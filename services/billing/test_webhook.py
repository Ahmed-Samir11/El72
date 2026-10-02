"""Tests for Feature 4: Paymob webhook & credit granting (billing service).

Covers the plan's acceptance criteria:
- Valid webhook -> credits granted, payment logged
- Invalid signature -> 401, no side effects
- Duplicate webhook -> 200 "duplicate", no double-grant
- Amount mismatch -> 400, no credits
- Invalid user / reference_id / package -> 400
- Failed/canceled status -> ignored, no credits (but logged)
- All processing logged in the immutable audit log
- Rate limiting active (100/hour -> 429)
"""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import services.billing.main as billing_main
from services.api.admin_models import Admin  # noqa: F401  (registers admins table)
from services.api.manual_payment_models import PaymentAuditLog
from services.api.models import Base, CreditTransaction, User, UserCredit
from services.billing.models import Base as BillingBase
from services.billing.models import PaymentLog

TEST_HMAC_SECRET = "test-webhook-secret"


def _sign(body: bytes) -> str:
    return hmac.new(TEST_HMAC_SECRET.encode(), body, hashlib.sha512).hexdigest()


@pytest.fixture()
def client(monkeypatch):
    """Billing app with a fresh in-memory DB and a known HMAC secret."""
    monkeypatch.setattr(billing_main, "PAYMOB_HMAC_SECRET", TEST_HMAC_SECRET)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    BillingBase.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Let the dialect generate the id (integer on SQLite, UUID on Postgres)
    # and read it back as a string for the reference_id.
    with TestingSessionLocal() as db:
        user = User(
            phone="+201098765432",
            password_hash="x",
            salt="y",
            tier="free",
        )
        db.add(user)
        db.commit()
        user_id = str(user.id)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    billing_main.app.dependency_overrides[billing_main.get_db] = override_get_db
    with TestClient(billing_main.app) as c:
        c._test_user_id = user_id  # type: ignore[attr-defined]
        yield c
    billing_main.app.dependency_overrides.clear()


def _webhook(client, tx: dict, sign: bool = True):
    body = json.dumps({"obj": tx}).encode("utf-8")
    headers = {}
    if sign:
        headers["X-Paymob-Signature"] = _sign(body)
    return client.post("/webhook/paymob", content=body, headers=headers)


def test_get_pricing(client):
    response = client.get("/pricing")
    assert response.status_code == 200
    data = response.json()
    assert data["currency"] == "EGP"
    assert data["packages"]["free"]["credits"] == 3
    assert data["packages"]["standard"]["credits"] == 10
    assert data["packages"]["premium"]["credits"] == 30


class TestWebhookProcessing:
    def _tx(self, client, **overrides):
        tx = {
            "id": "txn_abc123",
            "status": "succeeded",
            "amount": 3000,
            "currency": "EGP",
            "reference_id": f"elhaq-{client._test_user_id}-standard",
        }
        tx.update(overrides)
        return tx

    def test_valid_webhook_grants_credits_and_logs(self, client):
        resp = _webhook(client, self._tx(client))
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "processed"}

        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            log = db.query(PaymentLog).filter_by(paymob_order_id="txn_abc123").one()
            assert log.status == "succeeded"
            assert log.tier == "standard"
            assert float(log.amount) == 30.0

            # Free-tier user is lazily provisioned with 3, then +10 granted.
            credit = db.query(UserCredit).filter_by(user_id=client._test_user_id).one()
            assert credit.balance == 13

            tx_row = (
                db.query(CreditTransaction)
                .filter_by(user_id=client._test_user_id)
                .one()
            )
            assert tx_row.amount == 10
            assert tx_row.reason == "paymob_standard"
        finally:
            db.close()

    def test_invalid_signature_returns_401_no_side_effects(self, client):
        resp = _webhook(client, self._tx(client), sign=False)
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Invalid signature"}

        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            assert db.query(PaymentLog).count() == 0
            assert db.query(UserCredit).count() == 0
            # The failure IS audited (immutable trail).
            audit = db.query(PaymentAuditLog).one()
            assert audit.action == "webhook_signature_failed"
        finally:
            db.close()

    def test_duplicate_webhook_no_double_grant(self, client):
        first = _webhook(client, self._tx(client))
        assert first.status_code == 200
        assert first.json() == {"status": "processed"}

        second = _webhook(client, self._tx(client))
        assert second.status_code == 200
        assert second.json() == {"status": "duplicate"}

        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            # Exactly one payment log row and one grant.
            assert db.query(PaymentLog).count() == 1
            credit = db.query(UserCredit).filter_by(user_id=client._test_user_id).one()
            assert credit.balance == 13
            assert (
                db.query(CreditTransaction)
                .filter_by(user_id=client._test_user_id)
                .count()
                == 1
            )
        finally:
            db.close()

    def test_amount_mismatch_returns_400_no_credits(self, client):
        resp = _webhook(client, self._tx(client, amount=3001))
        assert resp.status_code == 400
        assert resp.json() == {"detail": "Amount mismatch"}

        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            assert db.query(PaymentLog).count() == 0
            assert db.query(UserCredit).count() == 0
            audit = db.query(PaymentAuditLog).one()
            assert audit.action == "amount_mismatch"
        finally:
            db.close()

    def test_unknown_user_returns_400(self, client):
        resp = _webhook(
            client,
            self._tx(
                client,
                reference_id="elhaq-11111111-2222-3333-4444-555555555555-standard",
            ),
        )
        assert resp.status_code == 400
        assert resp.json() == {"detail": "Unknown user"}

    def test_malformed_reference_id_returns_400(self, client):
        for bad_ref in (
            "nope",
            "elhaq-123",
            f"elhaq-{client._test_user_id}",
            "other-11111111-2222-3333-4444-555555555555-standard",
            "elhaq-not-a-uuid-standard",
        ):
            resp = _webhook(client, self._tx(client, reference_id=bad_ref))
            assert resp.status_code == 400, (bad_ref, resp.text)

    def test_invalid_package_returns_400(self, client):
        resp = _webhook(
            client,
            self._tx(client, reference_id=f"elhaq-{client._test_user_id}-enterprise"),
        )
        assert resp.status_code == 400
        assert resp.json() == {"detail": "Invalid package"}

    def test_failed_status_ignored_no_credits_but_logged(self, client):
        resp = _webhook(client, self._tx(client, status="failed"))
        assert resp.status_code == 200
        assert resp.json() == {"status": "ignored"}

        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            log = db.query(PaymentLog).filter_by(paymob_order_id="txn_abc123").one()
            assert log.status == "failed"
            assert db.query(UserCredit).count() == 0
            audit = db.query(PaymentAuditLog).one()
            assert audit.action == "webhook_received"
        finally:
            db.close()

    def test_success_webhook_is_audited(self, client):
        _webhook(client, self._tx(client))
        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            audit = db.query(PaymentAuditLog).one()
            assert audit.action == "webhook_received"
            assert audit.target_user_id == client._test_user_id
            assert audit.order_ref == "txn_abc123"
        finally:
            db.close()


class TestWebhookRateLimit:
    # (rate-limiter state is reset per test by the autouse fixture in
    # services/billing/conftest.py)

    def test_returns_429_after_limit(self, client):
        # /webhook/paymob is limited to 100/hour per IP. Failed signatures
        # count too (the limiter wraps the whole endpoint).
        responses = [
            _webhook(
                client,
                {
                    "id": f"txn_{i}",
                    "status": "succeeded",
                    "amount": 3000,
                    "currency": "EGP",
                    "reference_id": f"elhaq-{client._test_user_id}-standard",
                },
                sign=False,
            )
            for i in range(101)
        ]
        assert all(r.status_code == 401 for r in responses[:100])
        assert responses[100].status_code == 429
