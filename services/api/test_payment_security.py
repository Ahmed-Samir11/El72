"""Tests for Feature 5: payment security & audit infrastructure.

Covers:
- sanitize_for_log (card numbers, tokens, OTPs, phones, IBANs)
- SecurityMonitor sliding-window failure counters + alert thresholds
- record_payment_event (append-only audit entry for ALL payment events)
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.admin_models import Admin
from services.api.dependencies import get_db, get_password_hash
from services.api.main import app
from services.api.manual_payment_models import PaymentAuditLog
from services.api.models import Base
from services.api.payment_security import (
    OTP_FAILURE_THRESHOLD,
    WEBHOOK_SIGNATURE_FAILURE_THRESHOLD,
    SecurityMonitor,
    record_payment_event,
    sanitize_for_log,
)

# ---------------------------------------------------------------------------
# sanitize_for_log
# ---------------------------------------------------------------------------


class TestSanitizeForLog:
    def test_card_number_redacted(self):
        msg = "card 4242424242424242 declined"
        assert sanitize_for_log(msg) == "card [CARD_REDACTED] declined"

    def test_gateway_token_redacted(self):
        msg = "payment with staging_token_abc123def failed"
        assert sanitize_for_log(msg) == "payment with [TOKEN_REDACTED] failed"

    def test_paymob_token_redacted(self):
        msg = "paymob_token_xyz789 attached"
        assert sanitize_for_log(msg) == "[TOKEN_REDACTED] attached"

    def test_otp_redacted_with_label_kept(self):
        msg = "OTP: 123456 entered"
        assert sanitize_for_log(msg) == "OTP: [OTP_REDACTED] entered"

    def test_phone_masked(self):
        msg = "user +201098765432 called"
        assert sanitize_for_log(msg) == "user +2010****5432 called"

    def test_iban_masked(self):
        msg = "transfer to EG1234567890123456789012 done"
        result = sanitize_for_log(msg)
        assert "[IBAN_MASKED]" in result
        assert "EG1234" in result  # prefix kept
        assert "9012" in result  # suffix kept
        # The full account body must not appear.
        assert "5678901234567890" not in result

    def test_safe_values_pass_through(self):
        msg = "order ELH-20250101-a3f2b1 amount 30.0 status approved user u1"
        assert sanitize_for_log(msg) == msg

    def test_empty_string_unchanged(self):
        assert sanitize_for_log("") == ""

    def test_unlabeled_short_numbers_pass_through(self):
        # Documented behavior: only labeled OTPs ("OTP: 123456") are
        # redacted; bare short numbers (amounts, counts) must not be.
        assert sanitize_for_log("amount 30.0 retries 5 code 123456") == (
            "amount 30.0 retries 5 code 123456"
        )


# ---------------------------------------------------------------------------
# SecurityMonitor
# ---------------------------------------------------------------------------


class TestSecurityMonitor:
    def setup_method(self):
        self.monitor = SecurityMonitor()

    def test_webhook_signature_alert_after_five_in_one_minute(self):
        base = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alerts = [
            self.monitor.record_failure(
                "webhook_signature_failed", now=base + timedelta(seconds=i)
            )
            for i in range(WEBHOOK_SIGNATURE_FAILURE_THRESHOLD)
        ]
        # Only the threshold-crossing failure raises an alert.
        assert alerts[:-1] == [False] * (WEBHOOK_SIGNATURE_FAILURE_THRESHOLD - 1)
        assert alerts[-1] is True

    def test_webhook_signature_no_realert_while_sustained(self):
        base = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(WEBHOOK_SIGNATURE_FAILURE_THRESHOLD + 3):
            self.monitor.record_failure(
                "webhook_signature_failed", now=base + timedelta(seconds=i)
            )
        # Failures after the first alert do not re-alert while the window is hot.
        assert (
            self.monitor.record_failure(
                "webhook_signature_failed", now=base + timedelta(seconds=10)
            )
            is False
        )

    def test_otp_alert_after_ten_in_one_hour(self):
        base = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alerts = [
            self.monitor.record_failure("otp_failed", now=base + timedelta(minutes=i))
            for i in range(OTP_FAILURE_THRESHOLD)
        ]
        assert sum(alerts) == 1
        assert alerts[-1] is True

    def test_window_expiry_prevents_false_alert(self):
        base = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        # 4 failures, then a gap longer than the 1-minute window.
        for i in range(4):
            self.monitor.record_failure(
                "webhook_signature_failed", now=base + timedelta(seconds=i)
            )
        # 5th failure 2 minutes later: the first four have expired from the
        # window, so no alert.
        assert (
            self.monitor.record_failure(
                "webhook_signature_failed", now=base + timedelta(minutes=2)
            )
            is False
        )

    def test_independent_event_counters(self):
        base = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(WEBHOOK_SIGNATURE_FAILURE_THRESHOLD):
            self.monitor.record_failure(
                "webhook_signature_failed", now=base + timedelta(seconds=i)
            )
        # OTP counter is independent and unaffected.
        assert (
            self.monitor.record_failure("otp_failed", now=base + timedelta(seconds=1))
            is False
        )

    def test_sustained_attack_alerts_exactly_once(self):
        base = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alerts = [
            self.monitor.record_failure(
                "webhook_signature_failed", now=base + timedelta(seconds=i)
            )
            for i in range(10)
        ]
        # One alert for the whole sustained attack (count stays >= threshold).
        assert sum(alerts) == 1
        assert alerts[WEBHOOK_SIGNATURE_FAILURE_THRESHOLD - 1] is True

    def test_rearms_after_window_drains_below_threshold(self):
        base = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(WEBHOOK_SIGNATURE_FAILURE_THRESHOLD):
            self.monitor.record_failure(
                "webhook_signature_failed", now=base + timedelta(seconds=i)
            )
        # Two minutes later the whole first window has expired.
        second_wave = [
            self.monitor.record_failure(
                "webhook_signature_failed",
                now=base + timedelta(minutes=2, seconds=i),
            )
            for i in range(WEBHOOK_SIGNATURE_FAILURE_THRESHOLD)
        ]
        # A fresh attack re-arms and alerts again.
        assert sum(second_wave) == 1


# ---------------------------------------------------------------------------
# record_payment_event
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session():
    """Fresh in-memory DB with the get_db dependency overridden."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    db = TestingSessionLocal()
    yield db
    db.close()
    app.dependency_overrides.clear()


class TestRecordPaymentEvent:
    def test_webhook_event_persisted(self, db_session):
        entry = record_payment_event(
            db_session,
            event_type="webhook_received",
            user_id="u1",
            payment_ref="ELH-20250101-a3f2b1",
            detail="signature verified",
            ip_address="203.0.113.7",
        )
        db_session.commit()
        rows = (
            db_session.query(PaymentAuditLog)
            .filter_by(order_ref="ELH-20250101-a3f2b1")
            .all()
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.action == "webhook_received"
        assert row.detail == "signature verified"
        assert row.client_ip == "203.0.113.7"
        assert entry.id is not None

    def test_detail_is_sanitized_on_write(self, db_session):
        record_payment_event(
            db_session,
            event_type="amount_mismatch",
            payment_ref="ELH-20250101-b4c5d6",
            detail="card 4242424242424242 token staging_token_abc mismatch",
        )
        db_session.commit()
        row = (
            db_session.query(PaymentAuditLog)
            .filter_by(order_ref="ELH-20250101-b4c5d6")
            .one()
        )
        assert "4242424242424242" not in row.detail
        assert "[CARD_REDACTED]" in row.detail
        assert "[TOKEN_REDACTED]" in row.detail

    def test_unknown_event_type_rejected(self, db_session):
        with pytest.raises(ValueError):
            record_payment_event(db_session, event_type="not_a_real_event")
        # Nothing was added to the session.
        db_session.rollback()
        assert db_session.query(PaymentAuditLog).count() == 0

    def test_all_plan_event_types_accepted(self, db_session):
        from services.api.payment_security import PAYMENT_EVENT_TYPES

        for event_type in PAYMENT_EVENT_TYPES:
            record_payment_event(
                db_session, event_type=event_type, payment_ref=f"ref-{event_type}"
            )
        db_session.commit()
        assert db_session.query(PaymentAuditLog).count() == len(PAYMENT_EVENT_TYPES)

    def test_actor_attribution_persisted(self, db_session):
        record_payment_event(
            db_session,
            event_type="approve",
            user_id="u1",
            payment_ref="ELH-20250101-c7d8e9",
            actor_id="admin-uuid-123",
            actor_username="admin1",
        )
        db_session.commit()
        row = (
            db_session.query(PaymentAuditLog)
            .filter_by(order_ref="ELH-20250101-c7d8e9")
            .one()
        )
        assert row.actor_id == "admin-uuid-123"
        assert row.actor_username == "admin1"


# ---------------------------------------------------------------------------
# Rate limiting on payment endpoints
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """Test client with a fresh in-memory DB (mirrors test_manual_payment)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    with TestingSessionLocal() as db:
        db.add(
            Admin(username="admin1", password_hash=get_password_hash("admin-secret"))
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
        yield c
    app.dependency_overrides.clear()


class TestRateLimits:
    # (rate-limiter state is reset per test by the autouse fixture in
    # services/api/conftest.py)

    def test_status_endpoint_returns_429_after_limit(self, client):
        reg = client.post(
            "/auth/register", json={"phone": "+201011111111", "password": "pw12345678"}
        )
        assert reg.status_code == 200, reg.text
        login = client.post(
            "/auth/login", json={"phone": "+201011111111", "password": "pw12345678"}
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        created = client.post(
            "/payment/manual", json={"package": "standard"}, headers=headers
        )
        assert created.status_code == 200, created.text
        order_ref = created.json()["order_ref"]

        responses = [
            client.get(f"/payment/manual/{order_ref}", headers=headers)
            for _ in range(31)
        ]
        # The endpoint is limited to 30/minute per IP: the 31st call is 429.
        assert all(r.status_code == 200 for r in responses[:30])
        assert responses[30].status_code == 429
