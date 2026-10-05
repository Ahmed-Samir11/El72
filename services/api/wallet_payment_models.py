"""Wallet payment tracking models (Paymob wallet flow, Feature 2).

``WalletPayment`` tracks a wallet payment (Vodafone Cash, Orange Money,
Etisalat Cash, Fawry) from ``/payment/confirm`` through ``/payment/confirm-otp``
until the Paymob webhook (Feature 4) records the final outcome in
``payment_logs``.

The wallet NUMBER is deliberately never stored — only the wallet type is kept
(plan 2.8: every wallet payment is logged with user_id, wallet_type, amount,
status and timestamp, but not the number).
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


class WalletPayment(Base):
    __tablename__ = "wallet_payments"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Set at /payment/confirm. Unique — one Paymob payment per record.
    paymob_payment_id = Column(String(255), unique=True, nullable=True)
    # Canonical upper-case wallet type (e.g. VODAFONE_CASH) — never the number.
    wallet_type = Column(String(30), nullable=False)
    package = Column(String(20), nullable=False)
    amount_egp = Column(Numeric(10, 2), nullable=False)
    # pending_otp -> processing -> succeeded/failed (final state comes from
    # the webhook via payment_logs); canceled on 3 failed OTPs or expiry.
    status = Column(String(20), nullable=False, default="pending_otp")
    # OTP brute-force guard (plan 2.1): max 3 attempts, then canceled.
    otp_attempts = Column(Integer, nullable=False, default=0)
    # OTP challenge expiry — 60 s after the payment was created (plan 2.1).
    otp_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_otp', 'processing', 'succeeded', "
            "'failed', 'canceled')",
            name="wallet_payments_status_check",
        ),
        # Mirror the SQL DDL CHECK constraints so ORM-created schemas
        # (e.g. tests via Base.metadata.create_all) match production.
        CheckConstraint(
            "package IN ('standard', 'premium')",
            name="wallet_payments_package_check",
        ),
        CheckConstraint(
            "amount_egp > 0",
            name="wallet_payments_amount_check",
        ),
        CheckConstraint(
            "otp_attempts >= 0",
            name="wallet_payments_otp_attempts_check",
        ),
        Index("ix_wallet_payments_user_created", "user_id", "created_at"),
    )
