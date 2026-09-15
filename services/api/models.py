import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, UUID as sqlalchemy_UUID
from sqlalchemy.dialects.postgresql import UUID as postgres_UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(postgres_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone = Column(String(20), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    salt = Column(String(32), nullable=False)
    tier = Column(String(20), nullable=False, default="free")
    valid_until = Column(DateTime, nullable=True)

    alerts = relationship("Alert", back_populates="user", cascade="all, delete-orphan")
    credits = relationship("UserCredit", back_populates="user", uselist=False, cascade="all, delete-orphan")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(postgres_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(postgres_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
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

    user_id = Column(postgres_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    balance = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="credits")


class CreditTransaction(Base):
    """Immutable ledger of credit grants and deductions."""
    __tablename__ = "credit_transactions"

    id = Column(postgres_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(postgres_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Integer, nullable=False)  # + grant, - deduction
    reason = Column(String(50), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AffiliateClick(Base):
    """A merchant click with enough context for deal attribution."""

    __tablename__ = "affiliate_clicks"

    id = Column(postgres_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(String(32), nullable=False)
    sku = Column(String(255), nullable=True)
    deal_id = Column(String(255), nullable=True)
    target_url = Column(Text, nullable=False)
    affiliate_url = Column(Text, nullable=False)
    clicked_at = Column(DateTime, nullable=False, default=datetime.utcnow)