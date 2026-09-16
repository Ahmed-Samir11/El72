import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, UUID as sqlalchemy_UUID
from sqlalchemy.dialects.postgresql import UUID as postgres_UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import relationship

Base = declarative_base()


class DialectIdType(TypeDecorator):
    """Integer on SQLite, native UUID on PostgreSQL.

    Lets the same ORM models run against the local SQLite dev database and
    the production PostgreSQL database without dialect-specific code.
    """

    impl = String
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(Integer())
        return dialect.type_descriptor(postgres_UUID(as_uuid=True))


# Backwards-compatible alias (User.id historically used this name).
UserIdType = DialectIdType


def _new_user_id(context):
    """Keep the legacy SQLite schema compatible with PostgreSQL UUIDs."""
    if context.dialect.name == "sqlite":
        return context.connection.exec_driver_sql(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM users"
        ).scalar_one()
    return uuid.uuid4()


def _new_alert_id(context):
    """SQLite-safe auto-increment id; native UUID on PostgreSQL."""
    if context.dialect.name == "sqlite":
        return context.connection.exec_driver_sql(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM alerts"
        ).scalar_one()
    return uuid.uuid4()


def _new_credit_tx_id(context):
    """SQLite-safe auto-increment id for credit_transactions; UUID on Postgres."""
    if context.dialect.name == "sqlite":
        return context.connection.exec_driver_sql(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM credit_transactions"
        ).scalar_one()
    return uuid.uuid4()


def _new_affiliate_click_id(context):
    """SQLite-safe auto-increment id for affiliate_clicks; UUID on Postgres."""
    if context.dialect.name == "sqlite":
        return context.connection.exec_driver_sql(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM affiliate_clicks"
        ).scalar_one()
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"

    id = Column(UserIdType(), primary_key=True, default=_new_user_id)
    phone = Column(String(20), unique=True, nullable=False)
    name = Column(String(100), nullable=False, default="Customer")
    preferred_language = Column(String(10), nullable=False, default="en")
    password_hash = Column(String(128), nullable=False)
    salt = Column(String(32), nullable=False)
    tier = Column(String(20), nullable=False, default="free")
    valid_until = Column(DateTime, nullable=True)

    alerts = relationship("Alert", back_populates="user", cascade="all, delete-orphan")
    credits = relationship("UserCredit", back_populates="user", uselist=False, cascade="all, delete-orphan")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(DialectIdType(), primary_key=True, default=_new_alert_id)
    user_id = Column(DialectIdType(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Original ddl.sql columns
    target_url = Column(Text, nullable=True)
    target_price = Column(Numeric(10, 2), nullable=True)
    active_status = Column(Boolean, default=True, nullable=False)
    
    # alerts.sql columns (more granular tracking)
    sku = Column(Text, nullable=True)
    store_id = Column(Text, nullable=True)
    category = Column(Text, nullable=True)
    desired_price_egp = Column(Numeric(10, 2), nullable=True)
    target_price_bucket = Column(Text, nullable=True)
    notify_channel = Column(Text, default="whatsapp")

    user = relationship("User", back_populates="alerts")


class UserCredit(Base):
    """Per-user credit balance (one row per user).

    Keyed by the canonical ``User`` (UUID). Lazy-provisioned: a user with no
    row is treated as having their tier's starting balance.
    """
    __tablename__ = "user_credits"

    user_id = Column(DialectIdType(), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    balance = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="credits")


class CreditTransaction(Base):
    """Immutable ledger of credit grants and deductions."""
    __tablename__ = "credit_transactions"

    id = Column(DialectIdType(), primary_key=True, default=_new_credit_tx_id)
    user_id = Column(DialectIdType(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Integer, nullable=False)  # + grant, - deduction
    reason = Column(String(50), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AffiliateClick(Base):
    """A merchant click with enough context for deal attribution."""

    __tablename__ = "affiliate_clicks"

    id = Column(DialectIdType(), primary_key=True, default=_new_affiliate_click_id)
    store_id = Column(String(32), nullable=False)
    sku = Column(String(255), nullable=True)
    deal_id = Column(String(255), nullable=True)
    target_url = Column(Text, nullable=False)
    affiliate_url = Column(Text, nullable=False)
    clicked_at = Column(DateTime, nullable=False, default=datetime.utcnow)