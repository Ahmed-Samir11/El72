"""Tests for Feature 7: recurring subscriptions (Paymob subscriptions).

Covers:
- POST /subscription/create (API service) — creation, credits, dedupe.
- POST /subscription/cancel (API service) — owner-only cancellation.
- GET  /subscription/status (API service) — active subscription status.
- POST /webhook/paymob/subscription-renewal (billing service) — renewal
  success, failure/dunning, auto-cancel after 3 failures, idempotency.
"""

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.models import User
from services.api.staging_store import InMemoryStagingStore, set_store
from services.api.subscription_models import Subscription, SubscriptionRenewal

TEST_HMAC_SECRET = "test-hmac-secret-subscription"
USER_PHONE = "+201012345678"
OTHER_PHONE = "+201098765432"
PASSWORD = "testpass123"
OTHER_PASSWORD = "otherpass1"


def _sign(body: bytes) -> str:
    return hmac.new(TEST_HMAC_SECRET.encode(), body, hashlib.sha512).hexdigest()


@pytest.fixture
def client(monkeypatch):
    """API app with in-memory DB, in-memory staging store, mocked Paymob."""
    # Deferred imports (same pattern as the card payment tests): importing
    # services.api.main at collection time would create its SQLAlchemy
    # engine from whatever DATABASE_URL an earlier test module set.
    from services.api.dependencies import get_db
    from services.api.main import app
    from services.api.models import Base
    from services.billing.models import Base as BillingBase

    # Mock the Paymob API client (subscription + the /payment/start customer
    # used to mint staging tokens).
    monkeypatch.setattr(
        "services.api.routers.payment.create_customer",
        lambda email: {"id": 1, "staging_token": f"staging_mock_{email}"},
    )
    monkeypatch.setattr(
        "services.api.routers.subscription.create_payment_method",
        lambda token, payment_method_type="card": {"id": "pm_sub_1"},
    )
    monkeypatch.setattr(
        "services.api.routers.subscription.create_subscription",
        lambda method_id, amount_paisa, currency, reference_id, interval="month": {
            "id": f"sub_{reference_id}",
            "authentication_token": "auth_sub_12345",
        },
    )
    monkeypatch.setattr(
        "services.api.routers.subscription.cancel_subscription",
        lambda subscription_id: {"id": subscription_id, "status": "canceled"},
    )

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
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
            client, USER_PHONE, PASSWORD
        )
    return client._user_tokens["primary"]


def _staging_token_for(client, token):
    """Start a card payment to mint a staging token bound to the user."""
    resp = client.get("/payment/start", headers=_auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["staging_token"]


# ---------------------------------------------------------------------------
# POST /subscription/create
# ---------------------------------------------------------------------------


class TestSubscriptionCreate:
    def test_create_returns_subscription_id(self, client):
        token = _user_token(client)
        staging = _staging_token_for(client, token)
        resp = client.post(
            "/subscription/create",
            headers=_auth_headers(token),
            json={
                "staging_token": staging,
                "token": "tok_sub_12345",
                "package": "standard",
                "interval": "month",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "subscription_id" in data
        assert data["subscription_id"]
        assert "next_charge" in data

    def test_create_does_not_grant_credits(self, client):
        # Credits are granted only when the first charge is confirmed by the
        # renewal webhook, not at creation (review finding: premature
        # credit granting). Creation must not change the balance.
        token = _user_token(client)
        before = client.get("/credits/balance", headers=_auth_headers(token)).json()[
            "balance"
        ]
        staging = _staging_token_for(client, token)
        resp = client.post(
            "/subscription/create",
            headers=_auth_headers(token),
            json={
                "staging_token": staging,
                "token": "tok_sub_12345",
                "package": "standard",
                "interval": "month",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["subscription_id"]
        assert data["next_charge"]
        after = client.get("/credits/balance", headers=_auth_headers(token)).json()[
            "balance"
        ]
        assert after == before

    def test_create_invalid_package_400(self, client):
        token = _user_token(client)
        staging = _staging_token_for(client, token)
        resp = client.post(
            "/subscription/create",
            headers=_auth_headers(token),
            json={
                "staging_token": staging,
                "token": "tok_sub_12345",
                "package": "gold",
                "interval": "month",
            },
        )
        assert resp.status_code == 422, resp.text

    def test_create_duplicate_active_409(self, client):
        token = _user_token(client)
        staging1 = _staging_token_for(client, token)
        r1 = client.post(
            "/subscription/create",
            headers=_auth_headers(token),
            json={
                "staging_token": staging1,
                "token": "tok_sub_1",
                "package": "standard",
                "interval": "month",
            },
        )
        assert r1.status_code == 200, r1.text
        # A second active subscription for the same user is rejected.
        staging2 = _staging_token_for(client, token)
        r2 = client.post(
            "/subscription/create",
            headers=_auth_headers(token),
            json={
                "staging_token": staging2,
                "token": "tok_sub_2",
                "package": "premium",
                "interval": "month",
            },
        )
        assert r2.status_code == 409, r2.text

    def test_create_unauthenticated_401(self, client):
        resp = client.post(
            "/subscription/create",
            json={
                "staging_token": "x",
                "token": "y",
                "package": "standard",
                "interval": "month",
            },
        )
        assert resp.status_code == 401

    def test_create_missing_token_400(self, client):
        token = _user_token(client)
        staging = _staging_token_for(client, token)
        resp = client.post(
            "/subscription/create",
            headers=_auth_headers(token),
            json={
                "staging_token": staging,
                "token": "",
                "package": "standard",
                "interval": "month",
            },
        )
        assert resp.status_code == 400, resp.text

    def test_create_provider_failure_502(self, client, monkeypatch):
        # If the Paymob API fails, create returns a controlled 502.
        import services.api.routers.subscription as sub_router

        def _raise(method_id, amount_paisa, currency, reference_id, interval="month"):
            from services.common.paymob_client import PaymobApiError

            raise PaymobApiError(502, "paymob api unreachable")

        monkeypatch.setattr(sub_router, "create_subscription", _raise)
        token = _user_token(client)
        staging = _staging_token_for(client, token)
        resp = client.post(
            "/subscription/create",
            headers=_auth_headers(token),
            json={
                "staging_token": staging,
                "token": "tok_sub_12345",
                "package": "standard",
                "interval": "month",
            },
        )
        assert resp.status_code == 502, resp.text

    def test_cancel_provider_failure_502(self, client, monkeypatch):
        # If the Paymob cancel API fails, cancel returns a controlled 502.
        import services.api.routers.subscription as sub_router

        def _raise(subscription_id):
            from services.common.paymob_client import PaymobApiError

            raise PaymobApiError(502, "paymob api unreachable")

        monkeypatch.setattr(sub_router, "cancel_subscription", _raise)
        token = _user_token(client)
        staging = _staging_token_for(client, token)
        create = client.post(
            "/subscription/create",
            headers=_auth_headers(token),
            json={
                "staging_token": staging,
                "token": "tok_sub_12345",
                "package": "standard",
                "interval": "month",
            },
        )
        assert create.status_code == 200, create.text
        sub_id = create.json()["subscription_id"]
        resp = client.post(
            "/subscription/cancel",
            headers=_auth_headers(token),
            json={"subscription_id": sub_id},
        )
        assert resp.status_code == 502, resp.text


# ---------------------------------------------------------------------------
# GET /subscription/status
# ---------------------------------------------------------------------------


class TestSubscriptionStatus:
    def test_status_inactive_when_none(self, client):
        token = _user_token(client)
        resp = client.get("/subscription/status", headers=_auth_headers(token))
        assert resp.status_code == 200
        assert resp.json()["active"] is False

    def test_status_active_after_create(self, client):
        token = _user_token(client)
        staging = _staging_token_for(client, token)
        client.post(
            "/subscription/create",
            headers=_auth_headers(token),
            json={
                "staging_token": staging,
                "token": "tok_sub_12345",
                "package": "premium",
                "interval": "month",
            },
        )
        resp = client.get("/subscription/status", headers=_auth_headers(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert data["package"] == "premium"
        assert data["next_charge"] is not None


# ---------------------------------------------------------------------------
# POST /subscription/cancel
# ---------------------------------------------------------------------------


class TestSubscriptionCancel:
    def _create(self, client, token):
        staging = _staging_token_for(client, token)
        resp = client.post(
            "/subscription/create",
            headers=_auth_headers(token),
            json={
                "staging_token": staging,
                "token": "tok_sub_12345",
                "package": "standard",
                "interval": "month",
            },
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["subscription_id"]

    def test_cancel_owner(self, client):
        token = _user_token(client)
        sub_id = self._create(client, token)
        resp = client.post(
            "/subscription/cancel",
            headers=_auth_headers(token),
            json={"subscription_id": sub_id},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "canceled"
        # After cancel, the status is inactive.
        status = client.get("/subscription/status", headers=_auth_headers(token)).json()
        assert status["active"] is False

    def test_cancel_unknown_404(self, client):
        token = _user_token(client)
        resp = client.post(
            "/subscription/cancel",
            headers=_auth_headers(token),
            json={"subscription_id": "does-not-exist"},
        )
        assert resp.status_code == 404

    def test_cancel_other_users_subscription_404(self, client):
        token = _user_token(client)
        sub_id = self._create(client, token)
        # A different user cannot cancel it.
        reg = client.post(
            "/auth/register", json={"phone": OTHER_PHONE, "password": OTHER_PASSWORD}
        )
        assert reg.status_code == 200, reg.text
        login = client.post(
            "/auth/login", json={"phone": OTHER_PHONE, "password": OTHER_PASSWORD}
        )
        other_token = login.json()["access_token"]
        resp = client.post(
            "/subscription/cancel",
            headers=_auth_headers(other_token),
            json={"subscription_id": sub_id},
        )
        assert resp.status_code == 404

    def test_cancel_inactive_400(self, client):
        token = _user_token(client)
        sub_id = self._create(client, token)
        client.post(
            "/subscription/cancel",
            headers=_auth_headers(token),
            json={"subscription_id": sub_id},
        )
        # Canceling an already-canceled subscription is 400.
        resp = client.post(
            "/subscription/cancel",
            headers=_auth_headers(token),
            json={"subscription_id": sub_id},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Billing webhook: subscription renewal
# ---------------------------------------------------------------------------


@pytest.fixture
def billing_client(monkeypatch):
    """Billing app with a fresh in-memory DB, known HMAC secret, and a
    seeded active subscription."""
    import services.billing.main as billing_main

    monkeypatch.setattr(billing_main, "PAYMOB_HMAC_SECRET", TEST_HMAC_SECRET)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from services.api.models import Base
    from services.billing.models import Base as BillingBase

    Base.metadata.create_all(engine)
    BillingBase.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    with TestingSessionLocal() as db:
        user = User(phone=USER_PHONE, password_hash="x", salt="y", tier="free")
        db.add(user)
        db.commit()
        user_id = str(user.id)
        sub = Subscription(
            id=str(uuid.uuid4()),
            user_id=user_id,
            paymob_subscription_id="paymob_sub_1",
            card_payment_method_id="pm_sub_1",
            package="standard",
            amount_egp=30.0,
            interval="month",
            status="active",
            failed_renewals=0,
            next_charge=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(sub)
        db.commit()
        sub_id = sub.id

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    billing_main.app.dependency_overrides[billing_main.get_db] = override_get_db
    with TestClient(billing_main.app) as c:
        c._test_user_id = user_id  # type: ignore[attr-defined]
        c._test_sub_id = sub_id  # type: ignore[attr-defined]
        c._test_engine = engine  # type: ignore[attr-defined]
        c._test_session = TestingSessionLocal  # type: ignore[attr-defined]
        yield c
    billing_main.app.dependency_overrides.clear()


def _renewal_webhook(client, renewal_id, status, sign=True):
    body = json.dumps(
        {
            "obj": {
                "id": renewal_id,
                "paymob_subscription_id": "paymob_sub_1",
                "status": status,
            }
        }
    ).encode("utf-8")
    headers = {}
    if sign:
        headers["X-Paymob-Signature"] = _sign(body)
    return client.post(
        "/webhook/paymob/subscription-renewal", content=body, headers=headers
    )


class TestRenewalWebhook:
    def test_invalid_signature_401(self, billing_client):
        resp = _renewal_webhook(billing_client, "renewal_1", "succeeded", sign=False)
        assert resp.status_code == 401

    def test_succeeded_grants_credits_and_advances(self, billing_client):
        from services.api.credits import get_balance

        # Capture the balance before the renewal so we can assert the
        # exact credit delta (review finding: weak credit assertion).
        with billing_client._test_session() as db:
            user = db.get(User, billing_client._test_user_id)
            balance_before = get_balance(db, user)
        resp = _renewal_webhook(billing_client, "renewal_1", "succeeded")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "succeeded"
        # The renewal row is recorded, credits granted, and next_charge
        # advanced a month (the dunning counter resets).
        with billing_client._test_session() as db:
            sub = db.get(Subscription, billing_client._test_sub_id)
            user = db.get(User, billing_client._test_user_id)
            renewal = (
                db.query(SubscriptionRenewal)
                .filter_by(paymob_renewal_id="renewal_1")
                .first()
            )
            balance_after = get_balance(db, user)
        assert renewal is not None
        assert renewal.status == "succeeded"
        assert sub.failed_renewals == 0
        # standard package grants exactly 10 credits on renewal.
        assert balance_after - balance_before == 10
        # next_charge advanced ~30 days from now. (SQLite returns naive
        # datetimes, so compare against a naive UTC datetime.)
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        assert sub.next_charge > now_naive

    def test_failed_increments_dunning(self, billing_client):
        resp = _renewal_webhook(billing_client, "renewal_f1", "failed")
        assert resp.status_code == 200, resp.text
        with billing_client._test_session() as db:
            sub = db.get(Subscription, billing_client._test_sub_id)
        assert sub.failed_renewals == 1
        assert sub.status == "active"

    def test_auto_cancel_after_three_failures(self, billing_client):
        for i in range(3):
            resp = _renewal_webhook(billing_client, f"renewal_f{i}", "failed")
            assert resp.status_code == 200, resp.text
        with billing_client._test_session() as db:
            sub = db.get(Subscription, billing_client._test_sub_id)
        assert sub.status == "failed"
        assert sub.failed_renewals == 3
        assert sub.canceled_at is not None

    def test_idempotent_duplicate(self, billing_client):
        first = _renewal_webhook(billing_client, "renewal_dup", "succeeded")
        assert first.status_code == 200
        second = _renewal_webhook(billing_client, "renewal_dup", "succeeded")
        assert second.status_code == 200
        assert second.json()["status"] == "duplicate"
        # Only one renewal row.
        with billing_client._test_session() as db:
            count = (
                db.query(SubscriptionRenewal)
                .filter_by(paymob_renewal_id="renewal_dup")
                .count()
            )
        assert count == 1

    def test_unknown_subscription_404(self, billing_client):
        body = json.dumps(
            {
                "obj": {
                    "id": "renewal_x",
                    "paymob_subscription_id": "does-not-exist",
                    "status": "succeeded",
                }
            }
        ).encode("utf-8")
        resp = billing_client.post(
            "/webhook/paymob/subscription-renewal",
            content=body,
            headers={"X-Paymob-Signature": _sign(body)},
        )
        assert resp.status_code == 404

    def test_renewal_for_canceled_subscription_noop(self, billing_client):
        # Cancel the subscription first (via the DB).
        with billing_client._test_session() as db:
            sub = db.get(Subscription, billing_client._test_sub_id)
            sub.status = "canceled"
            db.commit()
        resp = _renewal_webhook(billing_client, "renewal_inactive", "succeeded")
        assert resp.status_code == 200
        assert resp.json()["status"] == "inactive"
