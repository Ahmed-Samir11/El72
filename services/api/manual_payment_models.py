"""Manual payment models for the bridge flow (pre-Paymob).

Users submit "I've paid" after manually transferring money. An admin
verifies and approves the payment, which grants credits.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import relationship

from services.api.models import Base, DialectIdType


def _utcnow() -> datetime:
    """Naive UTC now (matches the codebase's naive-UTC datetime convention)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _new_manual_payment_id(context):
    """SQLite-safe auto-increment id for manual_payments; UUID on Postgres."""
    if context.dialect.name == "sqlite":
        return context.connection.exec_driver_sql(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM manual_payments"
        ).scalar_one()
    return uuid.uuid4()


class ManualPayment(Base):
    """A pending manual payment order.

    Created when a user taps "I've Paid" in the app. Resolved (approved or
    rejected) by an admin after verifying the actual transfer.
    """

    __tablename__ = "manual_payments"

    id = Column(DialectIdType(), primary_key=True, default=_new_manual_payment_id)
    order_ref = Column(String(32), unique=True, nullable=False)  # "ELH-20250101-a3f2b"
    user_id = Column(
        DialectIdType(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    package = Column(String(20), nullable=False)  # "standard" | "premium"
    amount_egp = Column(Numeric(10, 2), nullable=False)
    # status: pending | approved | rejected
    status = Column(String(20), nullable=False, default="pending")
    reject_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(DialectIdType(), nullable=True)  # admin user id

    user = relationship("User")
