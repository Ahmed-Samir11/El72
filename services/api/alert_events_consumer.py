"""Alert-event consumer: ``stream:alerts`` -> ``alert_events`` (plans/p2 WS1).

The scraper's alert emitter has always published price events to
``stream:alerts``; nothing on the API side ever persisted them, so the client
alert path was write-only and a price drop was gone by the next app open
(plan p2, finding N2). This module owns the missing leg: it turns one event
into a row that belongs to the OWNING user, which ``GET /alerts/recent``
then reads back.

Business contract (report §26 Gate 2 "do users return?", §23 ``price_change``
/ ``alert_sent`` / ``alert_opened``): every event becomes attributable, per-user,
deduped history, so "an alert the user actually saw" can later be counted
against "an alert that was only written".

Service isolation (AGENTS): this consumer reads Redis Streams only — never
another service's code or database — and writes only ``services/api``'s own
``alert_events`` table.

Reliability rules this file exists to enforce:
* ``ensure_group`` runs before the first read, and is re-asserted after any
  reconnect, so a dropped group can never strand the pipeline;
* every message the consumer DECIDES about — stored, duplicate, unknown item,
  owner mismatch, unsupported type, undecodable payload — is ``XACK``ed exactly
  once, because an undecided message would be re-read forever;
* a FAILURE (transient database error or an unexpected bug) is NOT acked: the
  entry stays in the group's pending list, where XPENDING/XAUTOCLAIM and
  ``el72_alert_events_failed_total`` make it visible instead of silently lost.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from services.api.affiliate import normalize_category
from services.api.models import Alert, AlertEvent
from services.api.monitoring.metrics import (
    ALERT_EVENTS_ACK_ERRORS_TOTAL,
    ALERT_EVENTS_CONSUMER_UP,
    ALERT_EVENTS_DISCARDED_TOTAL,
    ALERT_EVENTS_FAILED_TOTAL,
    ALERT_EVENTS_READ_ERRORS_TOTAL,
    ALERT_EVENTS_RECEIVED_TOTAL,
    ALERT_EVENTS_REDRAWS_TOTAL,
    ALERT_EVENTS_SKIPPED_TOTAL,
    ALERT_EVENTS_STORED_TOTAL,
)
from services.api.tracked_items_models import TrackedItem
from services.common.currency import EGP_TO_USD, EXCHANGE_RATES
from services.common.redis_client import RedisStreamClient

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
ALERTS_STREAM = os.getenv("ALERTS_STREAM", "stream:alerts")
CONSUMER_GROUP = os.getenv("ALERTS_CONSUMER_GROUP", "cg_alerts_api")
CONSUMER_NAME = (
    os.getenv("ALERTS_CONSUMER_NAME")
    or f"alerts_api_{socket.gethostname()}-{os.getpid()}"
)


# Batch size / block time are ops-tunable (same pattern as the affiliate
# redirect rate cap: env overrides, built-in default when unset). A malformed
# value must not be a boot failure: the default is used and the mistake is
# logged, so a typo in .env cannot take the alert feed down silently or loudly.
def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        logger.warning(
            "Invalid %s; using default", name, extra={"value": raw, "default": default}
        )
        return default
    if value < minimum:
        logger.warning(
            "%s below minimum; using default",
            name,
            extra={"value": raw, "default": default},
        )
        return default
    return value


READ_COUNT = _env_int("ALERTS_CONSUMER_READ_COUNT", 10, minimum=1)
READ_BLOCK_MS = _env_int("ALERTS_CONSUMER_BLOCK_MS", 5000, minimum=100)
READ_BACKOFF_SECONDS = 5.0

# The four event types the alert emitter produces (services/scraper/alert_emitter.py
# AlertType) and the only values the canonical CHECK allows. Anything else —
# including a scrape_failure record sent to the wrong stream — is unsupported
# here, logged and counted, never guessed at.
VALID_EVENT_TYPES = frozenset(
    {"price_drop", "threshold_crossed", "lowest_price_changed", "back_in_stock"}
)

# One alert per item per event type PER CALENDAR DAY (the fair-use rate rule
# the free tracker model is built on): a market that jitters its price all day
# must not turn into a wall of identical cards. Implemented as a floor on the
# UTC day (hour 0) in the dedupe query below, not a rolling 24 h window, so
# "today" means the same thing to the consumer, the query and the ops dashboard.

# A stream message is a durable fact, but a consumer that keeps failing on it
# must not retry it forever: after this many deliveries the entry is acked and
# counted as discarded, so lag is bounded and the loss is loud.
MAX_DELIVERY_ATTEMPTS = 3

# Outcome labels — also the Prometheus label values, so a review can read the
# same set from the metrics as from the code.
OUTCOME_STORED = "stored"
OUTCOME_DUPLICATE = "duplicate"
OUTCOME_UNKNOWN_ITEM = "unknown_item"
OUTCOME_OWNER_MISMATCH = "owner_mismatch"
OUTCOME_INVALID = "invalid"
OUTCOME_UNSUPPORTED = "unsupported_event_type"
OUTCOME_FAILED = "failed"
# Not a decision about the EVENT: the decision was made, but XACK did not take.
# It must count as retryable — an entry that stays pending while the consumer
# reports success would be re-read without backoff, hot-spinning the pending
# pass and starving new messages.
OUTCOME_ACK_FAILED = "ack_failed"
# Poison pills remembered so a failed XACK cannot make the same entry loop
# forever; bounded because a long-lived process must not accumulate ids.
DISCARDED_MEMORY = 1024
# Alias used by the retry bookkeeping (both memories are bounded the same way).
DELIVERY_MEMORY = DISCARDED_MEMORY
# The name of the same-day UNIQUE index created by infra/sql/schema/postgres.sql
# and migration 0013 (pinned there by test_alert_events_schema_sync). Kept here
# as a string only, so an unrelated IntegrityError can be told apart from this
# dedupe violation (see _is_same_day_unique).
SAME_DAY_UNIQUE_INDEX = "uq_alert_events_item_type_day"

# Cap for a stored url: the Alerts card later taps it through merchant_link
# -> /affiliate/redirect, whose real guard is the merchant host allowlist
# (affiliate.STORE_HOSTS). This bound only keeps an oversized/garbage value out
# of a column that feeds that tap.
MAX_URL_LENGTH = 2048


def _decode(value: Any) -> str | None:
    """Decode a Redis field name or value (the client uses bytes responses)."""
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return str(value)


def _utc_now() -> datetime:
    """Naive UTC \"now\".

    Naive is deliberate and matches the column type: alert_events stores
    TIMESTAMP WITHOUT TIME ZONE, so a window comparison (the same-day dedupe)
    must be built from the same kind of timestamp as the value it compares
    against. An aware value here would raise \"can't compare offset-naive and
    offset-aware datetimes\" in production and not in the SQLite tests.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _event_time(event: dict[str, Any]) -> datetime:
    """When the event HAPPENED, not when this consumer got round to it.

    The emitter stamps the payload; using processing time instead would make a
    backlog rewrite history (an event that happened yesterday landing as
    today's alert, and stealing today's dedupe slot). Falls back to now when
    the stamp is missing or unparseable, and drops the offset so the value
    matches the naive-UTC column (see _utc_now).
    """
    raw = _decode(event.get("timestamp"))
    if raw:
        try:
            # "Z" is what the emitter writes; normalize rather than rely on the
            # interpreter's ISO support (same normalization the API router does).
            parsed = datetime.fromisoformat(
                raw[:-1] + "+00:00" if raw.endswith("Z") else raw
            )
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
    return _utc_now()


def _event_metadata(event: dict[str, Any]) -> dict[str, Any]:
    """The payload's metadata as a dict — or an empty one.

    A hostile or malformed payload can carry metadata as a list, a string or a
    number; ``(event.get('metadata') or {}).get(...)`` would then raise,
    which leaves the message pending forever. The metadata is display context,
    never identity, so a value that is not an object yields nothing.
    """
    metadata = event.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def parse_event(fields: Mapping[Any, Any]) -> dict[str, Any] | None:
    """Decode one stream message's ``payload`` JSON into a dict.

    Returns ``None`` for anything the consumer can never make a row from: a
    message without a payload field, non-JSON, a JSON non-object, or undecodable
    bytes. The caller acks and counts that message; it is not retried forever.
    """
    raw = None
    for key, value in fields.items():
        if _decode(key) == "payload":
            raw = value
            break
    if raw is None:
        return None
    text = _decode(raw)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _clean_str(value: Any, max_length: int) -> str | None:
    """Trim a payload string and drop anything empty or oversized."""
    text = _decode(value)
    if text is None:
        return None
    text = text.strip()
    return text[:max_length] if 0 < len(text) <= max_length else None


def _clean_float(value: Any) -> float | None:
    """Coerce a payload number, refusing bools, strings-with-junk and NaN."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value) if not isinstance(value, str) else float(value.strip())
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _bounded_decimal(
    value: float | None, max_digits: int, scale: int = 2
) -> Decimal | None:
    """Round a price to the column's scale, or NULL if it does not fit.

    ``NUMERIC(12,2)``/``NUMERIC(6,2)`` raise on an out-of-range value at insert
    time. A wild price from a bad scrape must not kill the row (the event still
    happened) nor the consumer, so an unrepresentable value degrades to NULL
    and the event lands without a bogus delta.
    """
    if value is None:
        return None
    try:
        quantum = Decimal(1).scaleb(-scale)
        number = Decimal(str(value)).quantize(quantum)
    except (InvalidOperation, ValueError):
        return None
    limit = Decimal(10) ** (max_digits - scale)
    return number if abs(number) < limit else None


def _to_egp(local: float | None, usd: float | None, currency: Any) -> float | None:
    """Express an event price in EGP — the unit the app displays.

    Preference order is honesty first: a store's own local reading when it is
    already EGP, then a local reading converted with the shared approximation
    constants (services/common/currency), then the USD reading converted the
    same way. These are documented approximations, not a live rate feed, which
    is exactly why the column is named ``*_egp`` and not quoted as a market fact.
    """
    code = (_decode(currency) or "").strip().upper()
    if local is not None and code == "EGP":
        return local
    if local is not None and code in EXCHANGE_RATES:
        # price_local is expressed in `currency`; EXCHANGE_RATES maps a unit to
        # USD, and EGP_TO_USD is its inverse.
        return local * EXCHANGE_RATES[code] / EGP_TO_USD
    if usd is not None:
        return usd / EGP_TO_USD
    return None


def _clean_url(value: Any) -> str | None:
    """Keep a plausible http/https product url out of the tap target.

    Not the security boundary — /affiliate/redirect re-checks the merchant host
    allowlist at tap time — just a guard against storing markup or a 10 KB blob
    in a column the client renders as a link.
    """
    url = _clean_str(value, MAX_URL_LENGTH)
    if url is None:
        return None
    return url if url.startswith(("http://", "https://")) else None


def _usd_to_egp(value: float | None) -> float | None:
    """Convert an emitter reading expressed in USD to EGP.

    The emitter prices threshold/target/old values in USD (``target_price",
    "old_price_usd``), while the card and the column are EGP; without this step
    a 30 (USD) target would be displayed as EGP 30. Approximation constants only
    (services/common/currency) — hence a comparison in one unit, never a claim
    of a market-accurate rate.
    """
    if value is None:
        return None
    return value / EGP_TO_USD


def _reference_price_egp(event: dict[str, Any], event_type: str) -> float | None:
    """The price the event is measured AGAINST, expressed in EGP.

    A threshold crossing is measured against the user's own target; every other
    event type against the previous reading. Either can be absent — "the price
    changed" is still a fact, "it fell 12%" is not claimable then.
    """
    if event_type == "threshold_crossed":
        return _usd_to_egp(_clean_float(event.get("target_price")))
    return _usd_to_egp(_clean_float(event.get("old_price_usd")))


def _discount_pct(
    event: dict[str, Any], price_egp: float | None, reference_egp: float | None
) -> Decimal | None:
    """Percent under the reference price, from the emitter's own metadata first.

    The emitter already computed ``drop_percentage`` for a price drop; recompute
    only when it is missing and both prices exist. Bounded to 0-100 — a "120%
    discount" is a data error, not a deal, and must not become a headline card.
    """
    claimed = _event_metadata(event).get("drop_percentage")
    claimed = _clean_float(claimed)
    if claimed is not None:
        candidate = claimed
    elif reference_egp and price_egp is not None and reference_egp > price_egp:
        candidate = (reference_egp - price_egp) / reference_egp * 100
    else:
        return None
    candidate = min(max(candidate, 0.0), 100.0)
    return _bounded_decimal(candidate, max_digits=6, scale=2)


def _resolve_owner(db: Session, tracked_item_id: int) -> int | None:
    """Return the user who OWNS the tracked item the event is about.

    The event's own ``user_id`` field is NOT trusted as identity: tracked_items
    is the scraper-owned source of truth for who a product belongs to, so a
    payload naming a different user is hostile or stale, and its row would leak
    one user's market data into another user's feed.
    """
    return db.execute(
        select(TrackedItem.user_id).where(TrackedItem.id == tracked_item_id)
    ).scalar_one_or_none()


def _fill_category(
    db: Session, sku: str | None, event: dict[str, Any], owner_id: int
) -> str | None:
    """Category for the event: the emitter's own value if it sent a safe one,
    otherwise the server's product context from the OWNER's tracker row.

    Reuses affiliate.normalize_category — the same clamp the affiliate click
    uses — so one metric dimension cannot be polluted by markup or a
    scheme-shaped token, and the stored value stays length-bounded even when
    older rows predate today's rules. The lookup is scoped to the alert's
    owner: another user's category for the same SKU is not this user's product
    context, and guessing it would make one user's card depend on another's
    data. No owner-scoped row means no category, not a stranger's.
    """
    claimed = normalize_category(_decode(_event_metadata(event).get("category")))
    if claimed:
        return claimed
    if not sku:
        return None
    return normalize_category(
        db.execute(
            select(Alert.category)
            .where(
                Alert.sku == sku,
                Alert.user_id == owner_id,
                Alert.category.isnot(None),
            )
            .order_by(Alert.id)
            .limit(1)
        )
        .scalars()
        .first()
    )


def store_event(
    session_factory: Callable[[], Session],
    event: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> str:
    """Persist one decoded alert event as ``alert_events`` rows.

    Returns an outcome label. All decisions are terminal: a row is written, or
    the event is skipped for a named, counted reason. Unknown item, owner
    mismatch and unsupported type are permanent conditions (acking them is
    correct); only a database failure is treated as transient, and it is
    raised so the caller can leave the message unacknowledged.
    """
    if not event:
        return OUTCOME_INVALID

    event_type = (_decode(event.get("alert_type")) or "").strip()
    if event_type not in VALID_EVENT_TYPES:
        return OUTCOME_UNSUPPORTED

    tracked_item_id = _clean_float(event.get("tracked_item_id"))
    if tracked_item_id is None or tracked_item_id != int(tracked_item_id):
        return OUTCOME_INVALID
    tracked_item_id = int(tracked_item_id)

    now = now or _event_time(event)
    with session_factory() as db:
        owner_id = _resolve_owner(db, tracked_item_id)
        if owner_id is None:
            # A price event for a product nobody tracks (deleted tracker, or a
            # probe with an invented id): skipped and counted, never crashed.
            return OUTCOME_UNKNOWN_ITEM

        claimed_user = _clean_float(event.get("user_id"))
        if claimed_user is not None and (
            claimed_user != int(claimed_user) or int(claimed_user) != int(owner_id)
        ):
            # Fractional or disagreeing: the payload is not trusted either way,
            # but a value that cannot be an id is not treated as agreement with
            # one ("1.9" must never match user 1).
            return OUTCOME_OWNER_MISMATCH

        # Same-day rule, floored on the day the EVENT happened (see _event_time),
        # in the naive-UTC kind the column stores. The upper bound is what
        # keeps this read aligned with uq_alert_events_item_type_day: an open-
        # ended >= would also match a row dated in a LATER day (a clock-skewed
        # or out-of-order stamp) and suppress today's alert, while the unique
        # index would happily allow that second row — two definitions of "same
        # day" is exactly the drift this test suite exists to prevent.
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        exists = db.execute(
            select(AlertEvent.id)
            .where(
                AlertEvent.tracked_item_id == tracked_item_id,
                AlertEvent.event_type == event_type,
                AlertEvent.created_at >= day_start,
                AlertEvent.created_at < day_start + timedelta(days=1),
            )
            .limit(1)
        ).first()
        if exists is not None:
            return OUTCOME_DUPLICATE

        raw_sku = event.get("canonical_product_id")
        sku = _clean_str(raw_sku, 255)
        price_egp = _to_egp(
            _clean_float(event.get("new_price_local")),
            _clean_float(event.get("new_price_usd")),
            event.get("currency"),
        )
        reference_egp = _reference_price_egp(event, event_type)

        db.add(
            AlertEvent(
                user_id=owner_id,
                tracked_item_id=tracked_item_id,
                sku=sku,
                store_id=_clean_str(event.get("store_id"), 32),
                category=_fill_category(db, sku, event, owner_id),
                url=_clean_url(event.get("url")),
                event_type=event_type,
                price_egp=(
                    _bounded_decimal(price_egp, max_digits=12)
                    if price_egp is not None
                    else None
                ),
                reference_price_egp=(
                    _bounded_decimal(reference_egp, max_digits=12)
                    if reference_egp is not None
                    else None
                ),
                discount_pct=_discount_pct(event, price_egp, reference_egp),
                # 'in_app' is the only channel this build delivers; a row
                # claiming 'push'/'whatsapp' would promise a send that did not
                # happen (plan p2 WS3 truth rule). The channel widens with the
                # sender that ships it.
                channel="in_app",
                created_at=now,
            )
        )
        try:
            db.commit()
        except IntegrityError as exc:
            if not _is_same_day_unique(exc):
                # Not our dedupe index: a user FK racing an account deletion,
                # or a constraint a later migration adds. Calling every
                # integrity error a "duplicate" would ack the message and make
                # the breakage invisible, so this re-raises into the caller's
                # transient-failure path (left pending, counted, bounded retries).
                raise
            db.rollback()
            return OUTCOME_DUPLICATE
        return OUTCOME_STORED


def _is_same_day_unique(exc: IntegrityError) -> bool:
    """True only when the violated constraint is alert_events' same-day index.

    The name is read from the driver when it exposes it (psycopg2 diagnostics)
    and from the message otherwise — SQLite names it
    ``uq_alert_events_item_type_day`` in the IntegrityError text, the same name
    the canonical schema and migration 0013 create.
    """
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    haystacks = (
        getattr(diag, "constraint", None),
        str(orig or ""),
        str(exc),
    )
    return any(text and SAME_DAY_UNIQUE_INDEX in text for text in haystacks if text)


async def _store_event_off_loop(
    session_factory: Callable[[], Session],
    event: dict[str, Any] | None,
) -> str:
    """Run the synchronous SQLAlchemy write, keeping the event loop free.

    AGENTS forbids blocking I/O on an async service's event loop, so the
    psycopg2-backed production write goes to a worker thread. SQLite stays inline:
    its engine is one shared connection with a thread guard, so threading it
    would turn a legitimate dev run into an OperationalError for no benefit (the
    write itself is microseconds against a local file).
    """
    if os.getenv("DATABASE_URL", "").strip().lower().startswith("sqlite"):
        return store_event(session_factory, event)
    return await asyncio.to_thread(store_event, session_factory, event)


async def process_message(
    redis: RedisStreamClient,
    stream: str,
    group: str,
    message_id: str,
    fields: Mapping[Any, Any],
    session_factory: Callable[[], Session],
) -> str:
    """Persist one message and acknowledge it. Returns the outcome label.

    Ack policy (see the module docstring): everything the consumer can decide
    about is acked; a transient database failure is the one case left pending.
    """
    ALERT_EVENTS_RECEIVED_TOTAL.inc()
    event = parse_event(fields)
    try:
        outcome = await _store_event_off_loop(session_factory, event)
    except SQLAlchemyError as exc:
        # Transient: leave acked-to-nobody so the entry stays in the group's
        # pending list (observable as consumer lag), rather than losing an event.
        ALERT_EVENTS_FAILED_TOTAL.inc()
        logger.error(
            "Alert event write failed; message left pending",
            extra={"message_id": _decode(message_id), "error": str(exc)},
        )
        return OUTCOME_FAILED
    except Exception:  # noqa: BLE001 - bug guard: counted, left pending, never fatal
        ALERT_EVENTS_FAILED_TOTAL.inc()
        logger.exception(
            "Unexpected alert event error; message left pending for retry",
            extra={"message_id": _decode(message_id)},
        )
        return OUTCOME_FAILED

    if outcome == OUTCOME_STORED:
        ALERT_EVENTS_STORED_TOTAL.inc()
    else:
        ALERT_EVENTS_SKIPPED_TOTAL.labels(reason=outcome).inc()

    try:
        await redis.xack(stream, group, message_id)
    except Exception:
        # ANY ack failure (connection gone, unknown group, timeout) is logged
        # and counted, never propagated: an exception here would escape the
        # consumer loop and leave the task dead while the gauge still reads 1.
        # The decision is already durable, but the entry is STILL pending, so
        # the outcome must be retryable: reporting success here would let the
        # pending pass re-read the same entry with no backoff (hot spin) while
        # new messages starve.
        ALERT_EVENTS_ACK_ERRORS_TOTAL.inc()
        logger.error(
            "XACK failed for an alert event message",
            extra={
                "message_id": _decode(message_id),
                "stream": stream,
                "group": group,
                "outcome": outcome,
            },
        )
        return OUTCOME_ACK_FAILED
    return outcome


def _entries_of(messages: Any) -> list[tuple[Any, Any]]:
    """Flatten an XREADGROUP reply into (message_id, fields) pairs.

    A reply for a group with nothing to read is ``[[stream, []]]``, not
    ``None``, so "did we get anything" has to look at the entries, not the
    outer list — which is what decides whether the pending pass or the
    new-messages pass is the one that produced work.
    """
    entries: list[tuple[Any, Any]] = []
    if not messages:
        return entries
    for _, message_list in messages:
        entries.extend((message_id, fields) for message_id, fields in message_list)
    return entries


async def _read_pass(
    redis: RedisStreamClient,
    stream: str,
    group: str,
    consumer: str,
    read_id: str,
    count: int,
    block: int | None = None,
) -> list[tuple[Any, Any]]:
    """One XREADGROUP pass, flattened. ``read_id`` '>' = new, '0' = my pending."""
    messages = await redis.xreadgroup(
        group=group,
        consumer=consumer,
        streams={stream: read_id},
        count=count,
        block=block,
    )
    return _entries_of(messages)


def _remember(keys: set[str], order: deque[str], key: str, limit: int) -> None:
    """Remember a message id with a bound, so a long-lived consumer cannot
    accumulate ids forever. Redis's pending list is the source of truth; this
    in-process memory only has to survive recent redelivery (FIFO eviction).
    """
    if key in keys:
        return
    keys.add(key)
    order.append(key)
    while len(keys) > limit:
        keys.discard(order.popleft())


async def _process_with_retry(
    redis: RedisStreamClient,
    stream: str,
    group: str,
    message_id: Any,
    fields: Any,
    session_factory: Callable[[], Session],
    attempts: dict[str, int],
    given_up: set[str],
    given_up_order: deque[str],
    decided: set[str],
    decided_order: deque[str],
) -> str:
    """Decide one message, bounded so a failure cannot spin the consumer.

    A message that FAILED keeps its entry pending, which is how a transient
    database outage gets retried — but only up to MAX_DELIVERY_ATTEMPTS times.
    Past that the entry is acked and counted as discarded: unbounded lag on one
    poison pill is worse than a bounded, loud loss, and the counter means
    "we measured nothing" can never silently mean "we gave up".

    ACK_FAILED is also retryable: the event already has a verdict, but the entry
    is STILL in the group's pending list. Treating it as success would have the
    pending pass hand the same entry back with no backoff — a hot spin that
    starves new messages. Such an entry is re-acked and never re-decided (re-
    deciding would double-count stored/skipped), and after MAX_DELIVERY_ATTEMPTS
    it joins ``given_up`` so the loop moves on.
    """
    key = _decode(message_id) or "?"
    if key in given_up:
        try:
            await redis.xack(stream, group, message_id)
        except Exception:  # noqa: BLE001
            ALERT_EVENTS_ACK_ERRORS_TOTAL.inc()
        ALERT_EVENTS_REDRAWS_TOTAL.inc()
        return OUTCOME_FAILED

    attempt = attempts.get(key, 0) + 1
    attempts[key] = attempt
    if attempt > 1:
        ALERT_EVENTS_REDRAWS_TOTAL.inc()

    if key in decided:
        # Decided earlier, ack never took: retry the ack alone.
        try:
            await redis.xack(stream, group, message_id)
        except Exception:  # noqa: BLE001
            ALERT_EVENTS_ACK_ERRORS_TOTAL.inc()
        outcome = OUTCOME_ACK_FAILED
    else:
        try:
            outcome = await process_message(
                redis, stream, group, message_id, fields, session_factory
            )
        except Exception:  # noqa: BLE001 - the loop must never die on one message
            ALERT_EVENTS_FAILED_TOTAL.inc()
            logger.exception(
                "Alert event processing raised unexpectedly",
                extra={"message_id": key},
            )
            outcome = OUTCOME_FAILED
        if outcome != OUTCOME_FAILED:
            # The EVENT now has a verdict; only the ack may still be missing.
            _remember(decided, decided_order, key, DELIVERY_MEMORY)

    if outcome not in (OUTCOME_FAILED, OUTCOME_ACK_FAILED):
        attempts.pop(key, None)
        return outcome

    if attempt >= MAX_DELIVERY_ATTEMPTS:
        try:
            await redis.xack(stream, group, message_id)
        except Exception:  # noqa: BLE001
            ALERT_EVENTS_ACK_ERRORS_TOTAL.inc()
            logger.error(
                "XACK of a discarded message failed", extra={"message_id": key}
            )
        ALERT_EVENTS_DISCARDED_TOTAL.inc()
        # Remembered, not forgotten: the entry must never be reprocessed or
        # re-counted just because the ack that should have removed it failed.
        _remember(given_up, given_up_order, key, DELIVERY_MEMORY)
        attempts.pop(key, None)
    return outcome


async def consume_loop(
    session_factory: Callable[[], Session],
    *,
    redis_url: str | None = None,
    stream: str | None = None,
    group: str | None = None,
    consumer_name: str | None = None,
) -> None:
    """Consume ``stream:alerts`` forever.

    Started from the API's startup hook (``main.py``). A Redis outage does NOT
    take the API down: the read fails, is logged and counted, and the loop
    retries after a backoff. That is a deliberate, observable trade — ``GET
    /alerts/recent`` keeps serving what is already durable, ``el72_alert_events_
    consumer_up`` goes to 0, and the entries stay pending, so "no new alerts"
    can never be read as "nothing happened" while the pipeline is down.
    """
    url = redis_url or os.getenv("REDIS_URL", REDIS_URL)
    stream_name = stream or ALERTS_STREAM
    group_name = group or CONSUMER_GROUP
    name = consumer_name or CONSUMER_NAME

    redis: RedisStreamClient | None = None
    attempts: dict[str, int] = {}
    given_up: set[str] = set()
    given_up_order: deque[str] = deque()
    decided: set[str] = set()
    decided_order: deque[str] = deque()
    try:
        while True:
            progressed = False
            try:
                if redis is None:
                    # Connected lazily, INSIDE the loop: a Redis outage at API
                    # startup must not take the API down — GET /alerts/recent still
                    # serves what is already durable — but it must be visible,
                    # which is what el72_alert_events_consumer_up = 0 is for.
                    redis = await RedisStreamClient.create(url)
                # ALWAYS create the consumer group before reading. Re-asserted
                # every pass: ensure_group swallows BUSYGROUP, and after a
                # reconnect a dropped group must never strand the pipeline.
                await redis.ensure_group(stream_name, group_name)

                # Pending entries are invisible to '>' forever, so the consumer
                # re-claims its OWN pending list first; only when that is empty
                # does it ask for new messages (which is where the blocking
                # read belongs).
                entries = await _read_pass(
                    redis, stream_name, group_name, name, "0", READ_COUNT
                )
                if not entries:
                    entries = await _read_pass(
                        redis,
                        stream_name,
                        group_name,
                        name,
                        ">",
                        READ_COUNT,
                        READ_BLOCK_MS,
                    )
                ALERT_EVENTS_CONSUMER_UP.set(1)
            except asyncio.CancelledError:
                ALERT_EVENTS_CONSUMER_UP.set(0)
                raise
            except Exception:
                ALERT_EVENTS_READ_ERRORS_TOTAL.inc()
                ALERT_EVENTS_CONSUMER_UP.set(0)
                logger.exception(
                    "Alert events read failed; retrying after backoff",
                    extra={"stream": stream_name, "group": group_name},
                )
                # The client is kept, not closed: RedisStreamClient is a process
                # singleton and redis.asyncio reconnects on the next command, while
                # a failed create() leaves the singleton empty for a fresh attempt.
                await asyncio.sleep(READ_BACKOFF_SECONDS)
                continue

            for message_id, fields in entries:
                outcome = await _process_with_retry(
                    redis,
                    stream_name,
                    group_name,
                    message_id,
                    fields,
                    session_factory,
                    attempts,
                    given_up,
                    given_up_order,
                    decided,
                    decided_order,
                )
                if outcome not in (OUTCOME_FAILED, OUTCOME_ACK_FAILED):
                    progressed = True

            if entries and not progressed:
                # The pending pass keeps handing back entries this consumer has
                # already decided about (typically an XACK that keeps failing);
                # pausing keeps that observable lag from becoming a hot spin.
                await asyncio.sleep(READ_BACKOFF_SECONDS)
    finally:
        # Dead-person guard in the other direction: whatever ends this task
        # (cancelled, or an error that escaped despite the guards above), the
        # gauge must not be left at 1 for a consumer that is no longer running.
        ALERT_EVENTS_CONSUMER_UP.set(0)
