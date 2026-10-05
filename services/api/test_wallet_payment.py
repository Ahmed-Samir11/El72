"""Tests for the Paymob wallet payment flow (Feature 2).

Covers:
- POST /payment/confirm (wallet): type/number validation, server-determined
  amount, single-use staging token, cross-user rejection, rate limit 5/hour
- POST /payment/confirm-otp: success paths, 3-attempt budget, 60 s expiry,
  malformed OTP, provider outage, flood guard, owner-only access
- GET /payment/status/{payment_id}: wallet resolution + webhook terminal state
- Security: wallet number and OTP value never stored or audited (2.6/2.8)
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.models import User
from services.api.staging_store import InMemoryStagingStore, set_store
from services.api.wallet_payment_models import WalletPayment
from services.billing.models import PaymentLog

USER_PHONE = "+201012345678"
OTHER_PHONE = "+201098765432"
WALLET_NUMBER = "01012345678"
# An OTP value that must NEVER appear in audit details or DB rows.
OTP_VALUE = "492817"


@pytest.fixture
def client(monkeypatch):
    """Test client with in-memory DB, in-memory staging store, and mocked Paymob."""
    from services.api.dependencies import get_db
    from services.api.main import app
    from services.api.models import Base

    # Mock the Paymob API client so no real HTTP calls are made. The
    # create_payment mock embeds the amount in the returned id so tests can
    # assert the server-determined amount (plan 2.4).
    monkeypatch.setattr(
        "services.api.routers.payment.create_customer",
        lambda email: {"id": 1, "staging_token": f"staging_mock_{email}"},
    )

    _counter = {"n": 0}

    def _mock_create_payment(method_id, amount_paisa, currency, reference_id):
        _counter["n"] += 1
        return {
            "id": f"wpay_{_counter['n']}_{amount_paisa}_{reference_id}",
            "status": "pending_otp",
        }

    def _mock_create_wallet_method(staging_token, wallet_type, wallet_number):
        # Echo the inputs back so tests can assert what crossed the wire.
        return {"id": f"method_{wallet_type}"}

    def _mock_confirm_otp(payment_id, otp):
        # Default: verification fails; individual tests re-mock as needed.
        return {"id": payment_id, "status": "failed"}

    monkeypatch.setattr(
        "services.api.routers.payment.create_payment", _mock_create_payment
    )
    monkeypatch.setattr(
        "services.api.routers.payment.create_wallet_payment_method",
        _mock_create_wallet_method,
    )
    monkeypatch.setattr(
        "services.api.routers.payment.confirm_wallet_otp", _mock_confirm_otp
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


def _start_wallet_payment(client, token, package="standard"):
    """Run /payment/start and return the staging token."""
    start = client.get("/payment/start", headers=_auth_headers(token))
    assert start.status_code == 200
    return start.json()["staging_token"]


def _confirm_wallet(
    client,
    token,
    staging_token,
    package="standard",
    wallet_type="VODAFONE_CASH",
    wallet_number=WALLET_NUMBER,
):
    return client.post(
        "/payment/confirm",
        json={
            "staging_token": staging_token,
            "method_type": "wallet",
            "wallet_type": wallet_type,
            "wallet_number": wallet_number,
            "package": package,
        },
        headers=_auth_headers(token),
    )


def _get_wallet_row(session, payment_id):
    return (
        session.query(WalletPayment)
        .filter(WalletPayment.paymob_payment_id == payment_id)
        .first()
    )


# ---------------------------------------------------------------------------
# POST /payment/confirm (wallet)
# ---------------------------------------------------------------------------


class TestWalletConfirm:
    def test_confirm_happy_path(self, client):
        """Wallet confirm creates the payment and returns pending_otp."""
        token = _user_token(client)
        staging = _start_wallet_payment(client, token)
        resp = _confirm_wallet(client, token, staging)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "pending_otp"
        assert data["payment_id"].startswith("wpay_")

        db = _session(client)
        try:
            row = _get_wallet_row(db, data["payment_id"])
            assert row is not None
            assert row.wallet_type == "VODAFONE_CASH"
            assert row.package == "standard"
            assert float(row.amount_egp) == 30.0
            assert row.status == "pending_otp"
            assert row.otp_attempts == 0
            assert row.otp_expires_at is not None
        finally:
            db.close()

    def test_all_wallet_numbers_formats_accepted(self, client):
        """010/011/012/015 prefixes are valid Egyptian mobile numbers."""
        token = _user_token(client)
        for number in ["01012345678", "01112345678", "01212345678", "01512345678"]:
            staging = _start_wallet_payment(client, token)
            resp = _confirm_wallet(client, token, staging, wallet_number=number)
            assert resp.status_code == 200, f"number {number}: {resp.text}"

    def test_invalid_package_400(self, client):
        token = _user_token(client)
        staging = _start_wallet_payment(client, token)
        resp = _confirm_wallet(client, token, staging, package="gold")
        assert resp.status_code == 400
        # The staging token must survive a rejected confirm.
        staging2 = _confirm_wallet(client, token, staging)
        assert staging2.status_code == 200

    def test_unsupported_method_type_400(self, client):
        token = _user_token(client)
        staging = _start_wallet_payment(client, token)
        resp = client.post(
            "/payment/confirm",
            json={
                "staging_token": staging,
                "method_type": "bank_transfer",
                "package": "standard",
            },
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400

    def test_missing_wallet_type_400(self, client):
        token = _user_token(client)
        staging = _start_wallet_payment(client, token)
        resp = client.post(
            "/payment/confirm",
            json={
                "staging_token": staging,
                "method_type": "wallet",
                "wallet_number": WALLET_NUMBER,
                "package": "standard",
            },
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400

    def test_missing_wallet_number_400(self, client):
        token = _user_token(client)
        staging = _start_wallet_payment(client, token)
        resp = client.post(
            "/payment/confirm",
            json={
                "staging_token": staging,
                "method_type": "wallet",
                "wallet_type": "VODAFONE_CASH",
                "package": "standard",
            },
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize(
        "wallet_type",
        [
            "MEEza",
            "VISA",
            "vodafone",
            "",
        ],
    )
    def test_wallet_type_not_in_allowlist_400(self, client, wallet_type):
        """Plan 2.7: wallet_type validated against the server-side allowlist;
        unknown types are rejected before any Paymob call."""
        token = _user_token(client)
        staging = _start_wallet_payment(client, token)
        resp = _confirm_wallet(client, token, staging, wallet_type=wallet_type)
        assert resp.status_code == 400
        # Staging token survives (rejected before consumption).
        assert _confirm_wallet(client, token, staging).status_code == 200

    def test_wallet_type_case_insensitive(self, client):
        """The plan's API tokens are matched case-insensitively; the row is
        stored in canonical upper-case."""
        token = _user_token(client)
        staging = _start_wallet_payment(client, token)
        resp = _confirm_wallet(client, token, staging, wallet_type="vodafone_cash")
        assert resp.status_code == 200, resp.text
        db = _session(client)
        try:
            row = _get_wallet_row(db, resp.json()["payment_id"])
            assert row.wallet_type == "VODAFONE_CASH"
        finally:
            db.close()

    @pytest.mark.parametrize(
        "number",
        [
            "01312345678",  # 013 prefix not allowed
            "01412345678",  # 014 prefix not allowed
            "0101234567",  # too short (10 digits)
            "010123456789",  # too long (12 digits)
            "1012345678",  # missing leading 0
            "+201012345678",  # international form not accepted
            "0101234567a",  # non-digit
        ],
    )
    def test_invalid_wallet_number_rejected_fast(self, client, number):
        """Plan 2.2: format validation happens BEFORE any Paymob call."""
        token = _user_token(client)
        staging = _start_wallet_payment(client, token)
        resp = _confirm_wallet(client, token, staging, wallet_number=number)
        assert resp.status_code == 400
        # Staging token survives (rejected before consumption).
        assert _confirm_wallet(client, token, staging).status_code == 200

    def test_amount_server_determined(self, client):
        """Plan 2.4: the amount comes from the package, never the client. The
        mocked create_payment embeds the piastre amount in the payment id."""
        token = _user_token(client)
        staging = _start_wallet_payment(client, token)
        resp = _confirm_wallet(client, token, staging, package="premium")
        assert resp.status_code == 200
        assert "9000" in resp.json()["payment_id"]  # 90.00 EGP in piastres

        staging = _start_wallet_payment(client, token)
        resp = _confirm_wallet(client, token, staging, package="standard")
        assert resp.status_code == 200
        assert "3000" in resp.json()["payment_id"]  # 30.00 EGP in piastres

    def test_paymob_processing_status_honored(self, client, monkeypatch):
        """If Paymob skips the OTP challenge, the row is 'processing' with no
        OTP expiry clock."""
        monkeypatch.setattr(
            "services.api.routers.payment.create_payment",
            lambda method_id, amount, currency, ref: {
                "id": "wpay_processing_1",
                "status": "processing",
            },
        )
        token = _user_token(client)
        staging = _start_wallet_payment(client, token)
        resp = _confirm_wallet(client, token, staging)
        assert resp.status_code == 200
        assert resp.json()["status"] == "processing"
        db = _session(client)
        try:
            row = _get_wallet_row(db, "wpay_processing_1")
            assert row.status == "processing"
            assert row.otp_expires_at is None
        finally:
            db.close()

    def test_staging_replay_rejected(self, client):
        """Plan 2.5: the staging token is single-use — replay returns 400."""
        token = _user_token(client)
        staging = _start_wallet_payment(client, token)
        first = _confirm_wallet(client, token, staging)
        assert first.status_code == 200
        second = _confirm_wallet(client, token, staging)
        assert second.status_code == 400
        assert "staging" in second.json()["detail"].lower()

    def test_cross_user_staging_hijack_rejected_and_not_consumed(self, client):
        """Plan 2.5/1.2: a token bound to another user is rejected, and the
        legitimate owner's token is NOT burned by the attempt."""
        token_a = _user_token(client)
        token_b = _other_user_token(client)
        staging = _start_wallet_payment(client, token_a)

        # User B tries to use A's token → 400, token survives.
        resp = _confirm_wallet(client, token_b, staging)
        assert resp.status_code == 400

        # A can still use their own token.
        assert _confirm_wallet(client, token_a, staging).status_code == 200

    def test_unknown_staging_token_400_and_audited(self, client):
        token = _user_token(client)
        resp = _confirm_wallet(client, token, "staging_mock_never_issued")
        assert resp.status_code == 400
        db = _session(client)
        try:
            from services.api.manual_payment_models import PaymentAuditLog

            event = (
                db.query(PaymentAuditLog)
                .filter(PaymentAuditLog.action == "staging_rejected")
                .first()
            )
            assert event is not None
        finally:
            db.close()

    def test_rate_limit_sixth_confirm_429(self, client):
        """Plan 2.2: max 5 wallet confirms per user per hour."""
        token = _user_token(client)
        # Seed 5 confirmed wallet payments from the last hour directly in
        # the DB (avoiding the separate /payment/start rate limit, which is
        # covered by the card-flow tests).
        db = _session(client)
        try:
            user = db.query(User).filter(User.phone == USER_PHONE).first()
            for i in range(5):
                db.add(
                    WalletPayment(
                        user_id=user.id,
                        paymob_payment_id=f"seed_{i}",
                        wallet_type="VODAFONE_CASH",
                        package="standard",
                        amount_egp=30.0,
                        status="pending_otp",
                    )
                )
            db.commit()
        finally:
            db.close()

        staging = _start_wallet_payment(client, token)
        resp = _confirm_wallet(client, token, staging)
        assert resp.status_code == 429
        # The staging token must survive the rate-limited rejection (not
        # consumed).
        from services.api.staging_store import get_staging_store

        assert get_staging_store().get(staging) is not None

    def test_paymob_failure_creates_no_row(self, client, monkeypatch):
        """A Paymob outage at confirm time creates no payment row and no audit
        event, and maps to a 502."""
        from services.common.paymob_client import PaymobApiError

        def _boom(method_id, amount, currency, ref):
            raise PaymobApiError(502, "paymob api unreachable")

        monkeypatch.setattr("services.api.routers.payment.create_payment", _boom)
        token = _user_token(client)
        staging = _start_wallet_payment(client, token)
        resp = _confirm_wallet(client, token, staging)
        assert resp.status_code == 502
        db = _session(client)
        try:
            assert db.query(WalletPayment).count() == 0
            from services.api.manual_payment_models import PaymentAuditLog

            assert (
                db.query(PaymentAuditLog)
                .filter(PaymentAuditLog.action == "wallet_payment_created")
                .count()
                == 0
            )
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Security: wallet number and OTP never stored / audited
# ---------------------------------------------------------------------------


class TestWalletDataSecurity:
    def test_wallet_number_never_stored(self, client):
        """Plan 2.8: the ledger row keeps the wallet TYPE, never the number."""
        token = _user_token(client)
        staging = _start_wallet_payment(client, token)
        resp = _confirm_wallet(client, token, staging)
        assert resp.status_code == 200
        db = _session(client)
        try:
            row = _get_wallet_row(db, resp.json()["payment_id"])
            assert WALLET_NUMBER not in repr(row)
            # The table has no column for the number at all.
            column_names = [c.name for c in WalletPayment.__table__.columns]
            assert not any("number" in n or "phone" in n for n in column_names)
        finally:
            db.close()

    def test_wallet_payment_created_audit_has_type_not_number(self, client):
        """Plan 2.8: the audit event carries user_id, wallet_type, amount,
        status — but not the wallet number."""
        token = _user_token(client)
        staging = _start_wallet_payment(client, token)
        resp = _confirm_wallet(client, token, staging)
        assert resp.status_code == 200
        db = _session(client)
        try:
            from services.api.manual_payment_models import PaymentAuditLog

            event = (
                db.query(PaymentAuditLog)
                .filter(PaymentAuditLog.action == "wallet_payment_created")
                .first()
            )
            assert event is not None
            assert "VODAFONE_CASH" in (event.detail or "")
            assert WALLET_NUMBER not in (event.detail or "")
            assert event.order_ref == resp.json()["payment_id"]
        finally:
            db.close()

    def test_otp_never_in_audit_or_db(self, client, monkeypatch):
        """Plan 2.6: the OTP value must never reach the audit log or any DB
        row — only outcomes."""
        monkeypatch.setattr(
            "services.api.routers.payment.confirm_wallet_otp",
            lambda payment_id, otp: {"id": payment_id, "status": "failed"},
        )
        token = _user_token(client)
        staging = _start_wallet_payment(client, token)
        resp = _confirm_wallet(client, token, staging)
        payment_id = resp.json()["payment_id"]

        otp_resp = client.post(
            "/payment/confirm-otp",
            json={"payment_id": payment_id, "otp": OTP_VALUE},
            headers=_auth_headers(token),
        )
        assert otp_resp.status_code == 200
        assert otp_resp.json()["status"] == "failed"

        db = _session(client)
        try:
            from services.api.manual_payment_models import PaymentAuditLog

            for event in db.query(PaymentAuditLog).all():
                assert OTP_VALUE not in (event.detail or "")
            row = _get_wallet_row(db, payment_id)
            assert OTP_VALUE not in repr(row)
        finally:
            db.close()


# ---------------------------------------------------------------------------
# POST /payment/confirm-otp
# ---------------------------------------------------------------------------


class TestOtpConfirm:
    def _make_pending_payment(self, client, token, monkeypatch=None):
        """Create a wallet payment in pending_otp state; return the payment id."""
        staging = _start_wallet_payment(client, token)
        resp = _confirm_wallet(client, token, staging)
        assert resp.status_code == 200, resp.text
        return resp.json()["payment_id"]

    def test_otp_success_processing(self, client, monkeypatch):
        monkeypatch.setattr(
            "services.api.routers.payment.confirm_wallet_otp",
            lambda payment_id, otp: {"id": payment_id, "status": "processing"},
        )
        token = _user_token(client)
        payment_id = self._make_pending_payment(client, token)
        resp = client.post(
            "/payment/confirm-otp",
            json={"payment_id": payment_id, "otp": OTP_VALUE},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "processing"
        db = _session(client)
        try:
            assert _get_wallet_row(db, payment_id).status == "processing"
        finally:
            db.close()

    def test_otp_success_succeeded(self, client, monkeypatch):
        monkeypatch.setattr(
            "services.api.routers.payment.confirm_wallet_otp",
            lambda payment_id, otp: {"id": payment_id, "status": "succeeded"},
        )
        token = _user_token(client)
        payment_id = self._make_pending_payment(client, token)
        resp = client.post(
            "/payment/confirm-otp",
            json={"payment_id": payment_id, "otp": OTP_VALUE},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "succeeded"

    def test_otp_failed_decrements_attempts(self, client, monkeypatch):
        """The default mock returns status=failed: the attempt is consumed,
        the payment stays pending_otp, attempts_remaining is reported."""
        token = _user_token(client)
        payment_id = self._make_pending_payment(client, token)
        resp = client.post(
            "/payment/confirm-otp",
            json={"payment_id": payment_id, "otp": OTP_VALUE},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert data["attempts_remaining"] == 2
        db = _session(client)
        try:
            row = _get_wallet_row(db, payment_id)
            assert row.otp_attempts == 1
            assert row.status == "pending_otp"
        finally:
            db.close()

    def test_three_failed_otp_cancels_payment(self, client, monkeypatch):
        """Plan 2.1: after 3 failures the payment is canceled; further
        attempts are rejected."""
        token = _user_token(client)
        payment_id = self._make_pending_payment(client, token)
        for i in range(3):
            resp = client.post(
                "/payment/confirm-otp",
                json={"payment_id": payment_id, "otp": str(100000 + i)},
                headers=_auth_headers(token),
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "failed"
        db = _session(client)
        try:
            assert _get_wallet_row(db, payment_id).status == "canceled"
        finally:
            db.close()
        # A 4th attempt is rejected outright.
        resp = client.post(
            "/payment/confirm-otp",
            json={"payment_id": payment_id, "otp": "999999"},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400

    def test_expired_otp_cancels_payment_and_audits(self, client, monkeypatch):
        """Plan 2.1: the OTP expires 60 s after the payment was created; an
        expired challenge cancels the payment and is audited as
        token_expired."""
        token = _user_token(client)
        payment_id = self._make_pending_payment(client, token)
        db = _session(client)
        try:
            row = _get_wallet_row(db, payment_id)
            row.otp_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        finally:
            db.close()

        resp = client.post(
            "/payment/confirm-otp",
            json={"payment_id": payment_id, "otp": OTP_VALUE},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()
        db = _session(client)
        try:
            assert _get_wallet_row(db, payment_id).status == "canceled"
            from services.api.manual_payment_models import PaymentAuditLog

            event = (
                db.query(PaymentAuditLog)
                .filter(
                    PaymentAuditLog.action == "token_expired",
                    PaymentAuditLog.order_ref == payment_id,
                )
                .first()
            )
            assert event is not None
        finally:
            db.close()

    @pytest.mark.parametrize("bad_otp", ["123456789", "12ab", "abcd", "12 34", ""])
    def test_malformed_otp_rejected_without_attempt(self, client, monkeypatch, bad_otp):
        """A malformed OTP (not 4-8 digits) is rejected with 400 WITHOUT
        consuming an attempt — it would not reach Paymob anyway."""
        calls = []
        monkeypatch.setattr(
            "services.api.routers.payment.confirm_wallet_otp",
            lambda payment_id, otp: calls.append(otp) or {"status": "failed"},
        )
        token = _user_token(client)
        payment_id = self._make_pending_payment(client, token)
        resp = client.post(
            "/payment/confirm-otp",
            json={"payment_id": payment_id, "otp": bad_otp},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400
        assert calls == []
        db = _session(client)
        try:
            assert _get_wallet_row(db, payment_id).otp_attempts == 0
        finally:
            db.close()

    def test_provider_outage_does_not_consume_attempt(self, client, monkeypatch):
        """A Paymob outage (502) during OTP verification has an UNKNOWN
        outcome — the user's attempt budget must be preserved."""
        from services.common.paymob_client import PaymobApiError

        def _boom(payment_id, otp):
            raise PaymobApiError(502, "paymob api unreachable")

        monkeypatch.setattr(
            "services.api.routers.payment.confirm_wallet_otp",
            _boom,
        )
        token = _user_token(client)
        payment_id = self._make_pending_payment(client, token)
        resp = client.post(
            "/payment/confirm-otp",
            json={"payment_id": payment_id, "otp": OTP_VALUE},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 502
        db = _session(client)
        try:
            row = _get_wallet_row(db, payment_id)
            assert row.otp_attempts == 0
            assert row.status == "pending_otp"
        finally:
            db.close()
        # The same OTP can be retried after the outage (re-mock to succeed).
        monkeypatch.setattr(
            "services.api.routers.payment.confirm_wallet_otp",
            lambda payment_id, otp: {"id": payment_id, "status": "processing"},
        )
        resp = client.post(
            "/payment/confirm-otp",
            json={"payment_id": payment_id, "otp": OTP_VALUE},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "processing"

    def test_nonexistent_payment_404(self, client):
        token = _user_token(client)
        resp = client.post(
            "/payment/confirm-otp",
            json={"payment_id": "does-not-exist", "otp": OTP_VALUE},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 404

    def test_other_users_payment_404(self, client):
        """Owner-only: user B cannot submit an OTP for user A's payment."""
        token_a = _user_token(client)
        token_b = _other_user_token(client)
        payment_id = self._make_pending_payment(client, token_a)
        resp = client.post(
            "/payment/confirm-otp",
            json={"payment_id": payment_id, "otp": OTP_VALUE},
            headers=_auth_headers(token_b),
        )
        assert resp.status_code == 404

    def test_terminal_states_reject_otp(self, client, monkeypatch):
        """OTP submission is rejected for payments that are no longer
        pending_otp (succeeded / processing / canceled)."""
        token = _user_token(client)
        payment_id = self._make_pending_payment(client, token)
        for status in ("succeeded", "processing", "canceled"):
            db = _session(client)
            try:
                row = _get_wallet_row(db, payment_id)
                row.status = status
                db.commit()
            finally:
                db.close()
            resp = client.post(
                "/payment/confirm-otp",
                json={"payment_id": payment_id, "otp": OTP_VALUE},
                headers=_auth_headers(token),
            )
            assert resp.status_code == 400, f"status={status}: {resp.text}"

    def test_flood_guard_sixth_request_429(self, client):
        """Feature 5 rate-limit table: 5 OTP submissions per payment per
        10 minutes; the 6th is rejected with 429.

        The default mock fails verification, so after 3 failures the payment
        is canceled and requests 4-5 answer 400 — but every request still
        counts against the per-payment flood window.
        """
        token = _user_token(client)
        payment_id = self._make_pending_payment(client, token)
        for i in range(5):
            resp = client.post(
                "/payment/confirm-otp",
                json={"payment_id": payment_id, "otp": str(200000 + i)},
                headers=_auth_headers(token),
            )
            assert resp.status_code in (200, 400), f"otp {i}: {resp.text}"
        resp = client.post(
            "/payment/confirm-otp",
            json={"payment_id": payment_id, "otp": "300000"},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 429

    def test_otp_failed_audit_event_written(self, client, monkeypatch):
        """Every failed verification is audited as otp_failed (feeds the
        Feature 5 security monitor)."""
        token = _user_token(client)
        payment_id = self._make_pending_payment(client, token)
        resp = client.post(
            "/payment/confirm-otp",
            json={"payment_id": payment_id, "otp": OTP_VALUE},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        db = _session(client)
        try:
            from services.api.manual_payment_models import PaymentAuditLog

            event = (
                db.query(PaymentAuditLog)
                .filter(
                    PaymentAuditLog.action == "otp_failed",
                    PaymentAuditLog.order_ref == payment_id,
                )
                .first()
            )
            assert event is not None
            assert "1" in (event.detail or "")  # attempts=1
        finally:
            db.close()


# ---------------------------------------------------------------------------
# GET /payment/status/{payment_id} (wallet)
# ---------------------------------------------------------------------------


class TestWalletStatus:
    def test_status_pending_otp(self, client):
        token = _user_token(client)
        staging = _start_wallet_payment(client, token)
        resp = _confirm_wallet(client, token, staging)
        payment_id = resp.json()["payment_id"]
        resp = client.get(f"/payment/status/{payment_id}", headers=_auth_headers(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending_otp"
        assert data["package"] == "standard"
        assert data["amount_egp"] == 30.0

    def test_status_reflects_webhook_result(self, client):
        """After the webhook records a PaymentLog, status reflects the final
        state (the webhook is the single source of truth)."""
        token = _user_token(client)
        staging = _start_wallet_payment(client, token)
        resp = _confirm_wallet(client, token, staging)
        payment_id = resp.json()["payment_id"]

        db = _session(client)
        try:
            row = _get_wallet_row(db, payment_id)
            db.add(
                PaymentLog(
                    user_id=row.user_id,
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

        resp = client.get(f"/payment/status/{payment_id}", headers=_auth_headers(token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "succeeded"

    def test_other_users_payment_404(self, client):
        token_a = _user_token(client)
        token_b = _other_user_token(client)
        staging = _start_wallet_payment(client, token_a)
        resp = _confirm_wallet(client, token_a, staging)
        payment_id = resp.json()["payment_id"]
        resp = client.get(
            f"/payment/status/{payment_id}", headers=_auth_headers(token_b)
        )
        assert resp.status_code == 404

    def test_nonexistent_payment_404(self, client):
        token = _user_token(client)
        resp = client.get("/payment/status/nope", headers=_auth_headers(token))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Card flow regression (shared /payment/confirm + /payment/status surface)
# ---------------------------------------------------------------------------


class TestCardFlowStillWorks:
    def test_card_confirm_still_works(self, client, monkeypatch):
        """The confirm dispatcher must not regress the card path (Feature 1)."""
        monkeypatch.setattr(
            "services.api.routers.payment.create_payment_method",
            lambda token, payment_method_type="card": {"id": 42},
        )
        token = _user_token(client)
        start = client.get("/payment/start", headers=_auth_headers(token))
        staging = start.json()["staging_token"]
        resp = client.post(
            "/payment/confirm",
            json={
                "staging_token": staging,
                "method_type": "card",
                "token": "tok_mock_12345",
                "package": "standard",
            },
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

    def test_card_missing_token_400(self, client):
        token = _user_token(client)
        start = client.get("/payment/start", headers=_auth_headers(token))
        resp = client.post(
            "/payment/confirm",
            json={
                "staging_token": start.json()["staging_token"],
                "method_type": "card",
                "package": "standard",
            },
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400
