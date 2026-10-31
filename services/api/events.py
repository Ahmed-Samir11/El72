"""Validation rules for first-party app events (plans/p4 WS1).

Pure functions, no I/O: ``services/api/routers/events.py`` calls them and owns
the transport. Keeping the rules here lets the tests pin every refusal without
a database, and keeps one place where the event taxonomy is spelled.

Two kinds of refusal, on purpose:

* an event name outside :data:`EVENT_TYPES` fails the whole batch (the client
  is out of contract; fail fast), and
* a row whose *shape* is wrong is skipped and counted, so one bad row cannot
  cost the rest of a buffered batch.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from services.api.affiliate import (
    is_opaque_id,
    normalize_category,
    normalize_opaque_token,
)

# The report's §23 taxonomy plus the fields P1-P3 produce. Mirrored by the
# app_events_event_allowlist CHECK constraint in infra/sql/schema/timescaledb.sql;
# test_events.py fails if the two drift.
EVENT_TYPES: frozenset[str] = frozenset(
    {
        "search",
        "product_view",
        "comparison_view",
        "track_created",
        "track_removed",
        "price_change",
        "alert_sent",
        "alert_opened",
        "merchant_click",
        "purchase",
        "limit_hit",
        "error_observed",
    }
)

MAX_BATCH_EVENTS = 50
MAX_BODY_BYTES = 32 * 1024
MAX_PROPERTIES = 20
MAX_PROPERTIES_BYTES = 1024
# Property integers are counts, lengths and codes. A value this large is not a
# count; it is most likely an identifier (a phone number sent as a number
# loses its leading 0 and would otherwise slip past the text scan).
MAX_PROPERTY_INT = 10**9

# Delivery channels P2 can record; anything else is stored as NULL.
VALID_CHANNELS: frozenset[str] = frozenset({"in_app", "push", "whatsapp", "email"})

# Every key a row may carry. Anything else (including "user_id", which only
# the server sets, and any free-text field such as a search query) makes the
# row malformed, so a client cannot smuggle content past the column list.
ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "event",
        "session_id",
        "sku",
        "store_id",
        "category",
        "source",
        "channel",
        "product_id",
        "deal_id",
        "item_id",
        "event_id",
        "properties",
    }
)

# Opaque identifiers and their maximum lengths. event_id matches
# affiliate_clicks.event_id (String(64)) so the MS3 join key fits both tables.
_ID_FIELDS: dict[str, int] = {
    "sku": 128,
    "product_id": 128,
    "deal_id": 128,
    "item_id": 128,
    "event_id": 64,
    "store_id": 32,
}

_RANDOM_TOKEN_FIELDS = frozenset({"session_id", "event_id"})

_SOURCE_RE = re.compile(r"[a-z0-9_]{1,32}\Z")
_PROPERTY_KEY_RE = re.compile(r"[a-z0-9_]{1,40}\Z")
# A property string is an enum-like token ("network_error", "409", "ar"), never
# prose: no spaces, so a search query or any other user text cannot be stored
# as a property value.
_PROPERTY_VALUE_RE = re.compile(r"[A-Za-z0-9._:+\-]{1,64}\Z")
# Separators people put inside phone numbers, removed before the digit scan.
_PHONE_SEPARATORS = re.compile(r"[\s\-().,/_]")

# An Egyptian mobile number with its prefix (0, 20, +20 or 0020), not glued to
# other digits. The prefix is required so a long numeric product id is not
# mistaken for a phone.
_PHONE_RE = re.compile(r"(?<!\d)(?:\+20|0020|20|0)1[0125]\d{8}(?!\d)")

# Refusal reasons; the closed label set of el72_events_rejected_total.
REASON_UNKNOWN_EVENT = "unknown_event"
REASON_MALFORMED = "malformed"
REASON_PII = "pii"
REASON_BATCH_TOO_LARGE = "batch_too_large"
REASON_STORE_UNAVAILABLE = "store_unavailable"


class EventRejected(ValueError):
    """A single row was refused; ``reason`` is one of the ``REASON_*`` labels."""

    def __init__(self, reason: str) -> None:
        """Record why the row was refused."""
        super().__init__(reason)
        self.reason = reason


def unknown_event_names(rows: list[Any]) -> list[str]:
    """Event names in ``rows`` that are strings but outside :data:`EVENT_TYPES`.

    A row whose ``event`` is missing or not a string is a shape problem, left
    to :func:`validate_event`; only a well-formed but unknown name is the
    contract breach that fails the batch.
    """
    names = []
    for row in rows:
        if isinstance(row, dict):
            name = row.get("event")
            if isinstance(name, str) and name not in EVENT_TYPES:
                names.append(name)
    return names


def _all_digits(token: str) -> bool:
    """True for a token with no letters, e.g. a phone number used as an id.

    Client-minted random ids (hex or UUID) always contain letters in practice;
    an all-digit id is the shape a phone number takes when a client puts one
    where a random token belongs.
    """
    return not any(ch.isalpha() for ch in token)


def _looks_like_phone(value: str) -> bool:
    compact = _PHONE_SEPARATORS.sub("", value)
    return bool(_PHONE_RE.search(value) or _PHONE_RE.search(compact))


def _check_properties(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or len(raw) > MAX_PROPERTIES:
        raise EventRejected(REASON_MALFORMED)
    clean: dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not _PROPERTY_KEY_RE.match(key):
            raise EventRejected(REASON_MALFORMED)
        if isinstance(value, bool) or value is None:
            clean[key] = value
        elif isinstance(value, int):
            if abs(value) >= MAX_PROPERTY_INT:
                raise EventRejected(REASON_MALFORMED)
            clean[key] = value
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise EventRejected(REASON_MALFORMED)
            clean[key] = value
        elif isinstance(value, str):
            if _looks_like_phone(value):
                raise EventRejected(REASON_PII)
            if not _PROPERTY_VALUE_RE.match(value):
                raise EventRejected(REASON_MALFORMED)
            clean[key] = value
        else:
            # Nested objects and lists are where free text and payload dumps
            # hide; properties stay flat.
            raise EventRejected(REASON_MALFORMED)
    if len(json.dumps(clean, ensure_ascii=False).encode("utf-8")) > (
        MAX_PROPERTIES_BYTES
    ):
        raise EventRejected(REASON_MALFORMED)
    return clean


def validate_event(raw: Any) -> dict[str, Any]:
    """Return the storable columns for one event row, or raise :class:`EventRejected`.

    Args:
        raw: One element of the batch's ``events`` list, as decoded JSON.

    Returns:
        A dict with every ``app_events`` column the client may set (absent
        optional fields are ``None``). ``user_id`` and ``ts`` are never in it:
        the server sets both.

    Raises:
        EventRejected: with ``REASON_PII`` when any string looks like a phone
            number, otherwise ``REASON_MALFORMED`` for a shape problem.
    """
    if not isinstance(raw, dict) or set(raw) - ALLOWED_KEYS:
        raise EventRejected(REASON_MALFORMED)
    for key, value in raw.items():
        # session_id and event_id are random tokens the client mints; a long
        # random id can contain a phone-shaped digit run by chance, and
        # refusing it would silence that install for good. Both are held to
        # the opaque-token charset below and must contain a letter, which a
        # phone number pasted into either never does.
        if key in _RANDOM_TOKEN_FIELDS:
            continue
        if isinstance(value, str) and _looks_like_phone(value):
            raise EventRejected(REASON_PII)

    event = raw.get("event")
    if not isinstance(event, str) or event not in EVENT_TYPES:
        raise EventRejected(REASON_MALFORMED)

    session_raw = raw.get("session_id")
    session_id = (
        normalize_opaque_token(session_raw) if isinstance(session_raw, str) else None
    )
    if session_id is None or _all_digits(session_id):
        raise EventRejected(REASON_MALFORMED)

    row: dict[str, Any] = {"event": event, "session_id": session_id}
    for field, max_length in _ID_FIELDS.items():
        value = raw.get(field)
        if value is None:
            row[field] = None
            continue
        if not isinstance(value, str):
            raise EventRejected(REASON_MALFORMED)
        value = value.strip()
        if not value or len(value) > max_length or not is_opaque_id(value):
            raise EventRejected(REASON_MALFORMED)
        if field in _RANDOM_TOKEN_FIELDS and _all_digits(value):
            raise EventRejected(REASON_MALFORMED)
        row[field] = value

    # Context fields degrade to NULL instead of refusing the row: a bad label
    # must not cost the event itself (same rule as affiliate_clicks).
    category = raw.get("category")
    row["category"] = (
        normalize_category(category) if isinstance(category, str) else None
    )
    source = raw.get("source")
    source = source.strip().lower() if isinstance(source, str) else ""
    row["source"] = source if _SOURCE_RE.match(source) else None
    channel = raw.get("channel")
    # isinstance first: a list or dict is unhashable and would raise out of
    # the set lookup instead of degrading to NULL.
    row["channel"] = (
        channel if isinstance(channel, str) and channel in VALID_CHANNELS else None
    )

    row["properties"] = _check_properties(raw.get("properties"))
    return row
