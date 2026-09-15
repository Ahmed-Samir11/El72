import pytest
import uuid
from datetime import datetime, timedelta
from services.billing.models import PaymentLog, Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# In-memory SQLite for testing
engine = create_engine("sqlite:///:memory:")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

def test_payment_log_creation():
    db = SessionLocal()
    payment = PaymentLog(
        user_id=uuid.uuid4(),
        paymob_order_id="order123",
        amount=100.0,
        currency="EGP",
        status="success",
        tier="premium",
        created_at=datetime.utcnow()
    )
    db.add(payment)
    db.commit()
    assert payment.id is not None
    db.close()

def test_payment_log_attributes():
    user_id = uuid.uuid4()
    payment = PaymentLog(
        user_id=user_id,
        paymob_order_id="order456",
        amount=50.0,
        currency="USD",
        status="pending",
        tier="free"
    )
    assert payment.user_id == user_id
    assert payment.amount == 50.0
    assert payment.currency == "USD"

def test_payment_log_defaults():
    payment = PaymentLog(
        user_id=uuid.uuid4(),
        paymob_order_id="order789",
        amount=200.0,
        status="success",
        tier="enterprise"
    )
    assert payment.currency is None  # default not applied to object

def test_payment_log_table_name():
    assert PaymentLog.__tablename__ == "payment_logs"

def test_payment_log_columns():
    # Check if columns are defined
    assert hasattr(PaymentLog, 'id')
    assert hasattr(PaymentLog, 'user_id')
    assert hasattr(PaymentLog, 'paymob_order_id')
    assert hasattr(PaymentLog, 'amount')
    assert hasattr(PaymentLog, 'currency')
    assert hasattr(PaymentLog, 'status')
    assert hasattr(PaymentLog, 'tier')
    assert hasattr(PaymentLog, 'created_at')