from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class PaymentLog(Base):
    __tablename__ = "payment_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)  # Temporarily removed FK for testing
    paymob_order_id = Column(Text, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(10), nullable=False, default="EGP")
    status = Column(String(50), nullable=False)
    tier = Column(String(20), nullable=False)
    valid_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default="now()")