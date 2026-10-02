"""Manual payment models — bridge flow before Paymob integration.

These tables support the manual payment workflow described in
plans/paymob-integration.md:

- ManualPayment: a user's "I've paid" submission, pending admin verification
- PaymentAuditLog: append-only audit trail of admin actions (no UPDATE/DELETE)
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    UUID,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)

from services.api.models import Base


def _utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


class ManualPayment(Base):
    __tablename__ = "manual_payments"

    # Composite index for the primary admin query pattern: filter by status,
    # then range-scan created_at (date_from/date_to).
    __table_args__ = (
        Index("idx_manual_payments_status_created", "status", "created_at"),
    )

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    # Public order identifier (e.g. "ELH-20250101-a3f2b1"). The internal
    # UUID `id` is opaque; clients and admins interact via order_ref.
    order_ref = Column(String(32), unique=True, nullable=False, index=True)
    # SET NULL (not CASCADE): payment history is a financial record and must
    # survive user deletion for auditing.
    user_id = Column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    package = Column(String(20), nullable=False)  # "standard" | "premium"
    amount_egp = Column(Numeric(10, 2), nullable=False)
    # status: pending | approved | rejected
    status = Column(String(20), nullable=False, default="pending")
    reject_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(
        String(36), ForeignKey("admins.id", ondelete="SET NULL"), nullable=True
    )


class PaymentAuditLog(Base):
    """Append-only audit trail for admin payment actions.

    No UPDATE or DELETE endpoints exist for this table; entries are
    insert-only by design.
    """

    __tablename__ = "payment_audit_log"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    action = Column(String(50), nullable=False)  # approve|reject|reveal_contact
    actor_id = Column(
        String(36), ForeignKey("admins.id", ondelete="SET NULL"), nullable=True
    )
    # SET NULL (not CASCADE): audit rows are forensic records and must survive
    # user deletion.
    target_user_id = Column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    order_ref = Column(String(32), nullable=False, index=True)
    client_ip = Column(String(45), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
