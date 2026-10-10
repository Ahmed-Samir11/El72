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
from services.api.card_payment_models import CardPayment
from services.api.manual_payment_models import PaymentAuditLog
from services.api.models import Base, CreditTransaction, User, UserCredit
from services.api.wallet_payment_models import (
    WalletPayment,  # noqa: F401  (registers wallet_payments table)
)
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
            # The duplicate delivery IS audited.
            dup_audit = (
                db.query(PaymentAuditLog).filter_by(action="webhook_duplicate").one()
            )
            assert dup_audit.order_ref == "txn_abc123"
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

        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            # The rejection IS audited.
            audit = db.query(PaymentAuditLog).one()
            assert audit.action == "validation_rejected"
        finally:
            db.close()

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

        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            # Every rejection is audited (immutable trail).
            assert (
                db.query(PaymentAuditLog)
                .filter_by(action="validation_rejected")
                .count()
                == 5
            )
        finally:
            db.close()

    def test_invalid_package_returns_400(self, client):
        resp = _webhook(
            client,
            self._tx(client, reference_id=f"elhaq-{client._test_user_id}-enterprise"),
        )
        assert resp.status_code == 400
        assert resp.json() == {"detail": "Invalid package"}

        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            audit = db.query(PaymentAuditLog).one()
            assert audit.action == "validation_rejected"
        finally:
            db.close()

    def test_invalid_currency_returns_400(self, client):
        resp = _webhook(client, self._tx(client, currency="USD"))
        assert resp.status_code == 400
        assert resp.json() == {"detail": "Invalid currency"}

        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            audit = db.query(PaymentAuditLog).one()
            assert audit.action == "validation_rejected"
        finally:
            db.close()

    def test_unknown_status_returns_400(self, client):
        resp = _webhook(client, self._tx(client, status="processing"))
        assert resp.status_code == 400
        assert resp.json() == {"detail": "Invalid status"}

        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            audit = db.query(PaymentAuditLog).one()
            assert audit.action == "validation_rejected"
        finally:
            db.close()

    def test_malformed_json_audited(self, client):
        # A signed but unparseable body is rejected AND audited.
        resp = client.post(
            "/webhook/paymob",
            content=b"this is not json",
            headers={"X-Paymob-Signature": _sign(b"this is not json")},
        )
        assert resp.status_code == 400

        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            audit = db.query(PaymentAuditLog).one()
            assert audit.action == "validation_rejected"
        finally:
            db.close()

    def test_missing_fields_audited(self, client):
        # No amount field -> rejected AND audited.
        payload = {
            "id": "txn_no_amount",
            "status": "succeeded",
            "currency": "EGP",
            "reference_id": f"elhaq-{client._test_user_id}-standard",
        }
        resp = _webhook(client, payload)
        assert resp.status_code == 400

        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            audit = db.query(PaymentAuditLog).one()
            assert audit.action == "validation_rejected"
        finally:
            db.close()

    def test_failed_status_audited_no_credits_and_no_payment_row(self, client):
        """A terminal failure is audited but must NOT occupy the unique
        paymob_order_id, so a later succeeded delivery stays processable."""
        resp = _webhook(client, self._tx(client, status="failed"))
        assert resp.status_code == 200
        assert resp.json() == {"status": "ignored"}

        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            assert db.query(PaymentLog).count() == 0
            assert db.query(UserCredit).count() == 0
            assert (
                db.query(PaymentAuditLog).filter_by(action="webhook_received").count()
                == 1
            )

            # A succeeded delivery of the SAME order now processes cleanly.
            ok = _webhook(client, self._tx(client, status="succeeded"))
            assert ok.json() == {"status": "processed"}
            credit = db.query(UserCredit).filter_by(user_id=client._test_user_id).one()
            assert credit.balance == 13
            assert (
                db.query(PaymentAuditLog).filter_by(action="webhook_received").count()
                == 2
            )
        finally:
            db.close()

    def test_success_webhook_is_audited(self, client):
        _webhook(client, self._tx(client))
        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            audit = db.query(PaymentAuditLog).one()
            assert audit.action == "webhook_received"
            assert audit.target_user_id == int(client._test_user_id)
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


class TestWalletPaymentStatusUpdate:
    """Feature 2: the webhook terminal state transitions the wallet_payments
    row (only rows still in the OTP/in-flight states)."""

    def _seed_wallet_row(self, client, order_id: str, status: str = "pending_otp"):
        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            row = WalletPayment(
                user_id=client._test_user_id,
                paymob_payment_id=order_id,
                wallet_type="VODAFONE_CASH",
                package="standard",
                amount_egp=30.0,
                status=status,
            )
            db.add(row)
            db.commit()
        finally:
            db.close()

    def test_succeeded_webhook_updates_pending_otp_row(self, client):
        self._seed_wallet_row(client, "txn_abc123", "pending_otp")
        resp = _webhook(
            client,
            {
                "id": "txn_abc123",
                "status": "succeeded",
                "amount": 3000,
                "currency": "EGP",
                "reference_id": f"elhaq-{client._test_user_id}-standard",
            },
        )
        assert resp.status_code == 200, resp.text
        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            row = (
                db.query(WalletPayment).filter_by(paymob_payment_id="txn_abc123").one()
            )
            assert row.status == "succeeded"
        finally:
            db.close()

    def test_processing_row_updated_to_failed(self, client):
        self._seed_wallet_row(client, "txn_abc123", "processing")
        resp = _webhook(
            client,
            {
                "id": "txn_abc123",
                "status": "failed",
                "amount": 3000,
                "currency": "EGP",
                "reference_id": f"elhaq-{client._test_user_id}-standard",
            },
        )
        assert resp.status_code == 200, resp.text
        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            row = (
                db.query(WalletPayment).filter_by(paymob_payment_id="txn_abc123").one()
            )
            assert row.status == "failed"
        finally:
            db.close()

    def test_canceled_row_transitions_on_late_webhook(self, client):
        """A row canceled locally (3-attempt budget / OTP expiry) is
        superseded by the webhook — the webhook is the source of truth for
        the payment's fate. If Paymob says the order succeeded, the user was
        in fact charged and credited, so the row must show it too."""
        self._seed_wallet_row(client, "txn_abc123", "canceled")
        resp = _webhook(
            client,
            {
                "id": "txn_abc123",
                "status": "succeeded",
                "amount": 3000,
                "currency": "EGP",
                "reference_id": f"elhaq-{client._test_user_id}-standard",
            },
        )
        assert resp.status_code == 200, resp.text
        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            row = (
                db.query(WalletPayment).filter_by(paymob_payment_id="txn_abc123").one()
            )
            assert row.status == "succeeded"
        finally:
            db.close()

    def test_failed_webhook_updates_processing_row(self, client):
        """Plan Feature 1: 'Failed payment -> user sees error' — a failed
        terminal webhook must be visible on the payment row (and therefore
        on /payment/status)."""
        self._seed_wallet_row(client, "txn_abc123", "processing")
        resp = _webhook(
            client,
            {
                "id": "txn_abc123",
                "status": "canceled",
                "amount": 3000,
                "currency": "EGP",
                "reference_id": f"elhaq-{client._test_user_id}-standard",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "ignored"}
        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            row = (
                db.query(WalletPayment).filter_by(paymob_payment_id="txn_abc123").one()
            )
            assert row.status == "canceled"
            # And no PaymentLog row (a later succeeded delivery stays
            # processable).
            assert db.query(PaymentLog).count() == 0
        finally:
            db.close()


class TestCardPaymentStatusUpdate:
    """Regression: the card_payments row transition must actually persist —
    the webhook session is closed (not committed) by the get_db teardown, so
    the raw UPDATE needs an explicit commit (Feature 1 finding)."""

    def _seed_card_row(self, client, order_id: str, status: str = "pending"):
        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            row = CardPayment(
                user_id=client._test_user_id,
                paymob_payment_id=order_id,
                package="standard",
                amount_egp=30.0,
                status=status,
            )
            db.add(row)
            db.commit()
        finally:
            db.close()

    def test_succeeded_webhook_updates_card_row_persisted(self, client):
        self._seed_card_row(client, "txn_abc123", "pending")
        resp = _webhook(
            client,
            {
                "id": "txn_abc123",
                "status": "succeeded",
                "amount": 3000,
                "currency": "EGP",
                "reference_id": f"elhaq-{client._test_user_id}-standard",
            },
        )
        assert resp.status_code == 200, resp.text
        # A FRESH session sees the transition (it would not if the UPDATE
        # were rolled back on session close).
        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            row = db.query(CardPayment).filter_by(paymob_payment_id="txn_abc123").one()
            assert row.status == "succeeded"
        finally:
            db.close()

    def test_failed_webhook_updates_card_row(self, client):
        self._seed_card_row(client, "txn_abc123", "pending")
        resp = _webhook(
            client,
            {
                "id": "txn_abc123",
                "status": "failed",
                "amount": 3000,
                "currency": "EGP",
                "reference_id": f"elhaq-{client._test_user_id}-standard",
            },
        )
        assert resp.status_code == 200, resp.text
        db = next(client.app.dependency_overrides[billing_main.get_db]())
        try:
            row = db.query(CardPayment).filter_by(paymob_payment_id="txn_abc123").one()
            assert row.status == "failed"
        finally:
            db.close()


class TestSignatureFailureAlert:
    """Feature 5 wiring (deferred to Feature 2): 5+ failed webhook signatures
    within 1 minute raise a security alert (logged)."""

    def test_fifth_failed_signature_alerts(self, client, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="services.billing.main"):
            for i in range(4):
                resp = _webhook(
                    client,
                    {
                        "id": f"txn_bad_{i}",
                        "status": "succeeded",
                        "amount": 3000,
                        "currency": "EGP",
                        "reference_id": f"elhaq-{client._test_user_id}-standard",
                    },
                    sign=False,
                )
                assert resp.status_code == 401
            assert not any("Security alert" in r.message for r in caplog.records)
            # The 5th failure within the window crosses the threshold.
            resp = _webhook(
                client,
                {
                    "id": "txn_bad_5",
                    "status": "succeeded",
                    "amount": 3000,
                    "currency": "EGP",
                    "reference_id": f"elhaq-{client._test_user_id}-standard",
                },
                sign=False,
            )
            assert resp.status_code == 401
        assert any("Security alert" in r.message for r in caplog.records)
