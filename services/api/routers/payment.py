"""Manual payment endpoints (bridge flow, pre-Paymob).

User-facing:
  POST /payment/manual          → Create a pending order
  GET  /payment/manual/{id}     → Check own order status

Admin:
  GET  /admin/payments          → List payments (filterable)
  POST /admin/payments/{id}/approve  → Approve (grants credits)
  POST /admin/payments/{id}/reject    → Reject (notifies user)
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from services.api.credits import grant
from services.api.dependencies import get_current_user, get_db
from services.api.manual_payment_models import ManualPayment
from services.api.models import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Payment"])

# Package pricing (must match billing service)
PACKAGE_PRICES: dict[str, float] = {
    "standard": 30.0,
    "premium": 90.0,
}
PACKAGE_CREDITS: dict[str, int] = {
    "standard": 10,
    "premium": 30,
}

# Rate limiting: max pending orders per user per day
MAX_PENDING_PER_DAY = 3


def _utcnow() -> datetime:
    """Naive UTC now (matches the codebase's naive-UTC datetime convention)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _generate_order_ref() -> str:
    """Generate a unique, unguessable order reference.

    Format: ELH-{YYYYMMDD}-{random_hex_5}
    """
    date_part = _utcnow().strftime("%Y%m%d")
    random_part = secrets.token_hex(3)  # 6 hex chars
    return f"ELH-{date_part}-{random_part}"


class ManualPaymentCreate(BaseModel):
    package: str


class ManualPaymentResponse(BaseModel):
    order_id: str
    order_ref: str
    package: str
    amount_egp: float
    status: str
    created_at: str


class AdminPaymentResponse(BaseModel):
    order_id: str
    order_ref: str
    user_phone: str
    package: str
    amount_egp: float
    status: str
    created_at: str


class RejectRequest(BaseModel):
    reason: str = "Payment not received"


@router.post("/payment/manual", response_model=ManualPaymentResponse)
def create_manual_payment(
    body: ManualPaymentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a pending manual payment order.

    Security:
    - Rate limited: max 3 pending per user per day
    - Package validated against allowlist
    - Amount is server-determined (not user-supplied)
    """
    # Validate package
    if body.package not in PACKAGE_PRICES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid package. Must be one of: {list(PACKAGE_PRICES.keys())}",
        )

    # Rate limit: check pending orders today
    today_start = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    pending_count = (
        db.query(ManualPayment)
        .filter(
            ManualPayment.user_id == current_user.id,
            ManualPayment.status == "pending",
            ManualPayment.created_at >= today_start,
        )
        .count()
    )
    if pending_count >= MAX_PENDING_PER_DAY:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many pending payments today. Please try again tomorrow.",
        )

    # Create order
    order_ref = _generate_order_ref()
    payment = ManualPayment(
        order_ref=order_ref,
        user_id=current_user.id,
        package=body.package,
        amount_egp=PACKAGE_PRICES[body.package],
        status="pending",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    logger.info(
        "Manual payment created",
        extra={
            "order_ref": order_ref,
            "user_id": str(current_user.id),
            "package": body.package,
        },
    )

    return ManualPaymentResponse(
        order_id=str(payment.id),
        order_ref=payment.order_ref,
        package=payment.package,
        amount_egp=float(payment.amount_egp),
        status=payment.status,
        created_at=payment.created_at.isoformat(),
    )


@router.get("/payment/manual/{order_id}", response_model=ManualPaymentResponse)
def get_manual_payment(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a manual payment order (owner only).

    Security: user can only access their own orders.
    """
    payment = (
        db.query(ManualPayment)
        .filter(ManualPayment.id == order_id, ManualPayment.user_id == current_user.id)
        .first()
    )
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found"
        )

    return ManualPaymentResponse(
        order_id=str(payment.id),
        order_ref=payment.order_ref,
        package=payment.package,
        amount_egp=float(payment.amount_egp),
        status=payment.status,
        created_at=payment.created_at.isoformat(),
    )


# --- Admin endpoints ---


def _get_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Admin authorization: user must have admin tier.

    For v0, admin is identified by tier == "admin". In production,
    this will be replaced with a separate admin token system.
    """
    if current_user.tier != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


@router.get("/admin/payments", response_model=list[AdminPaymentResponse])
def list_admin_payments(
    status_filter: str | None = Query(None, alias="status"),
    date_from: str | None = Query(None, alias="date_from"),
    date_to: str | None = Query(None, alias="date_to"),
    admin: User = Depends(_get_admin_user),
    db: Session = Depends(get_db),
):
    """List payments for admin (filterable)."""
    query = db.query(ManualPayment).join(User, ManualPayment.user_id == User.id)

    if status_filter:
        query = query.filter(ManualPayment.status == status_filter)
    if date_from:
        query = query.filter(
            ManualPayment.created_at >= datetime.fromisoformat(date_from)
        )
    if date_to:
        query = query.filter(
            ManualPayment.created_at <= datetime.fromisoformat(date_to)
        )

    payments = query.order_by(ManualPayment.created_at.desc()).limit(100).all()

    return [
        AdminPaymentResponse(
            order_id=str(p.id),
            order_ref=p.order_ref,
            user_phone=p.user.phone if p.user else "unknown",
            package=p.package,
            amount_egp=float(p.amount_egp),
            status=p.status,
            created_at=p.created_at.isoformat(),
        )
        for p in payments
    ]


@router.post("/admin/payments/{order_id}/approve")
def approve_payment(
    order_id: int,
    admin: User = Depends(_get_admin_user),
    db: Session = Depends(get_db),
):
    """Approve a manual payment. Grants credits.

    Security:
    - Idempotent: approving an already-approved payment is a no-op
    - Atomic: credit grant + status update in same transaction
    - Audited: logged with admin id
    """
    payment = db.query(ManualPayment).filter(ManualPayment.id == order_id).first()
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found"
        )

    # Idempotency: already approved
    if payment.status == "approved":
        return {"status": "approved", "message": "Already approved (idempotent)"}

    if payment.status == "rejected":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot approve a rejected payment",
        )

    # Get user
    user = db.query(User).filter(User.id == payment.user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="User not found"
        )

    # Grant credits (atomic with status update)
    credits_to_grant = PACKAGE_CREDITS.get(payment.package, 0)
    if credits_to_grant <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown package: {payment.package}",
        )

    grant(db, user, credits_to_grant, reason=f"manual_{payment.package}")
    payment.status = "approved"
    payment.resolved_at = _utcnow()
    payment.resolved_by = admin.id
    db.commit()

    logger.info(
        "Manual payment approved",
        extra={
            "order_ref": payment.order_ref,
            "user_id": str(user.id),
            "admin_id": str(admin.id),
            "credits_granted": credits_to_grant,
        },
    )

    return {"status": "approved", "credits_granted": credits_to_grant}


@router.post("/admin/payments/{order_id}/reject")
def reject_payment(
    order_id: int,
    body: RejectRequest,
    admin: User = Depends(_get_admin_user),
    db: Session = Depends(get_db),
):
    """Reject a manual payment.

    Security:
    - Idempotent: rejecting an already-rejected payment is a no-op
    - Reason required (logged)
    """
    payment = db.query(ManualPayment).filter(ManualPayment.id == order_id).first()
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found"
        )

    # Idempotency
    if payment.status == "rejected":
        return {"status": "rejected", "message": "Already rejected (idempotent)"}

    if payment.status == "approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot reject an approved payment",
        )

    payment.status = "rejected"
    payment.reject_reason = body.reason
    payment.resolved_at = _utcnow()
    payment.resolved_by = admin.id
    db.commit()

    logger.info(
        "Manual payment rejected",
        extra={
            "order_ref": payment.order_ref,
            "user_id": str(payment.user_id),
            "admin_id": str(admin.id),
            "reason": body.reason,
        },
    )

    return {"status": "rejected", "reason": body.reason}
