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

    def test_cross_user_rejection_does_not_burn_owner_token(self, client):
        """A cross-user hijack attempt must NOT consume the owner's token.

        After user B is rejected for using A's staging token, user A must
        still be able to confirm with that same token (the CRITICAL review
        finding: the old code popped the token before checking ownership).
        """
        token_a = _user_token(client)
        token_b = _other_user_token(client)

        start = client.get("/payment/start", headers=_auth_headers(token_a))
        assert start.status_code == 200
        staging_token = start.json()["staging_token"]

        # User B's hijack attempt is rejected.
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

        # User A can STILL confirm with the same token — it was not consumed.
        owner = client.post(
            "/payment/confirm",
            json={
                "staging_token": staging_token,
                "method_type": "card",
                "token": "tok_mock_12345",
                "package": "standard",
            },
            headers=_auth_headers(token_a),
        )
        assert owner.status_code == 200
        assert owner.json()["status"] == "pending"

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


class TestRedisFailure:
    def test_start_redis_down_503(self, client, monkeypatch):
        """A Redis outage on /payment/start returns a controlled 503, not 500."""
        import redis as _redis

        from services.api.staging_store import get_staging_store

        store = get_staging_store()

        def _raise_incr(*a, **k):
            raise _redis.ConnectionError("down")

        monkeypatch.setattr(store, "incr", _raise_incr)
        token = _user_token(client)
        resp = client.get("/payment/start", headers=_auth_headers(token))
        assert resp.status_code == 503

    def test_confirm_redis_down_503(self, client, monkeypatch):
        """A Redis outage on /payment/confirm returns a controlled 503, not 500."""
        import redis as _redis

        from services.api.staging_store import get_staging_store

        store = get_staging_store()

        def _raise_get(*a, **k):
            raise _redis.ConnectionError("down")

        monkeypatch.setattr(store, "get", _raise_get)
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
        assert resp.status_code == 503


class TestPremiumAmount:
    def test_premium_confirm_uses_server_amount(self, client):
        """Premium confirm stores the server-determined 90.0 EGP amount."""
        token = _user_token(client)
        start = client.get("/payment/start", headers=_auth_headers(token))
        staging_token = start.json()["staging_token"]
        resp = client.post(
            "/payment/confirm",
            json={
                "staging_token": staging_token,
                "method_type": "card",
                "token": "tok_mock_12345",
                "package": "premium",
            },
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200

        from services.api.dependencies import get_db
        from services.api.main import app

        gen = app.dependency_overrides[get_db]()
        db = next(gen)
        try:
            payment = (
                db.query(CardPayment).filter_by(paymob_payment_id=resp.json()["payment_id"]).first()
            )
            assert payment is not None
            assert float(payment.amount_egp) == 90.0
            assert payment.package == "premium"
        finally:
            db.close()


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


# ---------------------------------------------------------------------------
# Finding #5: staging token expiry, audit events, provider error mapping
# ---------------------------------------------------------------------------


class TestStagingTokenExpiry:
    def test_expired_token_rejected_400(self, client):
        """A staging token that has expired (TTL elapsed) is rejected."""
        token = _user_token(client)
        start = client.get("/payment/start", headers=_auth_headers(token))
        assert start.status_code == 200
        staging_token = start.json()["staging_token"]

        # Simulate expiry by deleting the token from the store.
        from services.api.staging_store import get_staging_store

        store = get_staging_store()
        store._tokens.pop(staging_token, None)

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
        assert resp.status_code == 400


class TestAuditEvents:
    def test_staging_rejected_audited(self, client):
        """An unknown/expired staging token produces a staging_rejected audit row."""
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

        from services.api.dependencies import get_db
        from services.api.main import app

        gen = app.dependency_overrides[get_db]()
        db = next(gen)
        try:
            # The audit log is a separate table; check via raw query.
            from sqlalchemy import text

            rows = db.execute(
                text(
                    "SELECT action, detail FROM payment_audit_log "
                    "WHERE action = 'staging_rejected'"
                )
            ).fetchall()
            assert len(rows) >= 1
            assert "reason=unknown_or_expired_token" in rows[0][1]
        finally:
            db.close()

    def test_card_payment_created_audited(self, client):
        """A successful confirm produces a card_payment_created audit row."""
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

        from services.api.dependencies import get_db
        from services.api.main import app

        gen = app.dependency_overrides[get_db]()
        db = next(gen)
        try:
            from sqlalchemy import text

            rows = db.execute(
                text(
                    "SELECT action, order_ref, detail FROM payment_audit_log "
                    "WHERE action = 'card_payment_created'"
                )
            ).fetchall()
            assert len(rows) >= 1
            assert rows[0][1] == payment_id
            assert "package=standard" in rows[0][2]
        finally:
            db.close()


class TestProviderErrorMapping:
    def test_paymob_503_maps_to_503(self, client, monkeypatch):
        """PaymobApiError with 503 status → HTTP 503."""
        from services.common.paymob_client import PaymobApiError

        def _raise_503(email):
            raise PaymobApiError(503, "service unavailable")

        monkeypatch.setattr(
            "services.api.routers.payment.create_customer", _raise_503
        )
        token = _user_token(client)
        resp = client.get("/payment/start", headers=_auth_headers(token))
        assert resp.status_code == 503

    def test_paymob_non_503_maps_to_502(self, client, monkeypatch):
        """PaymobApiError with non-503 status → HTTP 502."""
        from services.common.paymob_client import PaymobApiError

        def _raise_400(email):
            raise PaymobApiError(400, "bad request")

        monkeypatch.setattr(
            "services.api.routers.payment.create_customer", _raise_400
        )
        token = _user_token(client)
        resp = client.get("/payment/start", headers=_auth_headers(token))
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# Finding #7: unauthenticated confirm/status → 401
# ---------------------------------------------------------------------------


class TestUnauthenticatedAccess:
    def test_confirm_unauthenticated_401(self, client):
        """POST /payment/confirm without auth → 401."""
        resp = client.post(
            "/payment/confirm",
            json={
                "staging_token": "some_token",
                "method_type": "card",
                "token": "tok_mock_12345",
                "package": "standard",
            },
        )
        assert resp.status_code == 401

    def test_status_unauthenticated_401(self, client):
        """GET /payment/status/{id} without auth → 401."""
        resp = client.get("/payment/status/some-id")
        assert resp.status_code == 401
