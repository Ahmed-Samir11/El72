"""Tests for manual payment endpoints (Feature 0).

Covers:
- Creating a manual payment order
- Rate limiting (max 3 pending per day)
- Package validation
- Order lookup (owner only)
- Admin approval (grants credits, idempotent)
- Admin rejection (idempotent)
- Admin authorization (non-admin rejected)
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.dependencies import get_current_user, get_db
from services.api.manual_payment_models import ManualPayment
from services.api.models import Base as ApiBase
from services.api.models import User, UserCredit
from services.api.routers.payment import router as payment_router


def _utcnow() -> datetime:
    """Naive UTC now (matches the codebase's naive-UTC datetime convention)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def db_session():
    """Fresh in-memory DB with test users."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ApiBase.metadata.create_all(bind=engine)
    ManualPayment.__table__.create(bind=engine, checkfirst=True)

    Session = sessionmaker(bind=engine)
    session = Session()

    user = User(
        id=1,
        phone="+201118302763",
        name="Test User",
        preferred_language="en",
        password_hash="hashed",
        salt="salt",
        tier="free",
    )
    admin = User(
        id=2,
        phone="+201118302764",
        name="Admin",
        preferred_language="en",
        password_hash="hashed",
        salt="salt",
        tier="admin",
    )
    session.add(user)
    session.commit()
    session.add(admin)
    session.commit()
    session.refresh(user)
    session.refresh(admin)

    yield session, user, admin
    session.close()
    engine.dispose()


@pytest.fixture
def client(db_session):
    """Test client with dependency overrides."""
    session, user, admin = db_session

    app = FastAPI()
    app.include_router(payment_router)

    def override_get_db():
        yield session

    def override_get_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    with TestClient(app) as c:
        c._admin = admin
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def admin_client(db_session):
    """Test client with admin as current user."""
    session, user, admin = db_session

    app = FastAPI()
    app.include_router(payment_router)

    def override_get_db():
        yield session

    def override_get_current_user():
        return admin

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    with TestClient(app) as c:
        c._session = session
        yield c

    app.dependency_overrides.clear()


# --- User-facing endpoints ---


def test_create_manual_payment_success(client):
    """User can create a manual payment order."""
    resp = client.post("/payment/manual", json={"package": "standard"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["package"] == "standard"
    assert data["amount_egp"] == 30.0
    assert data["status"] == "pending"
    assert data["order_ref"].startswith("ELH-")


def test_create_manual_payment_premium(client):
    """Premium package has correct price."""
    resp = client.post("/payment/manual", json={"package": "premium"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["package"] == "premium"
    assert data["amount_egp"] == 90.0


def test_create_manual_payment_invalid_package(client):
    """Invalid package is rejected."""
    resp = client.post("/payment/manual", json={"package": "gold"})
    assert resp.status_code == 400
    assert "Invalid package" in resp.json()["detail"]


def test_create_manual_payment_rate_limit(client):
    """Max 3 pending per user per day."""
    for i in range(3):
        resp = client.post("/payment/manual", json={"package": "standard"})
        assert resp.status_code == 200, f"Order {i} should succeed"

    # 4th should be rate limited
    resp = client.post("/payment/manual", json={"package": "standard"})
    assert resp.status_code == 429
    assert "Too many pending" in resp.json()["detail"]


def test_get_manual_payment_owner(client):
    """User can view their own order."""
    resp = client.post("/payment/manual", json={"package": "premium"})
    order_id = resp.json()["order_id"]

    resp = client.get(f"/payment/manual/{order_id}")
    assert resp.status_code == 200
    assert resp.json()["package"] == "premium"
    assert resp.json()["amount_egp"] == 90.0


def test_get_manual_payment_not_found(client):
    """Non-existent order returns 404."""
    resp = client.get("/payment/manual/99999")
    assert resp.status_code == 404


# --- Admin endpoints ---


def test_non_admin_cannot_access_admin_endpoints(client):
    """Non-admin users get 403 on admin endpoints."""
    resp = client.get("/admin/payments")
    assert resp.status_code == 403

    resp = client.post("/admin/payments/1/approve")
    assert resp.status_code == 403


def test_admin_list_pending(admin_client):
    """Admin can list pending payments."""
    session = admin_client._session

    payment = ManualPayment(
        order_ref="ELH-20250101-test1",
        user_id=1,  # regular user
        package="standard",
        amount_egp=30.0,
        status="pending",
    )
    session.add(payment)
    session.commit()

    resp = admin_client.get("/admin/payments?status=pending")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["package"] == "standard"
    assert data[0]["user_phone"] == "+201118302763"


def test_admin_approve_grants_credits(admin_client):
    """Admin approval grants credits to the user."""
    session = admin_client._session

    payment = ManualPayment(
        order_ref="ELH-20250101-test2",
        user_id=1,  # regular user
        package="standard",
        amount_egp=30.0,
        status="pending",
    )
    session.add(payment)
    session.commit()
    session.refresh(payment)

    # Free tier lazily provisions 3 starting credits, so the balance after a
    # standard-package grant is 3 + 10.
    resp = admin_client.post(f"/admin/payments/{payment.id}/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    assert resp.json()["credits_granted"] == 10

    # Verify credits were granted
    credit = session.query(UserCredit).filter(UserCredit.user_id == 1).first()
    assert credit is not None
    assert credit.balance == 13


def test_admin_approve_idempotent(admin_client):
    """Approving twice is a no-op (credits only granted once)."""
    session = admin_client._session

    payment = ManualPayment(
        order_ref="ELH-20250101-test3",
        user_id=1,  # regular user
        package="premium",
        amount_egp=90.0,
        status="pending",
    )
    session.add(payment)
    session.commit()
    session.refresh(payment)

    # First approve
    resp = admin_client.post(f"/admin/payments/{payment.id}/approve")
    assert resp.json()["status"] == "approved"
    assert resp.json()["credits_granted"] == 30

    # Second approve (idempotent)
    resp = admin_client.post(f"/admin/payments/{payment.id}/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    assert "idempotent" in resp.json()["message"]

    # Credits should only be granted once (3 free + 30 premium, not 63)
    credit = session.query(UserCredit).filter(UserCredit.user_id == 1).first()
    assert credit.balance == 33


def test_admin_reject_sets_reason(admin_client):
    """Admin rejection sets the reason and status."""
    session = admin_client._session

    payment = ManualPayment(
        order_ref="ELH-20250101-test4",
        user_id=1,  # regular user
        package="standard",
        amount_egp=30.0,
        status="pending",
    )
    session.add(payment)
    session.commit()
    session.refresh(payment)

    resp = admin_client.post(
        f"/admin/payments/{payment.id}/reject",
        json={"reason": "No transfer found"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert resp.json()["reason"] == "No transfer found"

    # Verify no credits granted
    credit = session.query(UserCredit).filter(UserCredit.user_id == 1).first()
    assert credit is None  # No credit row created


def test_admin_cannot_approve_rejected(admin_client):
    """Cannot approve a rejected payment."""
    session = admin_client._session

    payment = ManualPayment(
        order_ref="ELH-20250101-test5",
        user_id=1,
        package="standard",
        amount_egp=30.0,
        status="rejected",
        reject_reason="test",
        resolved_at=_utcnow(),
    )
    session.add(payment)
    session.commit()
    session.refresh(payment)

    resp = admin_client.post(f"/admin/payments/{payment.id}/approve")
    assert resp.status_code == 400
    assert "Cannot approve" in resp.json()["detail"]


def test_admin_cannot_reject_approved(admin_client):
    """Cannot reject an approved payment."""
    session = admin_client._session

    payment = ManualPayment(
        order_ref="ELH-20250101-test6",
        user_id=1,
        package="standard",
        amount_egp=30.0,
        status="approved",
        resolved_at=_utcnow(),
    )
    session.add(payment)
    session.commit()
    session.refresh(payment)

    resp = admin_client.post(
        f"/admin/payments/{payment.id}/reject",
        json={"reason": "too late"},
    )
    assert resp.status_code == 400
    assert "Cannot reject" in resp.json()["detail"]


def test_admin_approve_not_found(admin_client):
    """Approving non-existent payment returns 404."""
    resp = admin_client.post("/admin/payments/99999/approve")
    assert resp.status_code == 404


def test_admin_reject_not_found(admin_client):
    """Rejecting non-existent payment returns 404."""
    resp = admin_client.post(
        "/admin/payments/99999/reject",
        json={"reason": "test"},
    )
    assert resp.status_code == 404
