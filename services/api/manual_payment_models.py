"""Manual payment models — bridge flow before Paymob integration.

These tables support the manual payment workflow described in
plans/paymob-integration.md:

- ManualPayment: a user's "I've paid" submission, pending admin verification
- PaymentAuditLog: append-only audit trail of admin actions (no UPDATE/DELETE)

CHECK constraints are declared both here (ORM) and in infra/sql/schema.sql
(canonical DDL) so SQLite test databases enforce the same invariants as
Postgres.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    UUID,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)

from services.api.models import Base, OperationalIdType


def _utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


class ManualPayment(Base):
    __tablename__ = "manual_payments"

    # Composite index for the primary admin query pattern: filter by status,
    # then range-scan created_at (date_from/date_to).
    __table_args__ = (
        Index("idx_manual_payments_status_created", "status", "created_at"),
        CheckConstraint("package IN ('standard', 'premium')"),
        CheckConstraint("amount_egp > 0"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected')"),
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
        OperationalIdType(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Snapshot of the payer's phone at creation time so the row keeps
    # forensic attribution even if the user account is later deleted.
    user_phone = Column(String(20), nullable=True)
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
    # Snapshot of the resolving admin's username (survives admin deletion).
    resolved_by_username = Column(String(50), nullable=True)


class PaymentAuditLog(Base):
    """Append-only audit trail of ALL payment events.

    Covers admin actions (approve / reject / reveal_contact) and system
    security events (webhook signature failures, OTP failures, token expiry,
    amount mismatches). No UPDATE or DELETE endpoints exist for this table;
    entries are insert-only by design. Postgres additionally enforces
    append-only via a BEFORE UPDATE OR DELETE trigger (see
    infra/sql/schema.sql).

    ``detail`` must be sanitized via
    :func:`services.api.payment_security.sanitize_for_log` — never raw card
    data, gateway tokens or OTPs.
    """

    __tablename__ = "payment_audit_log"

    __table_args__ = (
        CheckConstraint(
            "action IN ('approve', 'reject', 'reveal_contact', "
            "'webhook_received', 'webhook_signature_failed', 'otp_failed', "
            "'token_expired', 'amount_mismatch')",
        ),
    )

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    # action: approve | reject | reveal_contact | webhook_received |
    # webhook_signature_failed | otp_failed | token_expired | amount_mismatch
    action = Column(String(50), nullable=False)
    # Sanitized free-form detail (never raw card data / tokens / OTPs).
    detail = Column(Text, nullable=True)
    actor_id = Column(
        String(36), ForeignKey("admins.id", ondelete="SET NULL"), nullable=True
    )
    # Snapshot of the acting admin's username (survives admin deletion).
    actor_username = Column(String(50), nullable=True)
    # SET NULL (not CASCADE): audit rows are forensic records and must survive
    # user deletion.
    target_user_id = Column(
        OperationalIdType(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Snapshot of the target user's phone at action time.
    target_user_phone = Column(String(20), nullable=True)
    order_ref = Column(String(32), nullable=False, index=True)
    client_ip = Column(String(45), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
