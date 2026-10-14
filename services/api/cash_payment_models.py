"""Cash payment tracking models (Paymob cash flow, Feature 3).

``CashPayment`` tracks a cash payment (Fawry / bank) from
``/payment/confirm`` until the Paymob webhook (Feature 4) records the final
outcome in ``payment_logs``. The user pays at a cash point using the
random single-use ``payment_code``; the code expires after 24 h (plan 3.3).

The code is NOT PII — it identifies the payment, not the user (plan 3.1:
even if shared, credits can only land on the original owner's account,
because credit granting resolves the user from the server-side
``reference_id``).
"""

from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)

from services.api.models import Base, OperationalIdType


def _utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


class CashPayment(Base):
    __tablename__ = "cash_payments"

    id = Column(Integer, primary_key=True)
    # Reconciled with the operational schema: user ids are integers and the
    # payment record survives user deletion (SET NULL, not CASCADE).
    user_id = Column(
        OperationalIdType(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Set at /payment/confirm. Unique — one Paymob payment per record.
    paymob_payment_id = Column(String(255), unique=True, nullable=True)
    # Random single-use code (8 unambiguous chars, non-sequential).
    payment_code = Column(String(32), unique=True, nullable=False)
    cash_type = Column(String(20), nullable=False)
    package = Column(String(20), nullable=False)
    amount_egp = Column(Numeric(10, 2), nullable=False)
    # pending -> succeeded/failed (webhook); canceled on 24 h expiry.
    status = Column(String(20), nullable=False, default="pending")
    # Code/order expiry: 24 h from creation (plan 3.3).
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'canceled', 'refunded')",
            name="cash_payments_status_check",
        ),
        # Mirror the SQL DDL CHECK constraints so ORM-created schemas
        # (e.g. tests via Base.metadata.create_all) match production.
        CheckConstraint(
            "cash_type IN ('fawry', 'bank')",
            name="cash_payments_cash_type_check",
        ),
        CheckConstraint(
            "package IN ('standard', 'premium')",
            name="cash_payments_package_check",
        ),
        CheckConstraint(
            "amount_egp > 0",
            name="cash_payments_amount_check",
        ),
        Index("ix_cash_payments_user_created", "user_id", "created_at"),
    )
