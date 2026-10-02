"""Tests for the manual payment flow (pre-Paymob bridge).

Covers:
- POST /payment/manual (server-determined pricing, rate limit)
- GET /payment/manual/{order_ref} (owner only)
- POST /admin/login (separate admin credential)
- GET /admin/payments (masked phones, date filters)
- GET /admin/payments/{order_ref}/contact (audited reveal)
- POST /admin/payments/{order_ref}/approve (idempotent, concurrency-safe)
- POST /admin/payments/{order_ref}/reject (reason persisted, audited)
- payment_audit_log entries for every admin action
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.admin_models import Admin
from services.api.dependencies import get_db, get_password_hash
from services.api.main import app
from services.api.manual_payment_models import ManualPayment, PaymentAuditLog
from services.api.models import Base, CreditTransaction

USER_PHONE = "+201098765432"
OTHER_PHONE = "+201055555555"


@pytest.fixture
def client():
    """Create a test client with a fresh in-memory database."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Seed a separate admin credential (not a user account).
    with TestingSessionLocal() as db:
        db.add(
            Admin(
                username="admin1",
                password_hash=get_password_hash("admin-secret"),
            )
        )
        db.commit()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c._user_tokens = {}
        yield c
    app.dependency_overrides.clear()


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def _register_and_login(client, phone, password):
    reg = client.post("/auth/register", json={"phone": phone, "password": password})
    assert reg.status_code == 200, f"register failed: {reg.text}"
    login = client.post("/auth/login", json={"phone": phone, "password": password})
    assert login.status_code == 200, f"login failed: {login.text}"
    return login.json()["access_token"]


def _user_token(client):
    """Login as the primary test user (cached per client)."""
    if "primary" not in client._user_tokens:
        client._user_tokens["primary"] = _register_and_login(
            client, USER_PHONE, "testpass123"
        )
    return client._user_tokens["primary"]


def _other_user_token(client):
    """Login as a second, unrelated user (cached per client)."""
    if "other" not in client._user_tokens:
        client._user_tokens["other"] = _register_and_login(
            client, OTHER_PHONE, "otherpass1"
        )
    return client._user_tokens["other"]


def _admin_token(client):
    """Login with the separate admin credential."""
    resp = client.post(
        "/admin/login", json={"username": "admin1", "password": "admin-secret"}
    )
    assert resp.status_code == 200, f"admin login failed: {resp.text}"
    return resp.json()["access_token"]


class TestManualPaymentCreate:
    def test_create_standard_package(self, client):
        token = _user_token(client)
        resp = client.post(
            "/payment/manual",
            json={"package": "standard"},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["package"] == "standard"
        assert data["amount_egp"] == 30.0
        assert data["order_ref"].startswith("ELH-")
        # order_ref must contain a random component beyond the date part.
        assert len(data["order_ref"]) > len("ELH-YYYYMMDD-")

    def test_create_premium_package(self, client):
        token = _user_token(client)
        resp = client.post(
            "/payment/manual",
            json={"package": "premium"},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        assert resp.json()["amount_egp"] == 90.0

    def test_create_invalid_package_400(self, client):
        token = _user_token(client)
        resp = client.post(
            "/payment/manual",
            json={"package": "gold"},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400

    def test_create_unauthenticated_401(self, client):
        resp = client.post("/payment/manual", json={"package": "standard"})
        assert resp.status_code == 401

    def test_rate_limit_three_pending_per_day(self, client):
        token = _user_token(client)
        for i in range(3):
            resp = client.post(
                "/payment/manual",
                json={"package": "standard"},
                headers=_auth_headers(token),
            )
            assert resp.status_code == 200, f"attempt {i}: {resp.text}"
        # The 4th pending order today is rejected and no row is created.
        resp = client.post(
            "/payment/manual",
            json={"package": "standard"},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 429

        gen = app.dependency_overrides[get_db]()
        db = next(gen)
        try:
            pending = (
                db.query(ManualPayment)
                .filter(ManualPayment.status == "pending")
                .count()
            )
            assert pending == 3
        finally:
            db.close()


class TestManualPaymentLookup:
    def test_get_own_payment(self, client):
        token = _user_token(client)
        create = client.post(
            "/payment/manual",
            json={"package": "standard"},
            headers=_auth_headers(token),
        )
        order_ref = create.json()["order_ref"]
        resp = client.get(f"/payment/manual/{order_ref}", headers=_auth_headers(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["order_ref"] == order_ref
        assert data["status"] == "pending"

    def test_get_other_users_payment_404(self, client):
        """Non-owner lookup returns 404 (no existence leak)."""
        token = _user_token(client)
        create = client.post(
            "/payment/manual",
            json={"package": "standard"},
            headers=_auth_headers(token),
        )
        order_ref = create.json()["order_ref"]

        other_token = _other_user_token(client)
        resp = client.get(
            f"/payment/manual/{order_ref}", headers=_auth_headers(other_token)
        )
        assert resp.status_code == 404

    def test_get_nonexistent_404(self, client):
        token = _user_token(client)
        resp = client.get(
            "/payment/manual/ELH-19700101-000000", headers=_auth_headers(token)
        )
        assert resp.status_code == 404


class TestAdminAuth:
    def test_admin_login_invalid_credentials_401(self, client):
        resp = client.post(
            "/admin/login", json={"username": "admin1", "password": "wrong"}
        )
        assert resp.status_code == 401

    def test_admin_login_unknown_user_401(self, client):
        resp = client.post("/admin/login", json={"username": "nobody", "password": "x"})
        assert resp.status_code == 401

    def test_user_token_rejected_on_admin_endpoint(self, client):
        """A user JWT (sub=user_id) must not authorize admin endpoints."""
        token = _user_token(client)
        resp = client.get("/admin/payments", headers=_auth_headers(token))
        assert resp.status_code == 401

    def test_admin_token_rejected_on_user_endpoint(self, client):
        """An admin JWT (sub=admin:username) must not authorize user endpoints."""
        admin_token = _admin_token(client)
        resp = client.post(
            "/payment/manual",
            json={"package": "standard"},
            headers=_auth_headers(admin_token),
        )
        assert resp.status_code == 401


class TestAdminPayments:
    def test_list_payments_masked_phone(self, client):
        user_token = _user_token(client)
        create = client.post(
            "/payment/manual",
            json={"package": "standard"},
            headers=_auth_headers(user_token),
        )
        assert create.status_code == 200
        order_ref = create.json()["order_ref"]

        admin_token = _admin_token(client)
        resp = client.get("/admin/payments", headers=_auth_headers(admin_token))
        assert resp.status_code == 200
        payments = resp.json()
        entry = next(p for p in payments if p["order_ref"] == order_ref)
        # The full phone number must NOT appear anywhere in the list response.
        assert USER_PHONE not in resp.text
        assert "*" in entry["user_phone_masked"]
        assert entry["user_phone_masked"].startswith("+20")

    def test_list_invalid_date_422(self, client):
        admin_token = _admin_token(client)
        resp = client.get(
            "/admin/payments?date_from=not-a-date",
            headers=_auth_headers(admin_token),
        )
        assert resp.status_code == 422

    def test_list_date_filter(self, client):
        user_token = _user_token(client)
        create = client.post(
            "/payment/manual",
            json={"package": "standard"},
            headers=_auth_headers(user_token),
        )
        assert create.status_code == 200
        order_ref = create.json()["order_ref"]

        admin_token = _admin_token(client)
        # A date window that excludes today should not include the new order.
        resp = client.get(
            "/admin/payments?date_from=1970-01-01&date_to=1970-01-02",
            headers=_auth_headers(admin_token),
        )
        assert resp.status_code == 200
        assert all(p["order_ref"] != order_ref for p in resp.json())

    def test_reveal_contact(self, client):
        user_token = _user_token(client)
        create = client.post(
            "/payment/manual",
            json={"package": "standard"},
            headers=_auth_headers(user_token),
        )
        order_ref = create.json()["order_ref"]

        admin_token = _admin_token(client)
        resp = client.get(
            f"/admin/payments/{order_ref}/contact",
            headers=_auth_headers(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["user_phone"] == USER_PHONE


class TestApproveReject:
    def test_approve_grants_credits(self, client):
        user_token = _user_token(client)
        create = client.post(
            "/payment/manual",
            json={"package": "standard"},
            headers=_auth_headers(user_token),
        )
        order_ref = create.json()["order_ref"]

        admin_token = _admin_token(client)
        resp = client.post(
            f"/admin/payments/{order_ref}/approve",
            headers=_auth_headers(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["credits_granted"] == 10
        # Free tier: 3 starting credits + 10 granted = 13.
        assert data["new_balance"] == 13

        # Approval persists resolved_by/resolved_at and a credit transaction.
        gen = app.dependency_overrides[get_db]()
        db = next(gen)
        try:
            payment = db.query(ManualPayment).filter_by(order_ref=order_ref).first()
            assert payment is not None
            assert payment.status == "approved"
            assert payment.resolved_by is not None
            assert payment.resolved_at is not None
            txns = (
                db.query(CreditTransaction)
                .filter(CreditTransaction.user_id == payment.user_id)
                .all()
            )
            grants = [t for t in txns if t.amount == 10]
            assert len(grants) == 1
        finally:
            db.close()

    def test_approve_idempotent_no_double_grant(self, client):
        user_token = _user_token(client)
        create = client.post(
            "/payment/manual",
            json={"package": "premium"},
            headers=_auth_headers(user_token),
        )
        order_ref = create.json()["order_ref"]

        admin_token = _admin_token(client)
        first = client.post(
            f"/admin/payments/{order_ref}/approve",
            headers=_auth_headers(admin_token),
        )
        assert first.status_code == 200
        # 3 free + 30 premium = 33.
        assert first.json()["new_balance"] == 33

        second = client.post(
            f"/admin/payments/{order_ref}/approve",
            headers=_auth_headers(admin_token),
        )
        assert second.status_code == 200
        assert second.json()["status"] == "approved"
        # No double grant: idempotent response carries no new balance delta.
        assert "credits_granted" not in second.json()

    def test_approve_rejected_payment_400(self, client):
        user_token = _user_token(client)
        create = client.post(
            "/payment/manual",
            json={"package": "standard"},
            headers=_auth_headers(user_token),
        )
        order_ref = create.json()["order_ref"]

        admin_token = _admin_token(client)
        reject = client.post(
            f"/admin/payments/{order_ref}/reject",
            json={"reason": "no transfer found"},
            headers=_auth_headers(admin_token),
        )
        assert reject.status_code == 200

        approve = client.post(
            f"/admin/payments/{order_ref}/approve",
            headers=_auth_headers(admin_token),
        )
        assert approve.status_code == 400

    def test_reject_persists_reason(self, client):
        user_token = _user_token(client)
        create = client.post(
            "/payment/manual",
            json={"package": "standard"},
            headers=_auth_headers(user_token),
        )
        order_ref = create.json()["order_ref"]

        admin_token = _admin_token(client)
        resp = client.post(
            f"/admin/payments/{order_ref}/reject",
            json={"reason": "amount mismatch"},
            headers=_auth_headers(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rejected"
        assert data["reject_reason"] == "amount mismatch"

        # The reason is visible to the owner.
        lookup = client.get(
            f"/payment/manual/{order_ref}", headers=_auth_headers(user_token)
        )
        assert lookup.json()["reject_reason"] == "amount mismatch"

    def test_reject_approved_payment_400(self, client):
        user_token = _user_token(client)
        create = client.post(
            "/payment/manual",
            json={"package": "standard"},
            headers=_auth_headers(user_token),
        )
        order_ref = create.json()["order_ref"]

        admin_token = _admin_token(client)
        approve = client.post(
            f"/admin/payments/{order_ref}/approve",
            headers=_auth_headers(admin_token),
        )
        assert approve.status_code == 200

        reject = client.post(
            f"/admin/payments/{order_ref}/reject",
            json={"reason": "too late"},
            headers=_auth_headers(admin_token),
        )
        assert reject.status_code == 400

    def test_approve_unknown_order_404(self, client):
        admin_token = _admin_token(client)
        resp = client.post(
            "/admin/payments/ELH-19700101-000000/approve",
            headers=_auth_headers(admin_token),
        )
        assert resp.status_code == 404

    def test_audit_log_entries_created(self, client):
        """Every admin action (reveal/approve/reject) leaves an audit row."""
        user_token = _user_token(client)
        create = client.post(
            "/payment/manual",
            json={"package": "premium"},
            headers=_auth_headers(user_token),
        )
        order_ref = create.json()["order_ref"]

        admin_token = _admin_token(client)
        assert (
            client.get(
                f"/admin/payments/{order_ref}/contact",
                headers=_auth_headers(admin_token),
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/admin/payments/{order_ref}/approve",
                headers=_auth_headers(admin_token),
            ).status_code
            == 200
        )

        # A second payment to reject.
        create2 = client.post(
            "/payment/manual",
            json={"package": "standard"},
            headers=_auth_headers(user_token),
        )
        assert (
            client.post(
                f"/admin/payments/{create2.json()['order_ref']}/reject",
                json={"reason": "test"},
                headers=_auth_headers(admin_token),
            ).status_code
            == 200
        )

        # Verify via the DB through the same overridden dependency.
        gen = app.dependency_overrides[get_db]()
        db = next(gen)
        try:
            rows = db.query(PaymentAuditLog).all()
            actions = {r.action for r in rows}
            assert {"reveal_contact", "approve", "reject"} <= actions
            refs = {r.order_ref for r in rows}
            assert order_ref in refs
        finally:
            db.close()
