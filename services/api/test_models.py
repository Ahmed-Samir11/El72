import pytest
from services.api.models import User, Alert, Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# In-memory SQLite for testing
engine = create_engine("sqlite:///:memory:")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

def test_user_creation():
    db = SessionLocal()
    user = User(
        phone="+201234567890",
        password_hash="hashedpass",
        salt="salt",
        tier="free"
    )
    db.add(user)
    db.commit()
    assert user.id is not None
    db.close()

def test_alert_creation():
    db = SessionLocal()
    user = User(phone="+201234567891", password_hash="hash", salt="salt")
    db.add(user)
    db.commit()

    alert = Alert(
        user_id=user.id,
        target_url="https://example.com",
        target_price=100.0,
        active_status=True
    )
    db.add(alert)
    db.commit()
    assert alert.id is not None
    db.close()

def test_user_alert_relationship():
    db = SessionLocal()
    user = User(phone="+201234567892", password_hash="hash", salt="salt")
    db.add(user)
    db.commit()

    alert = Alert(user_id=user.id, target_url="https://test.com", target_price=50.0)
    db.add(alert)
    db.commit()

    # Test relationship
    db.refresh(user)
    assert len(user.alerts) == 1
    assert user.alerts[0].target_url == "https://test.com"
    db.close()

def test_user_table_name():
    assert User.__tablename__ == "users"

def test_alert_table_name():
    assert Alert.__tablename__ == "alerts"