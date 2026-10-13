"""Admin credential model — separate from user accounts.

Per plans/paymob-integration.md, admin endpoints are authorized with a
separate admin credential (username + hashed password), never with a user
tier. Admins are provisioned out-of-band (env-var bootstrap at startup or
manual DB insert); there is no self-service registration endpoint.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, Text

from services.api.models import Base


def _utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


class Admin(Base):
    __tablename__ = "admins"

    # String(36) to match the users.id convention (dashed UUID strings),
    # so FKs from audit/resolution columns work on both SQLite and Postgres.
    id = Column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()), nullable=False
    )
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class Refund(Base):
    """Record of an admin-processed refund (plan 6.4).

    Append-only: a refund is irreversible, so this table only gains rows.
    It is the idempotency guard for ``POST /admin/payments/{order_id}/refund``
    — a second refund for the same order is rejected (409) rather than
    double-deducting the user's credits.

    ``order_key`` is ``{method}:{order_id}`` so the uniqueness constraint is
    global across the four payment tables (manual / card / wallet / cash).
    """

    __tablename__ = "refunds"

    id = Column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()), nullable=False
    )
    order_key = Column(String(255), unique=True, nullable=False, index=True)
    method = Column(String(20), nullable=False)  # manual | card | wallet | cash
    order_id = Column(String(255), nullable=False)
    user_id = Column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    package = Column(String(20), nullable=False)
    amount_egp = Column(Numeric(10, 2), nullable=False)
    # Credits clawed back from the user's balance at refund time.
    credits_deducted = Column(Integer, nullable=False)
    reason = Column(Text, nullable=False)
    admin_id = Column(
        String(36), ForeignKey("admins.id", ondelete="SET NULL"), nullable=True
    )
    admin_username = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
