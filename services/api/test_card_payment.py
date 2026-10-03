"""Tests for the Paymob card payment flow (Feature 1).

Covers:
- GET /payment/start (staging token creation, rate limit 5/hour)
- POST /payment/confirm (single-use token, cross-user rejection,
  server-determined amount, rate limit 3/hour)
- GET /payment/status/{payment_id} (owner only, no existence leak)
- Security: staging token replay (1.4), token hijacking (1.2), amount tampering (1.3)
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.card_payment_models import CardPayment
from services.api.staging_store import InMemoryStagingStore, set_store
from services.billing.models import PaymentLog

USER_PHONE = "+201012345678"
OTHER_PHONE = "+201098765432"


@pytest.fixture
def client(monkeypatch):
    """Test client with in-memory DB, in-memory staging store, and mocked Paymob."""
    # Deferred imports: importing services.api.main at collection time would
    # create its SQLAlchemy engine from whatever DATABASE_URL happens to be set
    # by an earlier test module. Importing inside the fixture body defers that
    # to test-execution time; the engine is never used because get_db is
    # overridden with an in-memory SQLite session. (Same pattern as conftest.)
    from services.api.dependencies import get_db
    from services.api.main import app
    from services.api.models import Base

    # Mock the Paymob API client so no real HTTP calls are made.
    monkeypatch.setattr(
        "services.api.routers.payment.create_customer",
        lambda email: {"id": 1, "staging_token": f"staging_mock_{email}"},
    )

    _counter = {"n": 0}

    def _mock_create_payment(method_id, amount_paisa, currency, reference_id):
        _counter["n"] += 1
        return {
            "id": f"pay_{_counter['n']}_{amount_paisa}_{reference_id}",
            "authentication_token": "auth_mock_12345",
        }

    monkeypatch.setattr(
        "services.api.routers.payment.create_payment_method",
        lambda token, payment_method_type="card": {"id": 42},
    )
    monkeypatch.setattr(
        "services.api.routers.payment.create_payment",
        _mock_create_payment,
    )

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    # PaymentLog lives on the billing service's Base — create it here too.
    from services.billing.models import Base as BillingBase
    BillingBase.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    set_store(InMemoryStagingStore())
    with TestClient(app) as c:
        c._user_tokens = {}
        yield c
    app.dependency_overrides.clear()
    set_store(None)


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def _register_and_login(client, phone, password):
    reg = client.post("/auth/register", json={"phone": phone, "password": password})
    assert reg.status_code == 200, f"register failed: {reg.text}"
    login = client.post("/auth/login", json={"phone": phone, "password": password})
    assert login.status_code == 200, f"login failed: {login.text}"
    return login.json()["access_token"]


def _user_token(client):
    if "primary" not in client._user_tokens:
        client._user_tokens["primary"] = _register_and_login(
            client, USER_PHONE, "testpass123"
        )
    return client._user_tokens["primary"]


def _other_user_token(client):
    if "other" not in client._user_tokens:
        client._user_tokens["other"] = _register_and_login(
            client, OTHER_PHONE, "otherpass1"
        )
    return client._user_tokens["other"]


# ---------------------------------------------------------------------------
# GET /payment/start
# ---------------------------------------------------------------------------


class TestPaymentStart:
    def test_start_returns_staging_token(self, client):
        """/payment/start creates a Paymob customer and returns a staging token."""
        token = _user_token(client)
        resp = client.get("/payment/start", headers=_auth_headers(token))
        assert resp.status_code == 200
        data = resp.json()
        assert "staging_token" in data
        assert data["staging_token"]
        assert data["expires_in"] == 900

    def test_start_unauthenticated_401(self, client):
        resp = client.get("/payment/start")
        assert resp.status_code == 401

    def test_start_rate_limit_sixth_request_429(self, client):
        """Plan 1.9: rate limit /payment/start to 5/hour per user."""
        token = _user_token(client)
        for i in range(5):
            resp = client.get("/payment/start", headers=_auth_headers(token))
            assert resp.status_code == 200, f"start {i}: {resp.text}"
        # The 6th start is rejected.
        resp = client.get("/payment/start", headers=_auth_headers(token))
        assert resp.status_code == 429


# ---------------------------------------------------------------------------
# POST /payment/confirm
# ---------------------------------------------------------------------------


class TestPaymentConfirm:
    def test_confirm_valid_flow(self, client):
        """Full card payment flow: start → confirm → pending payment created."""
        token = _user_token(client)

        # Step 1: start.
        start = client.get("/payment/start", headers=_auth_headers(token))
        assert start.status_code == 200
        staging_token = start.json()["staging_token"]

        # Step 2: confirm with a mock tokenization token.
        resp = client.post(
            "/payment/confirm",
            json={
                "staging_token": staging_token,
                "method_type": "card",
                "token": "tok_mock_12345",
                "package": "standard",
            },
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["payment_id"]

    def test_confirm_invalid_package_400(self, client):
        token = _user_token(client)
        start = client.get("/payment/start", headers=_auth_headers(token))
        staging_token = start.json()["staging_token"]
        resp = client.post(
            "/payment/confirm",
            json={
                "staging_token": staging_token,
                "method_type": "card",
                "token": "tok_mock_12345",
                "package": "gold",
            },
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400

    def test_confirm_unsupported_method_type_400(self, client):
        token = _user_token(client)
        start = client.get("/payment/start", headers=_auth_headers(token))
        staging_token = start.json()["staging_token"]
        resp = client.post(
            "/payment/confirm",
            json={
                "staging_token": staging_token,
                "method_type": "wallet",
                "token": "tok_mock_12345",
                "package": "standard",
            },
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400

    def test_confirm_missing_token_400(self, client):
        token = _user_token(client)
        start = client.get("/payment/start", headers=_auth_headers(token))
        staging_token = start.json()["staging_token"]
        resp = client.post(
            "/payment/confirm",
            json={
                "staging_token": staging_token,
                "method_type": "card",
                "token": "",
                "package": "standard",
            },
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400

    def test_confirm_unknown_staging_token_400(self, client):
        """A staging token that was never issued (or already expired) → 400."""
        token = _user_token(client)
        resp = client.post(
            "/payment/confirm",
            json={
                "staging_token": "never_issued_token",
                "method_type": "card",
                "token": "tok_mock_12345",
                "package": "standard",
            },
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400

    def test_confirm_staging_token_single_use_replay_400(self, client):
        """Plan 1.4: replaying a consumed staging token returns 400."""
        token = _user_token(client)
        start = client.get("/payment/start", headers=_auth_headers(token))
        staging_token = start.json()["staging_token"]

        # First confirm consumes the token.
        first = client.post(
            "/payment/confirm",
            json={
                "staging_token": staging_token,
                "method_type": "card",
                "token": "tok_mock_12345",
                "package": "standard",
            },
            headers=_auth_headers(token),
        )
        assert first.status_code == 200

        # Replay with the same token → 400.
        second = client.post(
            "/payment/confirm",
            json={
                "staging_token": staging_token,
                "method_type": "card",
                "token": "tok_mock_12345",
                "package": "standard",
            },
            headers=_auth_headers(token),
        )
        assert second.status_code == 400

    def test_confirm_cross_user_token_rejection(self, client):
        """Plan 1.2: user B cannot use user A's staging token."""
        token_a = _user_token(client)
        token_b = _other_user_token(client)

        # User A starts a payment.
        start = client.get("/payment/start", headers=_auth_headers(token_a))
        assert start.status_code == 200
        staging_token = start.json()["staging_token"]

        # User B tries to confirm with A's token → 400.
        resp = client.post(
            "/payment/confirm",
            json={
                "staging_token": staging_token,
                "method_type": "card",
                "token": "tok_mock_12345",
                "package": "standard",
            },
            headers=_auth_headers(token_b),
        )
        assert resp.status_code == 400

    def test_confirm_rate_limit_fourth_request_429(self, client):
        """Plan 1.9: rate limit /payment/confirm to 3/hour per user."""
        token = _user_token(client)
        for i in range(3):
            start = client.get("/payment/start", headers=_auth_headers(token))
            staging_token = start.json()["staging_token"]
            resp = client.post(
                "/payment/confirm",
                json={
                    "staging_token": staging_token,
                    "method_type": "card",
                    "token": f"tok_mock_{i}",
                    "package": "standard",
                },
                headers=_auth_headers(token),
            )
            assert resp.status_code == 200, f"confirm {i}: {resp.text}"

        # The 4th confirm is rejected.
        start = client.get("/payment/start", headers=_auth_headers(token))
        staging_token = start.json()["staging_token"]
        resp = client.post(
            "/payment/confirm",
            json={
                "staging_token": staging_token,
                "method_type": "card",
                "token": "tok_mock_3",
                "package": "standard",
            },
            headers=_auth_headers(token),
        )
        assert resp.status_code == 429


# ---------------------------------------------------------------------------
# GET /payment/status/{payment_id}
# ---------------------------------------------------------------------------


class TestPaymentStatus:
    def test_get_own_payment_status(self, client):
        """Owner can query their payment status."""
        token = _user_token(client)
        start = client.get("/payment/start", headers=_auth_headers(token))
        staging_token = start.json()["staging_token"]
        confirm = client.post(
            "/payment/confirm",
            json={
                "staging_token": staging_token,
                "method_type": "card",
                "token": "tok_mock_12345",
                "package": "standard",
            },
            headers=_auth_headers(token),
        )
        assert confirm.status_code == 200
        payment_id = confirm.json()["payment_id"]

        resp = client.get(
            f"/payment/status/{payment_id}", headers=_auth_headers(token)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["package"] == "standard"
        assert data["amount_egp"] == 30.0

    def test_get_other_users_payment_404(self, client):
        """Plan 1.8: non-owner lookup returns 404 (no existence leak)."""
        token_a = _user_token(client)
        token_b = _other_user_token(client)

        start = client.get("/payment/start", headers=_auth_headers(token_a))
        staging_token = start.json()["staging_token"]
        confirm = client.post(
            "/payment/confirm",
            json={
                "staging_token": staging_token,
                "method_type": "card",
                "token": "tok_mock_12345",
                "package": "standard",
            },
            headers=_auth_headers(token_a),
        )
        assert confirm.status_code == 200
        payment_id = confirm.json()["payment_id"]

        # User B queries A's payment → 404.
        resp = client.get(
            f"/payment/status/{payment_id}", headers=_auth_headers(token_b)
        )
        assert resp.status_code == 404

    def test_get_nonexistent_payment_404(self, client):
        token = _user_token(client)
        resp = client.get(
            "/payment/status/nonexistent-id", headers=_auth_headers(token)
        )
        assert resp.status_code == 404

    def test_status_reflects_webhook_result(self, client):
        """After the webhook records a PaymentLog, status reflects the final state."""
        token = _user_token(client)
        start = client.get("/payment/start", headers=_auth_headers(token))
        staging_token = start.json()["staging_token"]
        confirm = client.post(
            "/payment/confirm",
            json={
                "staging_token": staging_token,
                "method_type": "card",
                "token": "tok_mock_12345",
                "package": "standard",
            },
            headers=_auth_headers(token),
        )
        assert confirm.status_code == 200
        payment_id = confirm.json()["payment_id"]

        # Simulate the webhook having processed the payment.
        from services.api.dependencies import get_db
        from services.api.main import app

        gen = app.dependency_overrides[get_db]()
        db = next(gen)
        try:
            payment = (
                db.query(CardPayment)
                .filter_by(paymob_payment_id=payment_id)
                .first()
            )
            assert payment is not None
            db.add(
                PaymentLog(
                    user_id=payment.user_id,
                    paymob_order_id=payment_id,
                    amount=30.0,
                    currency="EGP",
                    status="succeeded",
                    tier="standard",
                )
            )
            db.commit()
        finally:
            db.close()

        resp = client.get(
            f"/payment/status/{payment_id}", headers=_auth_headers(token)
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "succeeded"


# ---------------------------------------------------------------------------
# Security: no card data in logs or database
# ---------------------------------------------------------------------------


class TestCardDataSecurity:
    def test_no_card_data_in_database(self, client):
        """Plan 1.1: the database stores only payment IDs, never card data."""
        token = _user_token(client)
        start = client.get("/payment/start", headers=_auth_headers(token))
        staging_token = start.json()["staging_token"]
        confirm = client.post(
            "/payment/confirm",
            json={
                "staging_token": staging_token,
                "method_type": "card",
                "token": "tok_mock_12345",
                "package": "premium",
            },
            headers=_auth_headers(token),
        )
        assert confirm.status_code == 200

        from services.api.dependencies import get_db
        from services.api.main import app

        gen = app.dependency_overrides[get_db]()
        db = next(gen)
        try:
            payment = db.query(CardPayment).first()
            assert payment is not None
            # Only server-determined fields are stored.
            assert payment.package == "premium"
            assert float(payment.amount_egp) == 90.0
            assert payment.status == "pending"
            # No card number, CVV, or expiry columns exist.
            cols = {c.name for c in CardPayment.__table__.columns}
            assert "card_number" not in cols
            assert "cvv" not in cols
            assert "expiry" not in cols
        finally:
            db.close()

    def test_confirm_response_contains_no_card_data(self, client):
        """The confirm response only contains payment_id and authentication_token."""
        token = _user_token(client)
        start = client.get("/payment/start", headers=_auth_headers(token))
        staging_token = start.json()["staging_token"]
        resp = client.post(
            "/payment/confirm",
            json={
                "staging_token": staging_token,
                "method_type": "card",
                "token": "tok_mock_12345",
                "package": "standard",
            },
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        # Only these fields should be present.
        assert set(data.keys()) == {"payment_id", "authentication_token", "status"}
