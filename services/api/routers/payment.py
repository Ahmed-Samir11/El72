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
from services.api.payment_security import record_payment_event
from services.api.routers.auth import Token

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

MAX_PENDING_PER_DAY = 3


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
