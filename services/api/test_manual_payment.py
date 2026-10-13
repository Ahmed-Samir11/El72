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

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.admin_models import Admin, Refund
from services.api.card_payment_models import CardPayment
from services.api.cash_payment_models import CashPayment
from services.api.dependencies import get_db, get_password_hash
from services.api.main import app
from services.api.manual_payment_models import ManualPayment, PaymentAuditLog
from services.api.models import Base, CreditTransaction, User
from services.api.wallet_payment_models import WalletPayment

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


def _admin_jwt_for(username: str) -> str:
    """Mint an admin JWT for ``username`` (signed under the admin secret).

    Used to test the verified dual-admin approval flow: the approver must
    present their own token.
    """
    import jwt as pyjwt

    from services.api.dependencies import ALGORITHM
    from services.api.routers.payment import ADMIN_SECRET_KEY

    return pyjwt.encode(
        {"sub": f"admin:{username}"}, ADMIN_SECRET_KEY, algorithm=ALGORITHM
    )


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
        entry = next(p for p in payments if p["order_id"] == order_ref)
        # The full phone number must NOT appear anywhere in the list response.
        assert USER_PHONE not in resp.text
        assert "*" in entry["user_phone"]
        assert entry["user_phone"].startswith("+20")

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
            # Attribution snapshots survive independently of the FKs.
            assert all(r.actor_username == "admin1" for r in rows)
            assert all(r.target_user_phone == USER_PHONE for r in rows)
            payment = db.query(ManualPayment).filter_by(order_ref=order_ref).first()
            assert payment.user_phone == USER_PHONE
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Feature 6: Admin & dispute management
# ---------------------------------------------------------------------------


def _seed_user(client, phone):
    """Register + login a user; return (user_id, phone)."""
    reg = client.post("/auth/register", json={"phone": phone, "password": "pw12345678"})
    assert reg.status_code == 200, f"register failed: {reg.text}"
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        user = db.query(User).filter_by(phone=phone).first()
        user_id = user.id
    finally:
        db.close()
    return user_id, phone


def _seed_payment_row(client, model, **fields):
    """Insert a payment row directly via the DB (bypasses the payment flow)."""
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        db.add(model(**fields))
        db.commit()
    finally:
        db.close()


class TestUnifiedPayments:
    def test_list_includes_all_four_methods(self, client):
        admin_token = _admin_token(client)
        user_id, _ = _seed_user(client, USER_PHONE)
        _seed_payment_row(
            client,
            ManualPayment,
            order_ref="ELH-UNIF-1",
            user_id=user_id,
            user_phone=USER_PHONE,
            package="standard",
            amount_egp=30,
            status="pending",
        )
        _seed_payment_row(
            client,
            CardPayment,
            paymob_payment_id="pm_card_1",
            user_id=user_id,
            package="premium",
            amount_egp=90,
            status="succeeded",
        )
        _seed_payment_row(
            client,
            WalletPayment,
            paymob_payment_id="pm_wallet_1",
            user_id=user_id,
            wallet_type="fawry",
            package="standard",
            amount_egp=30,
            status="succeeded",
        )
        _seed_payment_row(
            client,
            CashPayment,
            paymob_payment_id="pm_cash_1",
            user_id=user_id,
            payment_code="CODE123",
            cash_type="fawry",
            package="premium",
            amount_egp=90,
            status="pending",
            expires_at=datetime(2025, 1, 2, 12, 0, 0),
        )
        resp = client.get("/admin/payments", headers=_auth_headers(admin_token))
        assert resp.status_code == 200
        rows = resp.json()
        methods = {r["method"] for r in rows}
        assert methods == {"manual", "card", "wallet", "cash"}
        # Phones are masked by default.
        assert all("*" in r["user_phone"] for r in rows)

    def test_filter_by_user_phone(self, client):
        admin_token = _admin_token(client)
        user_id, _ = _seed_user(client, USER_PHONE)
        other_id, _ = _seed_user(client, OTHER_PHONE)
        _seed_payment_row(
            client,
            ManualPayment,
            order_ref="ELH-FILT-1",
            user_id=user_id,
            user_phone=USER_PHONE,
            package="standard",
            amount_egp=30,
            status="pending",
        )
        _seed_payment_row(
            client,
            ManualPayment,
            order_ref="ELH-FILT-2",
            user_id=other_id,
            user_phone=OTHER_PHONE,
            package="standard",
            amount_egp=30,
            status="pending",
        )
        resp = client.get(
            "/admin/payments",
            headers=_auth_headers(admin_token),
            params={"user": USER_PHONE},
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["order_id"] == "ELH-FILT-1"

    def test_filter_by_status(self, client):
        admin_token = _admin_token(client)
        user_id, _ = _seed_user(client, USER_PHONE)
        _seed_payment_row(
            client,
            ManualPayment,
            order_ref="ELH-STAT-1",
            user_id=user_id,
            user_phone=USER_PHONE,
            package="standard",
            amount_egp=30,
            status="pending",
        )
        _seed_payment_row(
            client,
            ManualPayment,
            order_ref="ELH-STAT-2",
            user_id=user_id,
            user_phone=USER_PHONE,
            package="standard",
            amount_egp=30,
            status="approved",
        )
        resp = client.get(
            "/admin/payments",
            headers=_auth_headers(admin_token),
            params={"status_filter": "pending"},
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["order_id"] == "ELH-STAT-1"


class TestRefund:
    def _make_refundable(self, client, admin_token, package="standard"):
        user_id, _ = _seed_user(client, USER_PHONE)
        # Give the user credits so the claw-back is observable.
        gen = app.dependency_overrides[get_db]()
        db = next(gen)
        try:
            from services.api.credits import grant

            grant(db, db.query(User).filter_by(id=user_id).first(), 15, reason="seed")
            db.commit()
        finally:
            db.close()
        _seed_payment_row(
            client,
            ManualPayment,
            order_ref="ELH-REF-1",
            user_id=user_id,
            user_phone=USER_PHONE,
            package=package,
            amount_egp=30 if package == "standard" else 90,
            status="approved",
        )
        return user_id

    def test_refund_deducts_credits_and_logs(self, client):
        admin_token = _admin_token(client)
        self._make_refundable(client, admin_token, package="standard")
        resp = client.post(
            "/admin/payments/ELH-REF-1/refund",
            headers=_auth_headers(admin_token),
            json={"reason": "customer requested refund"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "refunded"
        assert body["credits_deducted"] == 10  # standard package
        # Free tier starts at 3; +15 seed, -10 claw-back => 8.
        assert body["new_balance"] == 8

        # A Refund row was recorded.
        gen = app.dependency_overrides[get_db]()
        db = next(gen)
        try:
            refund = db.query(Refund).filter_by(order_key="manual:ELH-REF-1").first()
            assert refund is not None
            assert refund.credits_deducted == 10
            # An audit entry was written.
            audit = (
                db.query(PaymentAuditLog)
                .filter_by(action="refund", order_ref="ELH-REF-1")
                .first()
            )
            assert audit is not None
            assert audit.actor_username == "admin1"
        finally:
            db.close()

    def test_refund_idempotent_second_409(self, client):
        admin_token = _admin_token(client)
        self._make_refundable(client, admin_token, package="standard")
        first = client.post(
            "/admin/payments/ELH-REF-1/refund",
            headers=_auth_headers(admin_token),
            json={"reason": "customer requested refund"},
        )
        assert first.status_code == 200
        second = client.post(
            "/admin/payments/ELH-REF-1/refund",
            headers=_auth_headers(admin_token),
            json={"reason": "customer requested refund"},
        )
        assert second.status_code == 409

    def test_refund_unknown_payment_404(self, client):
        admin_token = _admin_token(client)
        resp = client.post(
            "/admin/payments/ELH-NOPE/refund",
            headers=_auth_headers(admin_token),
            json={"reason": "customer requested refund"},
        )
        assert resp.status_code == 404

    def test_refund_requires_reason(self, client):
        admin_token = _admin_token(client)
        self._make_refundable(client, admin_token, package="standard")
        resp = client.post(
            "/admin/payments/ELH-REF-1/refund",
            headers=_auth_headers(admin_token),
            json={"reason": ""},
        )
        assert resp.status_code == 422

    def test_refund_rejects_incomplete_payment(self, client):
        # A pending payment has no granted credits to claw back, so it must
        # not be refundable.
        admin_token = _admin_token(client)
        user_id, _ = _seed_user(client, USER_PHONE)
        _seed_payment_row(
            client,
            ManualPayment,
            order_ref="ELH-PEND-1",
            user_id=user_id,
            user_phone=USER_PHONE,
            package="standard",
            amount_egp=30,
            status="pending",
        )
        resp = client.post(
            "/admin/payments/ELH-PEND-1/refund",
            headers=_auth_headers(admin_token),
            json={"reason": "customer requested refund"},
        )
        assert resp.status_code == 400, resp.text

    def test_refund_card_payment(self, client):
        # A succeeded card payment is refundable; credits are clawed back
        # and the payment is marked refunded.
        admin_token = _admin_token(client)
        user_id, _ = _seed_user(client, USER_PHONE)
        _seed_payment_row(
            client,
            CardPayment,
            paymob_payment_id="pm_card_ref",
            user_id=user_id,
            package="standard",
            amount_egp=30,
            status="succeeded",
        )
        resp = client.post(
            "/admin/payments/pm_card_ref/refund",
            headers=_auth_headers(admin_token),
            json={"reason": "card chargeback"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "refunded"
        assert body["credits_deducted"] == 10
        # The payment row is marked refunded.
        gen = app.dependency_overrides[get_db]()
        db = next(gen)
        try:
            p = db.query(CardPayment).filter_by(paymob_payment_id="pm_card_ref").first()
            assert p.status == "refunded"
        finally:
            db.close()

    def test_refund_cash_payment(self, client):
        # A succeeded cash payment is refundable.
        admin_token = _admin_token(client)
        user_id, _ = _seed_user(client, USER_PHONE)
        _seed_payment_row(
            client,
            CashPayment,
            paymob_payment_id="pm_cash_ref",
            user_id=user_id,
            payment_code="CODEREF",
            cash_type="fawry",
            package="premium",
            amount_egp=90,
            status="succeeded",
            expires_at=datetime(2025, 1, 2, 12, 0, 0),
        )
        resp = client.post(
            "/admin/payments/pm_cash_ref/refund",
            headers=_auth_headers(admin_token),
            json={"reason": "cash not received"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "refunded"
        assert body["credits_deducted"] == 30  # premium package

    def test_refund_wallet_payment(self, client):
        # A succeeded wallet payment is refundable.
        admin_token = _admin_token(client)
        user_id, _ = _seed_user(client, USER_PHONE)
        _seed_payment_row(
            client,
            WalletPayment,
            paymob_payment_id="pm_wallet_ref",
            user_id=user_id,
            wallet_type="fawry",
            package="standard",
            amount_egp=30,
            status="succeeded",
        )
        resp = client.post(
            "/admin/payments/pm_wallet_ref/refund",
            headers=_auth_headers(admin_token),
            json={"reason": "wallet reversal"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["credits_deducted"] == 10


class TestAdjustCredits:
    def test_small_adjustment_no_approval(self, client):
        admin_token = _admin_token(client)
        user_id, _ = _seed_user(client, USER_PHONE)
        resp = client.post(
            f"/admin/users/{user_id}/adjust-credits",
            headers=_auth_headers(admin_token),
            json={"amount": 5, "reason": "goodwill credit"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["new_balance"] == 3 + 5  # free tier starts at 3

    def test_large_adjustment_requires_approval(self, client):
        admin_token = _admin_token(client)
        user_id, _ = _seed_user(client, USER_PHONE)
        resp = client.post(
            f"/admin/users/{user_id}/adjust-credits",
            headers=_auth_headers(admin_token),
            json={"amount": 100, "reason": "large topup"},
        )
        assert resp.status_code == 403

    def test_large_adjustment_same_admin_rejected(self, client):
        admin_token = _admin_token(client)
        user_id, _ = _seed_user(client, USER_PHONE)
        gen = app.dependency_overrides[get_db]()
        db = next(gen)
        try:
            admin = db.query(Admin).filter_by(username="admin1").first()
            admin_id = admin.id
        finally:
            db.close()
        resp = client.post(
            f"/admin/users/{user_id}/adjust-credits",
            headers=_auth_headers(admin_token),
            json={"amount": 100, "reason": "large topup", "approver_id": admin_id},
        )
        assert resp.status_code == 403

    def test_large_adjustment_requires_approver_token(self, client):
        # A large adjustment with an approver_id but NO approver token is
        # rejected: approval must be verified, not merely claimed.
        admin_token = _admin_token(client)
        user_id, _ = _seed_user(client, USER_PHONE)
        resp = client.post(
            f"/admin/users/{user_id}/adjust-credits",
            headers=_auth_headers(admin_token),
            json={"amount": 100, "reason": "large topup", "approver_id": "x"},
        )
        assert resp.status_code == 403

    def test_large_adjustment_with_valid_approver(self, client):
        admin_token = _admin_token(client)
        user_id, _ = _seed_user(client, USER_PHONE)
        # Provision a second admin out-of-band and mint their token.
        gen = app.dependency_overrides[get_db]()
        db = next(gen)
        try:
            second = Admin(username="admin2", password_hash=get_password_hash("pw"))
            db.add(second)
            db.commit()
            second_id = second.id
        finally:
            db.close()
        resp = client.post(
            f"/admin/users/{user_id}/adjust-credits",
            headers={
                **_auth_headers(admin_token),
                "X-Approver-Token": _admin_jwt_for("admin2"),
            },
            json={"amount": 100, "reason": "large topup", "approver_id": second_id},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["new_balance"] == 3 + 100

    def test_large_adjustment_token_does_not_match(self, client):
        # A valid approver token for a DIFFERENT admin than the claimed
        # approver_id must be rejected (no spoofing).
        admin_token = _admin_token(client)
        user_id, _ = _seed_user(client, USER_PHONE)
        gen = app.dependency_overrides[get_db]()
        db = next(gen)
        try:
            second = Admin(username="admin2", password_hash=get_password_hash("pw"))
            db.add(second)
            db.commit()
        finally:
            db.close()
        # Token is for admin2, but approver_id claims a nonexistent admin.
        resp = client.post(
            f"/admin/users/{user_id}/adjust-credits",
            headers={
                **_auth_headers(admin_token),
                "X-Approver-Token": _admin_jwt_for("admin2"),
            },
            json={
                "amount": 100,
                "reason": "large topup",
                "approver_id": "not-a-real-admin",
            },
        )
        assert resp.status_code == 403

    def test_large_adjustment_invalid_approver(self, client):
        admin_token = _admin_token(client)
        user_id, _ = _seed_user(client, USER_PHONE)
        resp = client.post(
            f"/admin/users/{user_id}/adjust-credits",
            headers=_auth_headers(admin_token),
            json={
                "amount": 100,
                "reason": "large topup",
                "approver_id": "not-a-real-admin",
            },
        )
        assert resp.status_code == 403

    def test_adjust_unknown_user_404(self, client):
        admin_token = _admin_token(client)
        resp = client.post(
            "/admin/users/not-a-real-user/adjust-credits",
            headers=_auth_headers(admin_token),
            json={"amount": 5, "reason": "goodwill credit"},
        )
        assert resp.status_code == 404

    def test_adjust_cannot_go_negative(self, client):
        # A manual adjustment must not drive the balance below zero (the
        # free tier starts at 3; removing 4 would be negative).
        admin_token = _admin_token(client)
        user_id, _ = _seed_user(client, USER_PHONE)
        resp = client.post(
            f"/admin/users/{user_id}/adjust-credits",
            headers=_auth_headers(admin_token),
            json={"amount": -4, "reason": "overdraft correction"},
        )
        assert resp.status_code == 400, resp.text

    def test_adjust_credits_logged(self, client):
        admin_token = _admin_token(client)
        user_id, _ = _seed_user(client, USER_PHONE)
        client.post(
            f"/admin/users/{user_id}/adjust-credits",
            headers=_auth_headers(admin_token),
            json={"amount": 5, "reason": "goodwill credit"},
        )
        gen = app.dependency_overrides[get_db]()
        db = next(gen)
        try:
            audit = (
                db.query(PaymentAuditLog)
                .filter_by(action="adjust_credits", target_user_id=user_id)
                .first()
            )
            assert audit is not None
            assert audit.actor_username == "admin1"
        finally:
            db.close()


class TestAuditLog:
    def test_audit_log_returns_entries(self, client):
        admin_token = _admin_token(client)
        user_id, _ = _seed_user(client, USER_PHONE)
        client.post(
            f"/admin/users/{user_id}/adjust-credits",
            headers=_auth_headers(admin_token),
            json={"amount": 5, "reason": "goodwill credit"},
        )
        resp = client.get("/admin/audit-log", headers=_auth_headers(admin_token))
        assert resp.status_code == 200
        rows = resp.json()
        assert any(r["event_type"] == "adjust_credits" for r in rows)

    def test_audit_log_filter_by_event_type(self, client):
        admin_token = _admin_token(client)
        user_id, _ = _seed_user(client, USER_PHONE)
        client.post(
            f"/admin/users/{user_id}/adjust-credits",
            headers=_auth_headers(admin_token),
            json={"amount": 5, "reason": "goodwill credit"},
        )
        resp = client.get(
            "/admin/audit-log",
            headers=_auth_headers(admin_token),
            params={"event_type": "adjust_credits"},
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert all(r["event_type"] == "adjust_credits" for r in rows)
        assert len(rows) >= 1

    def test_audit_log_requires_admin(self, client):
        # No admin token -> 401/403.
        resp = client.get("/admin/audit-log")
        assert resp.status_code in (401, 403)
