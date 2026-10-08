"""Payment router — manual payment bridge (pre-Paymob).

Implements the manual payment flow from plans/paymob-integration.md:
- POST /payment/manual — user submits "I've paid" (creates pending order)
- GET /payment/manual/{order_ref} — owner-only status lookup
- POST /admin/login — separate admin credential (not a user tier)
- GET /admin/payments — admin list (masked phone numbers by default)
- GET /admin/payments/{order_ref}/contact — audited full-contact reveal
- POST /admin/payments/{order_ref}/approve — idempotent, concurrency-safe
- POST /admin/payments/{order_ref}/reject — with reason, audited
- GET /payment/start — card/wallet staging token (Paymob customer)
- POST /payment/confirm — card (ToC token) or wallet (type + number)
- POST /payment/confirm-otp — wallet OTP confirmation (3-attempt budget)
- GET /payment/status/{payment_id} — owner-only status (card or wallet)

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
import re
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
from services.api.payment_security import (
    record_payment_event,
    sanitize_for_log,
    security_monitor,
)
from services.api.routers.auth import Token
from services.api.staging_store import (
    STAGING_TTL_SECONDS,
    StagingStore,
    get_staging_store,
)
from services.api.wallet_payment_models import WalletPayment
from services.billing.models import PaymentLog
from services.common.paymob_client import (
    PaymobApiError,
    confirm_wallet_otp,
    create_customer,
    create_payment,
    create_payment_method,
    create_wallet_payment_method,
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

# Wallet flow (Feature 2).
# Server-side allowlist of wallet types (plan 2.7): the plan's API tokens
# matched case-insensitively, stored/compared in canonical upper-case.
WALLET_TYPES = frozenset({"VODAFONE_CASH", "ORANGE_MONEY", "ETISALAT_CASH", "FAWRY"})
# Egyptian wallet number: 01[0125] + 8 digits (plan Feature 2).
WALLET_PHONE_RE = re.compile(r"^01[0125]\d{8}$")
# Rate limit: max 5 wallet confirms per user per hour (plan 2.2).
MAX_WALLET_CONFIRMS_PER_HOUR = 5
# OTP rules (plan 2.1): max 3 attempts per payment, 60 s expiry, 4-8 digits.
MAX_OTP_ATTEMPTS = 3
OTP_TTL_SECONDS = 60
OTP_RE = re.compile(r"^\d{4,8}$")
# Flood guard on /payment/confirm-otp: 5 requests per payment per 10 minutes
# (Feature 5 rate-limit table). Enforced with an atomic counter keyed by
# payment id — slowapi keys are request-derived and cannot see the body.
OTP_FLOOD_LIMIT = 5
OTP_FLOOD_WINDOW_SECONDS = 600


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


class PaymentConfirmBody(BaseModel):
    staging_token: str
    method_type: str = "card"  # "card" | "wallet"
    package: str  # "standard" | "premium"
    # card: ToC SDK output — a reference only, never card data.
    token: Optional[str] = None
    # wallet: type (plan 2.7 allowlist) + Egyptian wallet number.
    wallet_type: Optional[str] = None
    wallet_number: Optional[str] = None


class PaymentConfirmResponse(BaseModel):
    payment_id: str
    status: str
    # card only: for the ToS SDK (3DS).
    authentication_token: Optional[str] = None


class OtpConfirmBody(BaseModel):
    payment_id: str
    otp: str


class OtpConfirmResponse(BaseModel):
    status: str  # "processing" | "succeeded" | "failed"
    attempts_remaining: Optional[int] = None  # set when status == "failed"


class PaymentStatusResponse(BaseModel):
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


def _consume_staging_token(
    store: StagingStore,
    token: str,
    user: User,
    request: Request,
    db: Session,
) -> None:
    """Validate ownership and atomically consume a single-use staging token.

    Ownership is verified BEFORE consuming (non-destructive get) so a
    cross-user hijack attempt does not burn the legitimate owner's token
    (plan 1.2/2.5). Raises HTTPException on any failure; on success the
    token has been deleted from the store (1.4/2.5). Both rejection paths
    are audited as ``staging_rejected`` before the 400 is raised.
    """
    try:
        bound_user = store.get(token)
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
        # Token belongs to another user (hijacking attempt) — audited before
        # the 400. Deliberately NOT consumed: the owner can still use it.
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
        consumed = store.pop(token)
    except _redis.RedisError:
        raise HTTPException(
            status_code=503, detail="Payment service temporarily unavailable"
        ) from None
    if consumed is None:
        # Lost a race to a concurrent confirm (the token was just used).
        raise HTTPException(status_code=400, detail="Invalid or expired staging token")


def _paymob_payment_id(payment_resp: dict) -> str:
    """Extract the Paymob payment id from a create-payment response."""
    payment_id = payment_resp.get("id")
    if isinstance(payment_id, (int, str)) and payment_id:
        return str(payment_id)
    raise HTTPException(
        status_code=502, detail="Payment provider did not return a payment id"
    )


@router.post("/payment/confirm", response_model=PaymentConfirmResponse)
def confirm_payment(
    body: PaymentConfirmBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Confirm a payment with the requested method (card or wallet).

    Shared security (all methods):
    - The staging token is atomically consumed (single-use) and must be
      bound to the authenticated user (plan 1.2/1.4/2.5).
    - The amount is server-determined from the package (1.3/2.4) — the
      client never sends an amount.
    """
    if body.package not in PACKAGE_PRICING:
        raise HTTPException(
            status_code=400,
            detail="Invalid package. Available: standard, premium",
        )
    if body.method_type == "card":
        return _confirm_card_payment(body, request, db, user)
    if body.method_type == "wallet":
        return _confirm_wallet_payment(body, request, db, user)
    raise HTTPException(status_code=400, detail="Unsupported method type")


def _confirm_card_payment(
    body: PaymentConfirmBody,
    request: Request,
    db: Session,
    user: User,
) -> PaymentConfirmResponse:
    """Confirm a card payment with the on-device tokenization token (Feature 1).

    Only Paymob tokens cross the wire; card data never reaches us (1.1).
    Rate-limited to 3 confirms/hour per user (1.9).
    """
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

    _consume_staging_token(store, body.staging_token, user, request, db)

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

    payment_id = _paymob_payment_id(payment_resp)

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
    return PaymentConfirmResponse(
        payment_id=payment_id,
        authentication_token=payment_resp.get("authentication_token"),
        status="pending",
    )


def _confirm_wallet_payment(
    body: PaymentConfirmBody,
    request: Request,
    db: Session,
    user: User,
) -> PaymentConfirmResponse:
    """Confirm a wallet payment (Feature 2).

    Security (plan 2.x):
    - ``wallet_type`` is validated against the server-side allowlist (2.7).
    - ``wallet_number`` is format-validated BEFORE any Paymob call (2.2);
      it is sent to Paymob in the request payload only — never stored or
      logged.
    - Rate-limited to 5 confirms/hour per user (2.2), enforced BEFORE
      consuming the staging token.
    - Amount is server-determined from the package (2.4).
    - Every wallet payment is audited with the wallet TYPE, not the number
      (2.8).
    """
    if not body.wallet_type:
        raise HTTPException(status_code=400, detail="Missing wallet_type")
    if not body.wallet_number:
        raise HTTPException(status_code=400, detail="Missing wallet_number")
    wallet_type = body.wallet_type.strip().upper()
    # 2.7: server-side allowlist (case-insensitive match, canonical storage).
    if wallet_type not in WALLET_TYPES:
        raise HTTPException(status_code=400, detail="Invalid wallet type")
    # 2.2: fast Egyptian-number format validation before hitting Paymob.
    if not WALLET_PHONE_RE.match(body.wallet_number):
        raise HTTPException(status_code=400, detail="Invalid wallet number")

    # Serialize this user's confirmations (rate-limit + staging consumption).
    db.execute(select(User).where(User.id == user.id).with_for_update())

    store = get_staging_store()

    # 2.2: rate limit BEFORE consuming the staging token so a rejected
    # request does not burn a valid token.
    hour_ago = _utcnow() - timedelta(hours=1)
    wallet_count = (
        db.query(WalletPayment)
        .filter(
            WalletPayment.user_id == user.id,
            WalletPayment.paymob_payment_id.isnot(None),
            WalletPayment.created_at >= hour_ago,
        )
        .count()
    )
    if wallet_count >= MAX_WALLET_CONFIRMS_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail="Rate limit: maximum 5 wallet payment confirmations per hour",
        )

    _consume_staging_token(store, body.staging_token, user, request, db)

    # Server-determined amount (piastres) — the client never sets it.
    reference_id = f"elhaq-{user.id}-{body.package}"
    try:
        method = create_wallet_payment_method(
            body.staging_token, wallet_type, body.wallet_number
        )
        payment_resp = create_payment(
            method["id"],
            PACKAGE_PRICES_PAISA[body.package],
            "EGP",
            reference_id,
        )
    except PaymobApiError as exc:
        _paymob_error_response(exc)

    payment_id = _paymob_payment_id(payment_resp)

    # Trust Paymob's initial status when known; the plan contract defaults
    # to "pending_otp". The OTP expiry clock only runs for pending_otp.
    provider_status = payment_resp.get("status")
    if provider_status in ("processing", "succeeded"):
        initial_status = provider_status
        otp_expires_at = None
    else:
        initial_status = "pending_otp"
        otp_expires_at = _utcnow() + timedelta(seconds=OTP_TTL_SECONDS)

    payment = WalletPayment(
        user_id=user.id,
        paymob_payment_id=payment_id,
        wallet_type=wallet_type,
        package=body.package,
        amount_egp=PACKAGE_PRICING[body.package],
        status=initial_status,
        otp_expires_at=otp_expires_at,
    )
    db.add(payment)
    # 2.8: audit the wallet TYPE and amount — never the wallet number.
    record_payment_event(
        db,
        event_type="wallet_payment_created",
        user_id=str(user.id),
        payment_ref=payment_id,
        detail=sanitize_for_log(
            f"package={body.package} wallet_type={wallet_type}"
            f" amount_egp={PACKAGE_PRICING[body.package]}"
        ),
        ip_address=_client_ip(request),
    )
    db.commit()

    logger.info(
        "Wallet payment %s confirmed for user %s (%s/%s)",
        payment_id,
        user.id,
        wallet_type,
        body.package,
    )
    return PaymentConfirmResponse(payment_id=payment_id, status=initial_status)


@router.post("/payment/confirm-otp", response_model=OtpConfirmResponse)
def submit_wallet_otp(
    body: OtpConfirmBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Confirm a wallet payment with the OTP the user received (Feature 2).

    Security (plan 2.1/2.6):
    - Max 3 OTP attempts per payment; the 3rd failure cancels it.
    - The OTP expires 60 s after the payment was created; an expired
      challenge cancels the payment (the user must restart).
    - The OTP value is NEVER logged or audited — only outcomes.
    - Flood guard: 5 requests per payment per 10 minutes (Feature 5
      rate-limit table), enforced with an atomic counter keyed by payment
      id (slowapi keys are request-derived and cannot see the body).
    - Provider outages (502/503) do NOT consume an attempt: the outcome
      is unknown, so the user's attempt budget is preserved.
    """
    payment = (
        db.query(WalletPayment)
        .filter(
            WalletPayment.paymob_payment_id == body.payment_id,
            WalletPayment.user_id == user.id,
        )
        .first()
    )
    if payment is None:
        # 404 (not 403): no existence leak across users.
        raise HTTPException(status_code=404, detail="Payment not found")

    # Flood guard (5 per payment per 10 minutes).
    store = get_staging_store()
    try:
        flood_count = store.incr(
            f"paymob:otp_flood:{payment.id}", OTP_FLOOD_WINDOW_SECONDS
        )
    except _redis.RedisError:
        raise HTTPException(
            status_code=503, detail="Payment service temporarily unavailable"
        ) from None
    if flood_count > OTP_FLOOD_LIMIT:
        raise HTTPException(
            status_code=429, detail="Rate limit: too many OTP submissions"
        )

    # Serialize concurrent OTP submissions for this payment, then re-read
    # the authoritative row state under the lock.
    db.execute(
        select(WalletPayment).where(WalletPayment.id == payment.id).with_for_update()
    )
    db.refresh(payment)

    if payment.status != "pending_otp":
        if payment.status == "succeeded":
            detail = "Payment already succeeded"
        elif payment.status == "processing":
            detail = "Payment is already processing"
        elif payment.status == "canceled":
            detail = "Payment canceled (expired or too many failed OTP attempts)"
        else:  # failed (webhook-confirmed)
            detail = "Payment already failed"
        raise HTTPException(status_code=400, detail=detail)

    # 2.1: OTP expiry — 60 s from payment creation. Naive datetimes (as
    # returned by SQLite) are treated as UTC; Postgres TIMESTAMPTZ values
    # arrive timezone-aware.
    expires_at = payment.otp_expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at is None or _utcnow() > expires_at:
        payment.status = "canceled"
        record_payment_event(
            db,
            event_type="token_expired",
            user_id=str(user.id),
            payment_ref=payment.paymob_payment_id or "",
            detail=sanitize_for_log("otp_expired"),
            ip_address=_client_ip(request),
        )
        db.commit()
        raise HTTPException(
            status_code=400, detail="OTP expired, please restart the payment"
        )

    # Malformed OTP: reject fast WITHOUT consuming an attempt (a malformed
    # value would not reach Paymob anyway).
    if not OTP_RE.match(body.otp):
        raise HTTPException(status_code=400, detail="Invalid OTP format")

    # 2.1: attempt budget (defensive — the row is canceled at 3).
    if payment.otp_attempts >= MAX_OTP_ATTEMPTS:
        payment.status = "canceled"
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Payment canceled (too many failed OTP attempts)",
        )

    try:
        resp = confirm_wallet_otp(payment.paymob_payment_id, body.otp)
    except PaymobApiError as exc:
        # Provider outage: outcome UNKNOWN — do not consume an attempt.
        db.rollback()
        _paymob_error_response(exc)

    provider_status = resp.get("status") if isinstance(resp, dict) else None
    if provider_status in ("processing", "succeeded"):
        # OTP verified. Credits still wait for the webhook (Feature 4 is the
        # single source of truth for "payment succeeded").
        payment.status = provider_status
        db.commit()
        logger.info(
            "Wallet OTP verified for payment %s (status=%s)",
            payment.paymob_payment_id,
            provider_status,
        )
        return OtpConfirmResponse(status=provider_status)

    # Verification failed (or unknown provider status): consume one attempt.
    payment.otp_attempts += 1
    if payment.otp_attempts >= MAX_OTP_ATTEMPTS:
        payment.status = "canceled"
    # 2.6: the audit detail carries the attempt count ONLY — never the OTP.
    record_payment_event(
        db,
        event_type="otp_failed",
        user_id=str(user.id),
        payment_ref=payment.paymob_payment_id or "",
        detail=sanitize_for_log(f"attempts={payment.otp_attempts}"),
        ip_address=_client_ip(request),
    )
    # Feature 5 wiring (deferred to Feature 2): alert on 10+ OTP failures
    # within 1 hour.
    if security_monitor.record_failure("otp_failed"):
        logger.warning("Security alert: 10+ OTP failures within 1 hour")
    db.commit()
    logger.info(
        "Wallet OTP failed for payment %s (attempt %d)",
        payment.paymob_payment_id,
        payment.otp_attempts,
    )
    return OtpConfirmResponse(
        status="failed",
        attempts_remaining=max(0, MAX_OTP_ATTEMPTS - payment.otp_attempts),
    )


@router.get("/payment/status/{payment_id}", response_model=PaymentStatusResponse)
def get_payment_status(
    payment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get payment status (owner only, plan 1.8). Card and wallet payments
    resolve here; the final state comes from the Paymob webhook (recorded in
    ``payment_logs``). Until then the row's own status is returned (``pending``
    for cards, ``pending_otp``/``processing`` for wallets). A 404 (not 403)
    avoids leaking that a payment exists for someone else.
    """
    card = (
        db.query(CardPayment)
        .filter(
            CardPayment.paymob_payment_id == payment_id,
            CardPayment.user_id == user.id,
        )
        .first()
    )
    if card is not None:
        fallback_status = "pending"
        package, amount, created = card.package, card.amount_egp, card.created_at
    else:
        wallet = (
            db.query(WalletPayment)
            .filter(
                WalletPayment.paymob_payment_id == payment_id,
                WalletPayment.user_id == user.id,
            )
            .first()
        )
        if wallet is None:
            raise HTTPException(status_code=404, detail="Payment not found")
        fallback_status = wallet.status
        package, amount, created = wallet.package, wallet.amount_egp, wallet.created_at

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
    status_value = final.status if final is not None else fallback_status

    return PaymentStatusResponse(
        payment_id=payment_id,
        package=package,
        amount_egp=float(amount),
        status=status_value,
        created_at=created.isoformat(),
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
