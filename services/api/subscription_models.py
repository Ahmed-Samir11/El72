"""Recurring subscription models (Paymob subscriptions, Feature 7).

``Subscription`` tracks a monthly recurring subscription: the user's card
is charged every month by Paymob. It stores NO card data — only the Paymob
subscription id and the server-determined monthly amount (PCI-DSS
requirement 7.1).

``SubscriptionRenewal`` records each monthly renewal (idempotency guard via
the unique ``paymob_renewal_id``; plan 7.6).

Append-only and idempotency implications (review finding: document the
append-only trigger and idempotency implications):

- ``SubscriptionRenewal`` is append-only (a DB trigger blocks UPDATE and
  DELETE). A renewal is a historical record of a charge; it is never
  modified or deleted.
- The unique ``paymob_renewal_id`` is the idempotency guard: a duplicate
  webhook delivery for the same renewal is a no-op (no double charge,
  plan 7.6). This also means a status correction (e.g., a "failed" renewal
  later reported as "succeeded") is NOT applied — the first delivery wins.
  This is an accepted trade-off for v2 (the webhook is the source of
  truth; corrections require manual admin intervention).
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
    text,
)

from services.api.models import Base


def _utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(String(36), primary_key=True)
    user_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # The Paymob subscription id (unique; plan 7.6). Set at creation.
    paymob_subscription_id = Column(String(255), unique=True, nullable=False)
    # The Paymob payment-method id of the card charged each month.
    card_payment_method_id = Column(String(255), nullable=False)
    package = Column(String(20), nullable=False)
    # Fixed server-determined monthly amount (plan 7.1).
    amount_egp = Column(Numeric(10, 2), nullable=False)
    interval = Column(String(10), nullable=False, default="month")
    # active -> canceled/failed (failed = auto-canceled after 3 dunning
    # failures; plan 7.2).
    status = Column(String(20), nullable=False, default="active")
    # Consecutive failed renewals (dunning counter; plan 7.2).
    failed_renewals = Column(Integer, nullable=False, default=0)
    next_charge = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    canceled_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'canceled', 'failed')",
            name="subscriptions_status_check",
        ),
        CheckConstraint(
            "package IN ('standard', 'premium')",
            name="subscriptions_package_check",
        ),
        CheckConstraint(
            "amount_egp > 0",
            name="subscriptions_amount_check",
        ),
        CheckConstraint(
            "interval IN ('month')",
            name="subscriptions_interval_check",
        ),
        Index("ix_subscriptions_user_status", "user_id", "status"),
        # One active subscription per user, enforced at the database level
        # (plan 7.1). Partial unique index: only 'active' rows are
        # constrained, so a canceled/failed subscription does not block a
        # re-subscription. ``postgresql_where`` applies on Postgres and
        # ``sqlite_where`` on SQLite (review finding: the index was not
        # partial in SQLite, blocking re-subscription after cancel).
        Index(
            "uq_subscriptions_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )


class SubscriptionRenewal(Base):
    __tablename__ = "subscription_renewals"

    id = Column(String(36), primary_key=True)
    subscription_id = Column(
        String(36), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    # The Paymob renewal id (unique; idempotency guard, plan 7.6).
    paymob_renewal_id = Column(String(255), unique=True, nullable=False)
    amount_egp = Column(Numeric(10, 2), nullable=False)
    # succeeded / failed.
    status = Column(String(20), nullable=False)
    charged_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="subscription_renewals_status_check",
        ),
        CheckConstraint(
            "amount_egp > 0",
            name="subscription_renewals_amount_check",
        ),
        Index(
            "ix_subscription_renewals_subscription",
            "subscription_id",
            "created_at",
        ),
    )
