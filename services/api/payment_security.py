"""Cross-cutting payment security infrastructure (Feature 5).

Provides:

- ``sanitize_for_log``: redacts card numbers, gateway tokens, OTPs, phone
  numbers and IBANs so sensitive data never reaches log output.
- ``SecurityMonitor``: sliding-window failure counters that raise an alert
  (returned to the caller) when thresholds are exceeded:
    * 5+ failed webhook signatures within 1 minute
    * 10+ OTP failures within 1 hour
- ``record_payment_event``: single entry point for writing ANY payment event
  into the append-only ``payment_audit_log`` (admin actions included).

Secrets are only ever read from environment variables; nothing in this module
logs or stores raw secret values.
"""

import re
import threading
import time
from collections import deque
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from services.api.manual_payment_models import PaymentAuditLog

# ---------------------------------------------------------------------------
# Log sanitization
# ---------------------------------------------------------------------------

# 13-19 consecutive digits: PAN/card numbers (and anything that looks like one).
_CARD_RE = re.compile(r"\b\d{13,19}\b")
# Paymob-style tokens: staging_token_xxx / token_xxx / paymob_token_xxx.
_TOKEN_RE = re.compile(r"\b(?:paymob_)?(?:staging_)?token_[a-z0-9]+", re.IGNORECASE)
# "OTP: 123456" / "otp 123456" — redact the digits, keep the label.
_OTP_RE = re.compile(r"\b(otp)\s*[:\-]?\s*(\d{4,8})\b", re.IGNORECASE)
# Egyptian phone numbers in +20XXXXXXXXXX form: keep country code + first
# two digits and the last three to four digits, mask the middle.
_PHONE_RE = re.compile(r"(\+20)(\d{2})\d{2,4}(\d{3,4})")
# IBAN: EG + 4 check digits + bank code + account number; mask the middle.
_IBAN_RE = re.compile(r"\b([A-Z]{2}\d{4})[A-Z0-9]{8,18}(\d{4})\b")


def sanitize_for_log(value: str) -> str:
    """Redact sensitive data from a string before it is written to logs.

    Card numbers, gateway tokens and labeled OTPs are fully redacted; phone
    numbers and IBANs are masked (prefix + suffix kept) per the plan's log
    sanitization rules.

    Documented limitation: secrets embedded without any recognizable label
    or shape (e.g. a bare 6-digit code with no "otp" nearby) cannot be
    detected reliably — redacting arbitrary digit runs would corrupt
    amounts, counts and order data. Callers must not log raw secrets.
    """
    if not value:
        return value
    value = _CARD_RE.sub("[CARD_REDACTED]", value)
    value = _TOKEN_RE.sub("[TOKEN_REDACTED]", value)
    value = _OTP_RE.sub(lambda m: f"{m.group(1).upper()}: [OTP_REDACTED]", value)
    value = _IBAN_RE.sub(r"\1[IBAN_MASKED]\2", value)
    value = _PHONE_RE.sub(r"\1\2****\3", value)
    return value


# ---------------------------------------------------------------------------
# Security monitoring
# ---------------------------------------------------------------------------

WEBHOOK_SIGNATURE_FAILURE_THRESHOLD = 5
WEBHOOK_SIGNATURE_WINDOW_SECONDS = 60
OTP_FAILURE_THRESHOLD = 10
OTP_FAILURE_WINDOW_SECONDS = 3600

# Explicit per-event configuration. Events not listed here are NOT tracked
# (record_failure logs a warning and returns False) so an unknown event can
# never silently inherit another event's threshold.
_EVENT_CONFIG: dict[str, tuple[int, int]] = {
    "webhook_signature_failed": (
        WEBHOOK_SIGNATURE_WINDOW_SECONDS,
        WEBHOOK_SIGNATURE_FAILURE_THRESHOLD,
    ),
    "otp_failed": (OTP_FAILURE_WINDOW_SECONDS, OTP_FAILURE_THRESHOLD),
}


class SecurityMonitor:
    """Sliding-window failure counters for security-relevant events.

    ``record_failure`` returns True exactly when the threshold for that
    event is crossed within its window, so callers can emit an alert (and an
    audit entry) at most once per threshold crossing.

    Windows store epoch-second floats (``time.time()``), so there is no
    datetime object to get naive/aware mixed up in the eviction math.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._windows: dict[str, deque] = {}
        # Events currently in the "already alerted" state (re-armed only
        # after the count drops back below the threshold).
        self._alerting: dict[str, bool] = {}

    def record_failure(self, event: str, now: Optional[float] = None) -> bool:
        """Record one failure for ``event``; return True if the threshold
        for that event is now exceeded within its window.

        ``now`` is an epoch-seconds float (defaults to ``time.time()``);
        pass an explicit value in tests.
        """
        config = _EVENT_CONFIG.get(event)
        if config is None:
            logger.warning(
                "SecurityMonitor: untracked event type {!r}; not counted", event
            )
            return False
        window_seconds, threshold = config
        if now is None:
            now = time.time()
        with self._lock:
            window = self._windows.setdefault(event, deque())
            window.append(now)
            # Evict entries outside the window.
            cutoff = now - window_seconds
            while window and window[0] < cutoff:
                window.popleft()
            count = len(window)
            if count >= threshold:
                # Alert once per attack: stay in the alerted state for as long
                # as the window keeps meeting the threshold (a sustained
                # attack does not spam), and re-arm only after the count has
                # dropped back below the threshold.
                if not self._alerting.get(event, False):
                    self._alerting[event] = True
                    return True
                return False
            # Below threshold again: re-arm for a future attack.
            self._alerting.pop(event, None)
            return False

    def reset(self) -> None:
        """Clear all counters and alert states (tests)."""
        with self._lock:
            self._windows.clear()
            self._alerting.clear()


# Module-level singleton shared by the API process.
security_monitor = SecurityMonitor()


# ---------------------------------------------------------------------------
# Payment event audit
# ---------------------------------------------------------------------------

# NOTE: must stay in sync with the CHECK constraint on payment_audit_log.action
# in infra/sql/schema.sql (a test in test_payment_security.py asserts the two
# match).
PAYMENT_EVENT_TYPES = frozenset(
    {
        "approve",
        "reject",
        "reveal_contact",
        "webhook_received",
        "webhook_signature_failed",
        "webhook_duplicate",
        "validation_rejected",
        "otp_failed",
        "token_expired",
        "amount_mismatch",
    }
)


def record_payment_event(
    db: Session,
    event_type: str,
    user_id: Optional[str] = None,
    payment_ref: Optional[str] = None,
    detail: Optional[str] = None,
    ip_address: Optional[str] = None,
    actor_id: Optional[str] = None,
    actor_username: Optional[str] = None,
    target_user_phone: Optional[str] = None,
) -> PaymentAuditLog:
    """Append one row to the append-only payment audit log.

    This is the single entry point for ALL payment audit writes (admin
    actions included); do not construct ``PaymentAuditLog`` directly.

    ``detail`` must already be sanitized via :func:`sanitize_for_log`; this
    helper enforces it defensively so no caller can leak sensitive data.

    Admin-attributed events pass both ``actor_id`` (FK admins) and
    ``actor_username`` (snapshot that survives admin deletion).

    The entry is only added to the session: the CALLER is responsible for
    committing (or rolling back) the transaction.
    """
    if event_type not in PAYMENT_EVENT_TYPES:
        raise ValueError(f"Unknown payment event type: {event_type}")
    entry = PaymentAuditLog(
        action=event_type,
        target_user_id=user_id,
        order_ref=payment_ref,
        detail=sanitize_for_log(detail) if detail else None,
        client_ip=ip_address,
        actor_id=actor_id,
        actor_username=actor_username,
        target_user_phone=target_user_phone,
    )
    db.add(entry)
    return entry
