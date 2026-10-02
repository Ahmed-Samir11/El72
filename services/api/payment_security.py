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
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional

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

    Card numbers, gateway tokens and OTPs are fully redacted; phone numbers
    and IBANs are masked (prefix + suffix kept) per the plan's log
    sanitization rules.
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


class SecurityMonitor:
    """Sliding-window failure counters for security-relevant events.

    ``record_failure`` returns True exactly when the threshold for that
    event is crossed within its window, so callers can emit an alert (and an
    audit entry) at most once per threshold crossing.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._windows: dict[str, deque] = {}
        self._alerted_at: dict[str, datetime] = {}

    def record_failure(self, event: str, now: Optional[datetime] = None) -> bool:
        """Record one failure for ``event``; return True if the threshold
        for that event is now exceeded within its window."""
        if now is None:
            now = datetime.now(timezone.utc)
        window_seconds = (
            WEBHOOK_SIGNATURE_WINDOW_SECONDS
            if event == "webhook_signature_failed"
            else OTP_FAILURE_WINDOW_SECONDS
        )
        threshold = (
            WEBHOOK_SIGNATURE_FAILURE_THRESHOLD
            if event == "webhook_signature_failed"
            else OTP_FAILURE_THRESHOLD
        )
        with self._lock:
            window = self._windows.setdefault(event, deque())
            window.append(now)
            # Evict entries outside the window.
            cutoff = now - timedelta(seconds=window_seconds)
            while window and window[0] < cutoff:
                window.popleft()
            count = len(window)
            if count >= threshold:
                last_alert = self._alerted_at.get(event)
                # Re-alert only after the window has fully reset (count back
                # below threshold) so a sustained attack does not spam.
                if last_alert is None or count < threshold + 1:
                    self._alerted_at[event] = now
                    return True
            return False

    def reset(self) -> None:
        """Clear all counters (tests)."""
        with self._lock:
            self._windows.clear()
            self._alerted_at.clear()


# Module-level singleton shared by the API process.
security_monitor = SecurityMonitor()


# ---------------------------------------------------------------------------
# Payment event audit
# ---------------------------------------------------------------------------

PAYMENT_EVENT_TYPES = frozenset(
    {
        "approve",
        "reject",
        "reveal_contact",
        "webhook_received",
        "webhook_signature_failed",
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
    actor_username: Optional[str] = None,
) -> PaymentAuditLog:
    """Append one row to the append-only payment audit log.

    ``detail`` must already be sanitized via :func:`sanitize_for_log`; this
    helper enforces it defensively so no caller can leak sensitive data.
    """
    if event_type not in PAYMENT_EVENT_TYPES:
        raise ValueError(f"Unknown payment event type: {event_type}")
    entry = PaymentAuditLog(
        action=event_type,
        target_user_id=user_id,
        order_ref=payment_ref,
        detail=sanitize_for_log(detail) if detail else None,
        client_ip=ip_address,
        actor_username=actor_username,
    )
    db.add(entry)
    return entry
