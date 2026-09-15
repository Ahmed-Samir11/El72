from datetime import datetime

import uuid

from sqlalchemy import CHAR, Column, DateTime, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as postgres_UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.types import TypeDecorator


class GUID(TypeDecorator):
    """Use PostgreSQL UUIDs and a portable string representation in SQLite."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgres_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        value = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return value if dialect.name == "postgresql" else str(value)

    def process_result_value(self, value, dialect):
        if value is None or isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))

Base = declarative_base()


class PaymentLog(Base):
    __tablename__ = "payment_logs"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), nullable=False)
    paymob_order_id = Column(Text, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(10), nullable=False, default="EGP")
    status = Column(String(50), nullable=False)
    tier = Column(String(20), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)