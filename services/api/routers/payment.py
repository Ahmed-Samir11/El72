"""Payment router — manual payment bridge (pre-Paymob).

Implements the manual payment flow from plans/paymob-integration.md:
- POST /payment/manual — user submits "I've paid" (creates pending order)
- GET /payment/manual/{order_ref} — owner-only status lookup
- POST /admin/login — separate admin credential (not a user tier)
- GET /admin/payments — admin list (masked phone numbers by default)
- GET /admin/payments/{order_ref}/contact — audited full-contact reveal
- POST /admin/payments/{order_ref}/approve — idempotent, concurrency-safe
- POST /admin/payments/{order_ref}/reject — with reason, audited

Security properties:
- Package pricing is server-determined from an allowlist (no client amounts).
- Admin endpoints require a separate admin credential (JWT with
  sub="admin:<username>"), never a user tier.
- Approve/reject use an atomic compare-and-swap status update so concurrent
  requests can only grant credits once.
- Every admin action is written to the append-only payment_audit_log table.
"""

import logging
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import redis as _redis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.api.admin_models import Admin
from services.api.card_payment_models import CardPayment
from services.api.credits import get_balance, grant
from services.api.dependencies import (
    ALGORITHM,
    SECRET_KEY,
    create_access_token,
    get_current_user,
    get_db,
    pwd_context,
    security,
)
from services.api.manual_payment_models import ManualPayment
from services.api.models import User
from services.api.payment_security import record_payment_event, sanitize_for_log
from services.api.routers.auth import Token
from services.api.staging_store import STAGING_TTL_SECONDS, get_staging_store
from services.billing.models import PaymentLog
from services.common.paymob_client import (
    PaymobApiError,
    create_customer,
    create_payment,
    create_payment_method,
)

logger = logging.getLogger(__name__)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

# Admin tokens are signed with a domain-separated secret (never the raw user
# secret) and carry a short 1-hour lifetime, so a leaked admin token is less
# useful than a leaked user token. Set ADMIN_SECRET_KEY in production.
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY") or f"{SECRET_KEY}:admin"
ADMIN_TOKEN_EXPIRE_HOURS = 1

# Only peers in this (env-configured) set are trusted to supply X-Forwarded-For;
# otherwise the header is client-spoofable and ignored for audit capture.
TRUSTED_PROXIES = {
    p.strip() for p in os.getenv("TRUSTED_PROXIES", "").split(",") if p.strip()
}

# Package pricing (server-determined — clients never send amounts)
PACKAGE_PRICING = {
    "standard": 30.0,
    "premium": 90.0,
}

CREDITS_BY_PACKAGE = {
    "standard": 10,
    "premium": 30,
}

# Exact piastre (minor-unit) prices — the Paymob call uses integers, never
# float multiplication.
PACKAGE_PRICES_PAISA = {"standard": 3000, "premium": 9000}

MAX_PENDING_PER_DAY = 3

# Per-user card-flow rate limits (plan 1.9). The start limit is enforced
# with an atomic Redis counter; the confirm limit counts confirmed rows in
# the database under the user-row lock.
MAX_CARD_STARTS_PER_HOUR = 5
MAX_CARD_CONFIRMS_PER_HOUR = 3
CARD_START_WINDOW_SECONDS = 3600


def _utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


def _generate_order_ref() -> str:
    """Generate a unique, unguessable order reference.

    Format: ELH-{YYYYMMDD}-{random_hex_8} (32 bits of randomness).
    """
    date_part = _utcnow().strftime("%Y%m%d")
    random_part = secrets.token_hex(4)  # 8 hex chars
    return f"ELH-{date_part}-{random_part}"


def _mask_phone(phone: Optional[str]) -> str:
    """Mask a phone number for admin list views (keep prefix + last 2)."""
    if not phone:
        return ""
    if len(phone) <= 5:
        return phone[:2] + "****"
    return phone[:3] + "*" * (len(phone) - 5) + phone[-2:]


def _client_ip(request: Request) -> Optional[str]:
    """Best-effort client IP for audit capture.

    X-Forwarded-For is only honored when the direct peer is a configured
    trusted proxy (TRUSTED_PROXIES); otherwise it is client-spoofable and
    we record the direct socket address instead.
    """
    peer = request.client.host if request.client else None
    if peer in TRUSTED_PROXIES:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()[:45]
    return peer


def _audit_entry(
    db: Session,
    admin: Admin,
    target_user_id: Optional[str],
    order_ref: str,
    action: str,
    request: Request,
    target_user_phone: Optional[str] = None,
) -> None:
    """Append an audit entry via the single record_payment_event entry point
    (no UPDATE/DELETE path exists for this table)."""
    record_payment_event(
        db,
        event_type=action,
        user_id=target_user_id,
        payment_ref=order_ref,
        ip_address=_client_ip(request),
        actor_id=str(admin.id),
        actor_username=admin.username,
        target_user_phone=target_user_phone,
    )


def _get_admin_payment(db: Session, order_ref: str) -> ManualPayment:
    payment = (
        db.query(ManualPayment).filter(ManualPayment.order_ref == order_ref).first()
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


# ---------------------------------------------------------------------------
# Admin authentication (separate credential, not a user tier)
# ---------------------------------------------------------------------------


class AdminLogin(BaseModel):
    username: str
    password: str


def get_current_admin(
    token: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """Validate an admin JWT (sub='admin:<username>') against the admins table."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate admin credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token.credentials, ADMIN_SECRET_KEY, algorithms=[ALGORITHM]
        )
        sub = payload.get("sub", "")
    except JWTError:
        raise credentials_exception from None
    if not sub.startswith("admin:"):
        raise credentials_exception
    admin = db.query(Admin).filter(Admin.username == sub[len("admin:") :]).first()
    if admin is None:
        raise credentials_exception
    return admin


@router.post("/admin/login", response_model=Token, include_in_schema=False)
@limiter.limit("20/minute")
def admin_login(
    body: AdminLogin,
    request: Request,
    db: Session = Depends(get_db),
):
    """Login with a separate admin credential (not a user account).

    Rate-limited to 20 attempts/minute per client IP (brute-force guard).
    """
    admin = db.query(Admin).filter(Admin.username == body.username).first()
    if not admin or not pwd_context.verify(body.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    access_token = create_access_token(
        data={"sub": f"admin:{admin.username}"},
        expires_delta=timedelta(hours=ADMIN_TOKEN_EXPIRE_HOURS),
        secret_key=ADMIN_SECRET_KEY,
    )
    return {"access_token": access_token, "token_type": "bearer"}


# ---------------------------------------------------------------------------
# User endpoints
# ---------------------------------------------------------------------------


class ManualPaymentCreate(BaseModel):
    package: str  # "standard" | "premium"


class ManualPaymentResponse(BaseModel):
    id: str
    order_ref: str
    package: str
    amount_egp: float
    status: str
    reject_reason: Optional[str] = None
    created_at: str
    resolved_at: Optional[str] = None


@router.post("/payment/manual", response_model=ManualPaymentResponse)
def create_manual_payment(
    body: ManualPaymentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a pending manual payment order.

    Pricing is server-determined from the package allowlist — the client
    never sends an amount. Rate-limited to 3 pending orders per day.
    """
    # Validate package (server-side allowlist)
    if body.package not in PACKAGE_PRICING:
        raise HTTPException(
            status_code=400, detail="Invalid package. Available: standard, premium"
        )

    amount = PACKAGE_PRICING[body.package]

    # Lock the user row to serialize this user's pending-order creation
    # (makes the per-day rate limit concurrency-safe).
    db.execute(select(User).where(User.id == user.id).with_for_update())

    # Rate limit: check pending orders today
    today_start = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    pending_count = (
        db.query(ManualPayment)
        .filter(
            ManualPayment.user_id == user.id,
            ManualPayment.status == "pending",
            ManualPayment.created_at >= today_start,
        )
        .count()
    )
    if pending_count >= MAX_PENDING_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail="Rate limit: maximum 3 pending manual payments per day",
        )

    # Create the payment with a retry on order_ref collision.
    for _attempt in range(3):
        order_ref = _generate_order_ref()
        payment = ManualPayment(
            order_ref=order_ref,
            user_id=user.id,
            user_phone=user.phone,
            package=body.package,
            amount_egp=amount,
            status="pending",
        )
        db.add(payment)
        try:
            db.commit()
            break
        except IntegrityError:
            db.rollback()
    else:
        raise HTTPException(
            status_code=500, detail="Could not allocate an order reference"
        )

    return ManualPaymentResponse(
        id=str(payment.id),
        order_ref=payment.order_ref,
        package=payment.package,
        amount_egp=float(payment.amount_egp),
        status=payment.status,
        reject_reason=None,
        created_at=payment.created_at.isoformat(),
        resolved_at=None,
    )


@router.get("/payment/manual/{order_ref}", response_model=ManualPaymentResponse)
@limiter.limit("30/minute")
def get_manual_payment(
    request: Request,
    order_ref: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get manual payment status (owner only)."""
    payment = (
        db.query(ManualPayment)
        .filter(
            ManualPayment.order_ref == order_ref,
            ManualPayment.user_id == user.id,
        )
        .first()
    )
    if payment is None:
        # 404 (not 403) to avoid leaking that an order exists for someone else.
        raise HTTPException(status_code=404, detail="Payment not found")

    return ManualPaymentResponse(
        id=str(payment.id),
        order_ref=payment.order_ref,
        package=payment.package,
        amount_egp=float(payment.amount_egp),
        status=payment.status,
        reject_reason=payment.reject_reason,
        created_at=payment.created_at.isoformat(),
        resolved_at=payment.resolved_at.isoformat() if payment.resolved_at else None,
    )


# ---------------------------------------------------------------------------
# Card payment endpoints (Paymob card flow, Feature 1)
# ---------------------------------------------------------------------------


class PaymentStartResponse(BaseModel):
    staging_token: str
    expires_in: int


class CardConfirmBody(BaseModel):
    staging_token: str
    method_type: str = "card"
    token: str  # ToC SDK output — a reference only, never card data
    package: str  # "standard" | "premium"


class CardConfirmResponse(BaseModel):
    payment_id: str
    authentication_token: Optional[str] = None  # for the ToS SDK (3DS)
    status: str


class CardStatusResponse(BaseModel):
    payment_id: str
    package: str
    amount_egp: float
    status: str
    created_at: str


def _paymob_error_response(exc: PaymobApiError) -> None:
    """Map a Paymob API failure to a safe HTTP error.

    The detail never echoes the provider response body (it may contain
    sensitive context); only the status class is surfaced.
    """
    if exc.status_code == 503:
        raise HTTPException(
            status_code=503, detail="Payment provider is not configured"
        )
    raise HTTPException(status_code=502, detail="Payment provider request failed")


@router.get("/payment/start", response_model=PaymentStartResponse)
def start_card_payment(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Start a card payment: create a Paymob customer and return a staging token.

    The staging token is bound to THIS user in Redis with a 15-minute TTL and
    is single-use (plan 1.2/1.4). Rate-limited to 5 starts/hour per user via
    an atomic counter (plan 1.9).
    """
    store = get_staging_store()
    # NOTE (finding #8): the per-user start counter is incremented BEFORE
    # the Paymob call succeeds. This is a deliberate anti-abuse choice: a
    # user who fires 5 starts and then has Paymob fail on all of them has
    # consumed their hourly budget, which is acceptable because the cost
    # of provider abuse (5 Paymob API calls/hour per user) is bounded.
    try:
        count = store.incr(f"paymob:card_starts:{user.id}", CARD_START_WINDOW_SECONDS)
    except _redis.RedisError:
        # Redis unavailable — fail closed with a controlled 503 rather than
        # an unhandled 500 (finding: Redis failures must not leak 500s).
        raise HTTPException(
            status_code=503, detail="Payment service temporarily unavailable"
        ) from None
    if count > MAX_CARD_STARTS_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail="Rate limit: maximum 5 card payment starts per hour",
        )

    # Synthetic, PII-free customer identity (users have no email on file).
    # The uuid suffix ensures repeated /payment/start calls for the same
    # user produce distinct Paymob customers (finding #1).
    import uuid as _uuid

    try:
        customer = create_customer(f"u{user.id}-{_uuid.uuid4().hex[:8]}@elhaq.local")
    except PaymobApiError as exc:
        _paymob_error_response(exc)

    staging_token = customer.get("staging_token")
    if not isinstance(staging_token, str) or not staging_token:
        raise HTTPException(
            status_code=502, detail="Payment provider did not return a staging token"
        )
    try:
        store.set(staging_token, str(user.id))
    except _redis.RedisError:
        # The Paymob customer was created but we could not bind the staging
        # token; fail closed so no unbound token is ever returned to the client.
        raise HTTPException(
            status_code=503, detail="Payment service temporarily unavailable"
        ) from None

    logger.info("Card payment started for user %s", user.id)
    return PaymentStartResponse(
        staging_token=staging_token, expires_in=STAGING_TTL_SECONDS
    )


@router.post("/payment/confirm", response_model=CardConfirmResponse)
def confirm_card_payment(
    body: CardConfirmBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Confirm a card payment with the on-device tokenization token.

    Security (plan Feature 1):
    - The staging token is atomically consumed (single-use) and must be
      bound to the authenticated user (1.2/1.4).
    - The amount is server-determined from the package (1.3) — the client
      never sends an amount.
    - Only Paymob tokens cross the wire; card data never reaches us (1.1).
    - Rate-limited to 3 confirms/hour per user (1.9).
    """
    if body.package not in PACKAGE_PRICING:
        raise HTTPException(
            status_code=400,
            detail="Invalid package. Available: standard, premium",
        )
    if body.method_type != "card":
        raise HTTPException(status_code=400, detail="Unsupported method type")
    if not body.token:
        raise HTTPException(status_code=400, detail="Missing tokenization token")

    # Serialize this user's confirmations (rate-limit + staging consumption).
    db.execute(select(User).where(User.id == user.id).with_for_update())

    store = get_staging_store()

    # Rate limit BEFORE consuming the staging token so a rejected request
    # does not burn a valid token (finding #4).
    hour_ago = _utcnow() - timedelta(hours=1)
    confirm_count = (
        db.query(CardPayment)
        .filter(
            CardPayment.user_id == user.id,
            CardPayment.paymob_payment_id.isnot(None),
            CardPayment.created_at >= hour_ago,
        )
        .count()
    )
    if confirm_count >= MAX_CARD_CONFIRMS_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail="Rate limit: maximum 3 card payment confirmations per hour",
        )

    try:
        # Validate ownership BEFORE consuming (non-destructive get) so a
        # cross-user hijack attempt does not burn the legitimate owner's token.
        bound_user = store.get(body.staging_token)
    except _redis.RedisError:
        raise HTTPException(
            status_code=503, detail="Payment service temporarily unavailable"
        ) from None
    if bound_user is None:
        # Unknown or expired token — audited before the 400. Nothing to consume.
        record_payment_event(
            db,
            event_type="staging_rejected",
            user_id=str(user.id),
            payment_ref="",
            detail=sanitize_for_log("reason=unknown_or_expired_token"),
            ip_address=_client_ip(request),
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired staging token")
    if bound_user != str(user.id):
        # Token belongs to another user (hijacking attempt) — audited before the
        # 400. Deliberately NOT consumed: the owner can still use it.
        record_payment_event(
            db,
            event_type="staging_rejected",
            user_id=str(user.id),
            payment_ref="",
            detail=sanitize_for_log("reason=token_bound_to_other_user"),
            ip_address=_client_ip(request),
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired staging token")

    # Ownership verified — now atomically consume the single-use token.
    try:
        consumed = store.pop(body.staging_token)
    except _redis.RedisError:
        raise HTTPException(
            status_code=503, detail="Payment service temporarily unavailable"
        ) from None
    if consumed is None:
        # Lost a race to a concurrent confirm (the token was just used).
        raise HTTPException(status_code=400, detail="Invalid or expired staging token")

    # Server-determined amount (piastres) — the client never sets it.
    reference_id = f"elhaq-{user.id}-{body.package}"
    try:
        method = create_payment_method(body.token, "card")
        payment_resp = create_payment(
            method["id"],
            PACKAGE_PRICES_PAISA[body.package],
            "EGP",
            reference_id,
        )
    except PaymobApiError as exc:
        _paymob_error_response(exc)

    payment_id = payment_resp.get("id")
    if isinstance(payment_id, (int, str)) and payment_id:
        payment_id = str(payment_id)
    else:
        raise HTTPException(
            status_code=502, detail="Payment provider did not return a payment id"
        )

    payment = CardPayment(
        user_id=user.id,
        paymob_payment_id=payment_id,
        package=body.package,
        amount_egp=PACKAGE_PRICING[body.package],
        status="pending",
    )
    db.add(payment)
    record_payment_event(
        db,
        event_type="card_payment_created",
        user_id=str(user.id),
        payment_ref=payment_id,
        detail=sanitize_for_log(f"package={body.package}"),
        ip_address=_client_ip(request),
    )
    db.commit()

    logger.info(
        "Card payment %s confirmed for user %s (%s)",
        payment_id,
        user.id,
        body.package,
    )
    return CardConfirmResponse(
        payment_id=payment_id,
        authentication_token=payment_resp.get("authentication_token"),
        status="pending",
    )


@router.get("/payment/status/{payment_id}", response_model=CardStatusResponse)
def get_card_payment_status(
    payment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get card payment status (owner only, plan 1.8).

    The final state comes from the Paymob webhook (recorded in
    ``payment_logs``); until then the payment is ``pending``. A 404 (not
    403) avoids leaking that a payment exists for someone else.
    """
    payment = (
        db.query(CardPayment)
        .filter(
            CardPayment.paymob_payment_id == payment_id,
            CardPayment.user_id == user.id,
        )
        .first()
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    # Take the LATEST payment log for this order (a re-delivery or a
    # succeeded-after-failed sequence must not shadow the authoritative
    # terminal state with an older row). The id tiebreaker makes the pick
    # deterministic when two rows share the same created_at (e.g. webhook
    # re-delivery processed in the same second).
    final = (
        db.query(PaymentLog)
        .filter(PaymentLog.paymob_order_id == payment_id)
        .order_by(PaymentLog.created_at.desc(), PaymentLog.id.desc())
        .first()
    )
    status_value = final.status if final is not None else "pending"

    return CardStatusResponse(
        payment_id=payment_id,
        package=payment.package,
        amount_egp=float(payment.amount_egp),
        status=status_value,
        created_at=payment.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Admin endpoints (separate admin credential)
# ---------------------------------------------------------------------------


class AdminPaymentResponse(BaseModel):
    id: str
    order_ref: str
    user_phone_masked: str
    package: str
    amount_egp: float
    status: str
    reject_reason: Optional[str] = None
    created_at: str
    resolved_at: Optional[str] = None


@router.get(
    "/admin/payments",
    response_model=list[AdminPaymentResponse],
    include_in_schema=False,
)
@limiter.limit("20/minute")
def list_manual_payments(
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    status_filter: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
):
    """List manual payments for admins (phone numbers masked by default).

    Invalid date filter values are rejected by FastAPI with a 422.
    """
    query = db.query(ManualPayment, User).join(User, ManualPayment.user_id == User.id)
    if status_filter:
        query = query.filter(ManualPayment.status == status_filter)
    if date_from is not None:
        query = query.filter(
            ManualPayment.created_at
            >= datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
        )
    if date_to is not None:
        query = query.filter(
            ManualPayment.created_at
            <= datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc)
        )

    payments = query.order_by(ManualPayment.created_at.desc()).limit(100).all()

    return [
        {
            "id": str(p.id),
            "order_ref": p.order_ref,
            "user_phone_masked": _mask_phone(user.phone),
            "package": p.package,
            "amount_egp": float(p.amount_egp),
            "status": p.status,
            "reject_reason": p.reject_reason,
            "created_at": p.created_at.isoformat(),
            "resolved_at": p.resolved_at.isoformat() if p.resolved_at else None,
        }
        for p, user in payments
    ]


@router.get(
    "/admin/payments/{order_ref}/contact", response_model=dict, include_in_schema=False
)
@limiter.limit("20/minute")
def reveal_payment_contact(
    request: Request,
    order_ref: str,
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    """Reveal the full phone number for one payment (audited action)."""
    payment = _get_admin_payment(db, order_ref)
    user = db.query(User).filter(User.id == payment.user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _audit_entry(
        db,
        admin,
        payment.user_id,
        payment.order_ref,
        "reveal_contact",
        request,
        target_user_phone=payment.user_phone,
    )
    db.commit()
    return {
        "order_ref": payment.order_ref,
        "user_phone": user.phone,
    }


class RejectBody(BaseModel):
    reason: str


@router.post(
    "/admin/payments/{order_ref}/approve", response_model=dict, include_in_schema=False
)
@limiter.limit("20/minute")
def approve_manual_payment(
    request: Request,
    order_ref: str,
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    """Approve a pending manual payment and grant credits.

    Concurrency-safe: the pending->approved transition is an atomic
    compare-and-swap; only the winning request grants credits. The status
    update, credit grant, and audit entry commit as one transaction.
    """
    payment = _get_admin_payment(db, order_ref)
    if payment.status == "approved":
        # Idempotent: already approved.
        return {
            "id": str(payment.id),
            "order_ref": payment.order_ref,
            "status": "approved",
            "message": "Payment already approved (idempotent)",
        }
    if payment.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve payment in '{payment.status}' state",
        )

    user = db.query(User).filter(User.id == payment.user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Atomically claim the pending -> approved transition.
    result = db.execute(
        update(ManualPayment)
        .where(
            ManualPayment.id == payment.id,
            ManualPayment.status == "pending",
        )
        .values(
            status="approved",
            resolved_at=_utcnow(),
            resolved_by=str(admin.id),
            resolved_by_username=admin.username,
        )
    )
    if result.rowcount == 0:
        # Lost the race to a concurrent approve.
        db.rollback()
        raise HTTPException(status_code=409, detail="Payment was concurrently resolved")

    # We won the transition: grant credits + audit in the same transaction.
    credits_to_grant = CREDITS_BY_PACKAGE[payment.package]
    grant(db, user, credits_to_grant, reason=f"manual_{payment.package}")
    _audit_entry(
        db,
        admin,
        payment.user_id,
        payment.order_ref,
        "approve",
        request,
        target_user_phone=payment.user_phone,
    )
    db.commit()

    logger.info(
        "Approved manual payment %s for user %s (%d credits)",
        payment.order_ref,
        user.id,
        credits_to_grant,
    )

    return {
        "id": str(payment.id),
        "order_ref": payment.order_ref,
        "status": "approved",
        "credits_granted": credits_to_grant,
        "new_balance": get_balance(db, user),
    }


@router.post(
    "/admin/payments/{order_ref}/reject", response_model=dict, include_in_schema=False
)
@limiter.limit("20/minute")
def reject_manual_payment(
    request: Request,
    order_ref: str,
    body: RejectBody,
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    """Reject a pending manual payment with a reason (audited)."""
    payment = _get_admin_payment(db, order_ref)
    if payment.status == "rejected":
        return {
            "id": str(payment.id),
            "order_ref": payment.order_ref,
            "status": "rejected",
            "message": "Payment already rejected (idempotent)",
        }
    if payment.status != "pending":
        raise HTTPException(
            status_code=400, detail=f"Cannot reject payment in '{payment.status}' state"
        )

    # Atomically claim the pending -> rejected transition.
    result = db.execute(
        update(ManualPayment)
        .where(
            ManualPayment.id == payment.id,
            ManualPayment.status == "pending",
        )
        .values(
            status="rejected",
            reject_reason=body.reason,
            resolved_at=_utcnow(),
            resolved_by=str(admin.id),
            resolved_by_username=admin.username,
        )
    )
    if result.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=409, detail="Payment was concurrently resolved")

    _audit_entry(
        db,
        admin,
        payment.user_id,
        payment.order_ref,
        "reject",
        request,
        target_user_phone=payment.user_phone,
    )
    db.commit()

    logger.info("Rejected manual payment %s: %s", payment.order_ref, body.reason)

    return {
        "id": str(payment.id),
        "order_ref": payment.order_ref,
        "status": "rejected",
        "reject_reason": body.reason,
    }
