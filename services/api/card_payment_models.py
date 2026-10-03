"""Card payment tracking models (Paymob card flow, Feature 1).

``CardPayment`` tracks a card payment from ``/payment/start`` through
``/payment/confirm`` until the Paymob webhook (Feature 4) records the final
outcome in ``payment_logs``. It stores NO card data — only Paymob payment
ids and server-determined amounts (PCI-DSS requirement 1.1).
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

from services.api.models import Base


def _utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


class CardPayment(Base):
    __tablename__ = "card_payments"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Set at /payment/confirm (None until then). Unique — one Paymob payment
    # per card payment record.
    paymob_payment_id = Column(String(255), unique=True, nullable=True)
    package = Column(String(20), nullable=False)
    amount_egp = Column(Numeric(10, 2), nullable=False)
    # pending -> succeeded/failed/canceled (final state comes from the
    # webhook via payment_logs).
    status = Column(String(20), nullable=False, default="pending")
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'canceled')",
            name="card_payments_status_check",
        ),
        Index("ix_card_payments_user_created", "user_id", "created_at"),
    )
