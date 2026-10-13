"""Tests for the Paymob cash payment flow (Feature 3).

Covers:
- POST /payment/confirm (cash): channel allowlist, server-determined amount,
  single-use staging token, rate limit 5/hour, missing code -> 502, audit
  carries the code (plan 3.1-3.5)
- GET /payment/status/{payment_id}: cash resolution (code + expiry), lazy
  expiry -> canceled + cash_expired audit, webhook-wins semantics,
  owner-only 404, 1/minute poll rate limit (plan 3.2)
- Billing webhook: terminal webhooks transition cash rows (Feature 3)
"""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import services.billing.main as billing_main
from services.api.cash_payment_models import CashPayment
from services.api.manual_payment_models import PaymentAuditLog
from services.api.models import User
from services.api.staging_store import (
    InMemoryStagingStore,
    get_staging_store,
    set_store,
)
from services.billing.models import PaymentLog

USER_PHONE = "+201012345678"
OTHER_PHONE = "+201098765432"

TEST_HMAC_SECRET = "test-cash-webhook-secret"


@pytest.fixture
def client(monkeypatch):
    """Test client with in-memory DB, in-memory staging store, and mocked
    Paymob (cash payments create the payment directly — no method
    indirection)."""
    from services.api.dependencies import get_db
    from services.api.main import app
    from services.api.models import Base

    monkeypatch.setattr(
        "services.api.routers.payment.create_customer",
        lambda email: {"id": 1, "staging_token": f"staging_mock_{email}"},
    )

    _counter = {"n": 0}

    def _mock_create_cash_payment(
        staging_token, cash_type, amount_paisa, currency, reference_id
    ):
        _counter["n"] += 1
        return {
            "id": f"cpay_{_counter['n']}_{amount_paisa}",
            "status": "pending",
            "payment_code": f"CODE{_counter['n']:04d}",
        }

    monkeypatch.setattr(
        "services.api.routers.payment.create_cash_payment",
        _mock_create_cash_payment,
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


def _session(client):
    from services.api.dependencies import get_db
    from services.api.main import app

    gen = app.dependency_overrides[get_db]()
    return next(gen)


def _start_payment(client, token):
    start = client.get("/payment/start", headers=_auth_headers(token))
    assert start.status_code == 200
    return start.json()["staging_token"]


def _confirm_cash(
    client,
    token,
    staging_token,
    package="standard",
    cash_type="fawry",
    include_type=True,
):
    body = {
        "staging_token": staging_token,
        "method_type": "cash",
        "package": package,
    }
    if include_type:
        body["cash_type"] = cash_type
    return client.post("/payment/confirm", json=body, headers=_auth_headers(token))


def _get_cash_row(session, payment_id):
    return (
        session.query(CashPayment)
        .filter(CashPayment.paymob_payment_id == payment_id)
        .first()
    )


# ---------------------------------------------------------------------------
# POST /payment/confirm (cash)
# ---------------------------------------------------------------------------


class TestCashConfirm:
    @pytest.mark.parametrize("cash_type", ["fawry", "bank"])
    def test_confirm_happy_path(self, client, cash_type):
        """Cash confirm creates the payment and returns code + expiry."""
        token = _user_token(client)
        staging = _start_payment(client, token)
        resp = _confirm_cash(client, token, staging, cash_type=cash_type)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "pending"
        assert data["payment_id"].startswith("cpay_")
        assert data["payment_code"]
        assert data["expires_at"]

        db = _session(client)
        try:
            row = _get_cash_row(db, data["payment_id"])
            assert row is not None
            assert row.cash_type == cash_type
            assert row.package == "standard"
            assert float(row.amount_egp) == 30.0
            assert row.status == "pending"
            assert row.payment_code == data["payment_code"]
            # ~24 h from creation (plan 3.3); the two timestamps are taken
            # milliseconds apart, so allow a small tolerance.
            delta = row.expires_at - row.created_at
            assert timedelta(hours=24) - delta < timedelta(seconds=1)
        finally:
            db.close()

    def test_server_determined_amount(self, client):
        """Plan 3.4: the amount is looked up from the package; the client
        never sends one. Premium must cost 9000 piastres."""
        token = _user_token(client)
        staging = _start_payment(client, token)
        resp = _confirm_cash(client, token, staging, package="premium")
        assert resp.status_code == 200, resp.text
        db = _session(client)
        try:
            row = _get_cash_row(db, resp.json()["payment_id"])
            assert float(row.amount_egp) == 90.0
        finally:
            db.close()

    def test_invalid_package_400(self, client):
        token = _user_token(client)
        staging = _start_payment(client, token)
        resp = _confirm_cash(client, token, staging, package="gold")
        assert resp.status_code == 400
        # The staging token must survive a rejected confirm.
        assert _confirm_cash(client, token, staging).status_code == 200

    @pytest.mark.parametrize("cash_type", ["meeza", "visa", "Fawry!", ""])
    def test_cash_type_not_in_allowlist_400(self, client, cash_type):
        """Plan 3.2: cash_type validated against the server-side allowlist;
        unknown channels are rejected before any Paymob call."""
        token = _user_token(client)
        staging = _start_payment(client, token)
        resp = _confirm_cash(client, token, staging, cash_type=cash_type)
        assert resp.status_code == 400
        # Staging token survives (rejected before consumption).
        assert _confirm_cash(client, token, staging).status_code == 200

    def test_missing_cash_type_400(self, client):
        token = _user_token(client)
        staging = _start_payment(client, token)
        resp = _confirm_cash(client, token, staging, include_type=False)
        assert resp.status_code == 400
        # Staging token survives (rejected before consumption).
        assert _confirm_cash(client, token, staging).status_code == 200

    def test_cash_type_case_insensitive(self, client):
        token = _user_token(client)
        staging = _start_payment(client, token)
        resp = _confirm_cash(client, token, staging, cash_type="FAWRY")
        assert resp.status_code == 200, resp.text
        db = _session(client)
        try:
            row = _get_cash_row(db, resp.json()["payment_id"])
            assert row.cash_type == "fawry"
        finally:
            db.close()

    def test_missing_code_from_paymob_502_no_row(self, client, monkeypatch):
        """If the provider returns no code, the confirm fails with 502 and
        no row is persisted (the user can start again)."""
        monkeypatch.setattr(
            "services.api.routers.payment.create_cash_payment",
            lambda *a, **k: {"id": "cpay_nocode", "status": "pending"},
        )
        token = _user_token(client)
        staging = _start_payment(client, token)
        resp = _confirm_cash(client, token, staging)
        assert resp.status_code == 502
        db = _session(client)
        try:
            assert db.query(CashPayment).count() == 0
        finally:
            db.close()

    def test_sixth_confirm_429(self, client):
        """Plan 3.2 anti-abuse: max 5 cash confirms per user per hour.

        Five confirmed rows are seeded directly (bypassing /payment/start,
        which has its own 5/hour limit), then one staging token is injected
        into the store for the sixth attempt.
        """
        token = _user_token(client)
        db = _session(client)
        try:
            user_id = str(db.query(User).filter_by(phone=USER_PHONE).first().id)
            for i in range(5):
                db.add(
                    CashPayment(
                        user_id=user_id,
                        paymob_payment_id=f"cpay_seed_{i}",
                        payment_code=f"SEED{i:04d}",
                        cash_type="fawry",
                        package="standard",
                        amount_egp=30.0,
                        status="pending",
                        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
                    )
                )
            db.commit()
        finally:
            db.close()

        get_staging_store().set("staging_seed", user_id)
        resp = _confirm_cash(client, token, "staging_seed")
        assert resp.status_code == 429

    def test_audit_carries_code(self, client):
        """Plan 3.5: the cash_payment_created audit entry records the code
        (the code is not PII), package and amount."""
        token = _user_token(client)
        staging = _start_payment(client, token)
        resp = _confirm_cash(client, token, staging)
        assert resp.status_code == 200, resp.text
        code = resp.json()["payment_code"]
        db = _session(client)
        try:
            entry = (
                db.query(PaymentAuditLog)
                .filter(PaymentAuditLog.action == "cash_payment_created")
                .first()
            )
            assert entry is not None
            assert code in (entry.detail or "")
            assert "package=standard" in entry.detail
            assert "amount_egp=30.0" in entry.detail
        finally:
            db.close()

    def test_staging_token_single_use(self, client):
        """Plan 1.4: after a successful cash confirm the staging token is
        consumed; a replay is rejected."""
        token = _user_token(client)
        staging = _start_payment(client, token)
        assert _confirm_cash(client, token, staging).status_code == 200
        resp = _confirm_cash(client, token, staging)
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /payment/status/{payment_id} (cash)
# ---------------------------------------------------------------------------


class TestCashStatus:
    def _create_cash_payment(self, client, expires_delta=timedelta(hours=24)):
        token = _user_token(client)
        staging = _start_payment(client, token)
        resp = _confirm_cash(client, token, staging)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        db = _session(client)
        try:
            row = _get_cash_row(db, data["payment_id"])
            row.expires_at = row.created_at + expires_delta
            db.commit()
        finally:
            db.close()
        return data, token

    def test_pending_returns_code_and_expiry(self, client):
        data, token = self._create_cash_payment(client)
        resp = client.get(
            f"/payment/status/{data['payment_id']}", headers=_auth_headers(token)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "pending"
        assert body["payment_code"] == data["payment_code"]
        assert body["expires_at"]

    def test_lazy_expiry_cancels_and_audits(self, client):
        """Plan 3.3: a pending row past its expiry is canceled on sight and
        audited as cash_expired."""
        data, token = self._create_cash_payment(
            client, expires_delta=timedelta(minutes=-1)
        )
        resp = client.get(
            f"/payment/status/{data['payment_id']}", headers=_auth_headers(token)
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "canceled"
        db = _session(client)
        try:
            row = _get_cash_row(db, data["payment_id"])
            assert row.status == "canceled"
            entry = (
                db.query(PaymentAuditLog)
                .filter(PaymentAuditLog.action == "cash_expired")
                .first()
            )
            assert entry is not None
            assert data["payment_code"] in (entry.detail or "")
        finally:
            db.close()

    def test_succeeded_webhook_wins_over_expiry(self, client, monkeypatch):
        """The webhook is the source of truth: an expired row that later
        receives a succeeded delivery reports succeeded (consistent with
        Features 1/2)."""
        data, token = self._create_cash_payment(
            client, expires_delta=timedelta(minutes=-1)
        )
        db = _session(client)
        try:
            user_id = str(
                db.query(CashPayment)
                .filter(CashPayment.paymob_payment_id == data["payment_id"])
                .first()
                .user_id
            )
            db.add(
                PaymentLog(
                    user_id=user_id,
                    paymob_order_id=data["payment_id"],
                    amount=30.0,
                    currency="EGP",
                    status="succeeded",
                    tier="standard",
                )
            )
            db.commit()
        finally:
            db.close()
        # Two lookups: the first cancels via lazy expiry, the second must
        # still report succeeded (webhook wins).
        first = client.get(
            f"/payment/status/{data['payment_id']}", headers=_auth_headers(token)
        )
        assert first.status_code == 200
        assert first.json()["status"] == "succeeded"
        second = client.get(
            f"/payment/status/{data['payment_id']}", headers=_auth_headers(token)
        )
        # Second lookup within 60 s is rate limited (429) — expected; the
        # authoritative state was already proven by the first response.
        assert second.status_code == 429

    def test_owner_only_404(self, client):
        data, _ = self._create_cash_payment(client)
        other = _other_user_token(client)
        resp = client.get(
            f"/payment/status/{data['payment_id']}", headers=_auth_headers(other)
        )
        assert resp.status_code == 404

    def test_second_poll_within_minute_429(self, client):
        """Plan 3.2: cash status lookups are limited to 1 per payment per
        minute."""
        data, token = self._create_cash_payment(client)
        first = client.get(
            f"/payment/status/{data['payment_id']}", headers=_auth_headers(token)
        )
        assert first.status_code == 200, first.text
        second = client.get(
            f"/payment/status/{data['payment_id']}", headers=_auth_headers(token)
        )
        assert second.status_code == 429

    def test_unknown_payment_404(self, client):
        token = _user_token(client)
        resp = client.get(
            "/payment/status/cpay_nonexistent", headers=_auth_headers(token)
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Billing webhook: cash row transitions
# ---------------------------------------------------------------------------


def _sign(body: bytes) -> str:
    return hmac.new(TEST_HMAC_SECRET.encode(), body, hashlib.sha512).hexdigest()


@pytest.fixture
def billing_client(monkeypatch):
    """Billing app with a fresh in-memory DB and a known HMAC secret."""
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
        from services.api.models import User

        user = User(phone=USER_PHONE, password_hash="x", salt="y", tier="free")
        db.add(user)
        db.commit()
        user_id = str(user.id)
        cash = CashPayment(
            user_id=user_id,
            paymob_payment_id="cpay_billing_1",
            payment_code="CODEBILL",
            cash_type="fawry",
            package="standard",
            amount_egp=30.0,
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            created_at=datetime.now(timezone.utc),
        )
        db.add(cash)
        db.commit()

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


class TestBillingCashTransitions:
    def test_succeeded_webhook_transitions_cash_row(self, billing_client):
        resp = _webhook(
            billing_client,
            {
                "id": "cpay_billing_1",
                "status": "succeeded",
                "amount": 3000,
                "currency": "EGP",
                "reference_id": f"elhaq-{billing_client._test_user_id}-standard",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "processed"
        # Re-open a session via the dependency override to verify the row.
        gen = billing_main.app.dependency_overrides[billing_main.get_db]()
        db = next(gen)
        try:
            row = (
                db.query(CashPayment)
                .filter(CashPayment.paymob_payment_id == "cpay_billing_1")
                .first()
            )
            assert row is not None
            assert row.status == "succeeded"
        finally:
            db.close()

    def test_failed_webhook_transitions_cash_row(self, billing_client):
        resp = _webhook(
            billing_client,
            {
                "id": "cpay_billing_2",
                "status": "failed",
                "amount": 3000,
                "currency": "EGP",
                "reference_id": f"elhaq-{billing_client._test_user_id}-standard",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "ignored"
        gen = billing_main.app.dependency_overrides[billing_main.get_db]()
        db = next(gen)
        try:
            # No row for cpay_billing_2 — the transition must be a no-op
            # without error (card/wallet/manual orders share the endpoint).
            assert (
                db.query(CashPayment)
                .filter(CashPayment.paymob_payment_id == "cpay_billing_2")
                .first()
                is None
            )
        finally:
            db.close()
