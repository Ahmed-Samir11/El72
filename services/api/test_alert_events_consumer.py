"""Unit tests for the alert-events consumer (plans/p2 MS1).

Guards the stream-reliability contract, not just the happy path: the consumer
group is ensured before the first read, every message the consumer DECIDES
about is acked exactly once, a FAILURE is left pending rather than silently
lost, and hostile or meaningless payloads are skipped and counted instead of
crashing the feed.
"""

import asyncio
import json
import os
from datetime import datetime
from unittest.mock import AsyncMock

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.alert_events_consumer import (
    MAX_DELIVERY_ATTEMPTS,
    OUTCOME_DUPLICATE,
    OUTCOME_FAILED,
    OUTCOME_INVALID,
    OUTCOME_OWNER_MISMATCH,
    OUTCOME_STORED,
    OUTCOME_UNKNOWN_ITEM,
    OUTCOME_UNSUPPORTED,
    RedisStreamClient,
    consume_loop,
    parse_event,
    process_message,
    store_event,
)
from services.api.models import Alert, AlertEvent, User
from services.api.tracked_items_models import TrackedItem


class _Bundle:
    """Bundles the session factory with read-back and fixture helpers."""

    def __init__(self, factory, read_rows, add_user, add_item):
        self.factory = factory
        self.read_rows = read_rows
        self.add_user = add_user
        self.add_item = add_item


@pytest.fixture
def db():
    """Session factory for the consumer, plus helpers that read the rows back.

    ``store_event`` opens its OWN session (it must commit independently of its
    caller), so assertions use a fresh session on the same engine.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        User.__table__,
        Alert.__table__,
        AlertEvent.__table__,
        TrackedItem.__table__,
    ):
        table.create(bind=engine, checkfirst=True)
    factory = sessionmaker(bind=engine)

    def read_rows():
        with factory() as probe:
            return probe.execute(select(AlertEvent)).scalars().all()

    def add_user(phone):
        with factory() as session:
            user = User(phone=phone, password_hash="x", salt="y", tier="free")
            session.add(user)
            session.commit()
            return user.id

    def add_item(user_id, product_id):
        with factory() as session:
            item = TrackedItem(
                user_id=user_id, canonical_product_id=product_id, is_active=True
            )
            session.add(item)
            session.commit()
            return item.id

    return _Bundle(factory, read_rows, add_user, add_item)


def _event(**overrides) -> dict:
    """A payload shaped like services/scraper/alert_emitter.py emits.

    ``user_id`` is omitted by default: the consumer must not need it (ownership
    comes from tracked_items), and the mismatch tests state it explicitly.
    """
    payload = {
        "alert_type": "price_drop",
        "tracked_item_id": 1,
        "store_id": "amazon_eg",
        "canonical_product_id": "rtx-5060-compumarts",
        "url": "https://www.compumarts.com/product/rtx-5060",
        "new_price_usd": 260.0,
        "new_price_local": 8320.0,
        "currency": "EGP",
        "old_price_usd": 300.0,
        "target_price": None,
        "timestamp": "2026-10-29T09:00:00",
        "metadata": {"drop_percentage": 13.33},
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None}


# --- payload decoding --------------------------------------------------------


def test_parse_event_decodes_bytes_payload():
    fields = {"payload": json.dumps(_event()).encode()}
    assert parse_event(fields)["tracked_item_id"] == 1


def test_parse_event_refuses_hostile_or_empty_payloads():
    assert parse_event({"other": b"x"}) is None
    assert parse_event({"payload": b"not json"}) is None
    assert parse_event({"payload": b"[1, 2]"}) is None
    assert parse_event({b"payload": b"\xff\xfe"}) is None


# --- ownership, dedupe, hostile ids ------------------------------------------


def test_event_lands_for_the_owning_user_only(db):
    owner = db.add_user("+201000000001")
    other = db.add_user("+201000000002")
    item = db.add_item(owner, "rtx-5060-compumarts")
    db.add_item(other, "some-other-product")

    assert store_event(db.factory, _event(tracked_item_id=item)) == OUTCOME_STORED

    rows = db.read_rows()
    assert len(rows) == 1
    assert rows[0].user_id == owner
    assert rows[0].tracked_item_id == item
    assert rows[0].channel == "in_app"  # the only channel this build delivers
    assert rows[0].opened_at is None  # written, not yet seen


def test_same_day_duplicate_is_skipped(db):
    user = db.add_user("+201000000003")
    item = db.add_item(user, "tee-r219636")
    now = datetime(2026, 10, 29, 12, 0, 0)

    assert store_event(db.factory, _event(tracked_item_id=item), now=now)
    # The market jitters its price again the same day: one alert per item per
    # day, never a wall of identical cards.
    assert (
        store_event(
            db.factory,
            _event(tracked_item_id=item, new_price_local=8310.0),
            now=now,
        )
        == OUTCOME_DUPLICATE
    )
    # A different event type for the same item is a different fact.
    assert (
        store_event(
            db.factory,
            _event(tracked_item_id=item, alert_type="back_in_stock", metadata={}),
            now=now,
        )
        == OUTCOME_STORED
    )
    assert len(db.read_rows()) == 2


def test_next_day_gets_its_own_alert(db):
    user = db.add_user("+201000000004")
    item = db.add_item(user, "monitor-xg27acmeg-g")

    assert (
        store_event(
            db.factory,
            _event(tracked_item_id=item),
            now=datetime(2026, 10, 28, 23, 0, 0),
        )
        == OUTCOME_STORED
    )
    assert (
        store_event(
            db.factory,
            _event(tracked_item_id=item),
            now=datetime(2026, 10, 29, 1, 0, 0),
        )
        == OUTCOME_STORED
    )
    assert len(db.read_rows()) == 2


def test_unknown_tracked_item_is_skipped_not_crashed(db):
    db.add_user("+201000000005")
    assert store_event(db.factory, _event(tracked_item_id=4242)) == OUTCOME_UNKNOWN_ITEM
    assert db.read_rows() == []


def test_payload_user_id_cannot_reassign_ownership(db):
    """The OWNING user comes from tracked_items, never from the payload."""
    owner = db.add_user("+201000000006")
    item = db.add_item(owner, "rtx-5060-el-badr")

    assert (
        store_event(db.factory, _event(tracked_item_id=item, user_id=9999))
        == OUTCOME_OWNER_MISMATCH
    )
    assert db.read_rows() == []


def test_unsupported_event_type_is_skipped(db):
    user = db.add_user("+201000000007")
    item = db.add_item(user, "tee")
    for alert_type in ("scrape_failure", "", "DROP", "price drop"):
        assert (
            store_event(
                db.factory,
                _event(tracked_item_id=item, alert_type=alert_type),
            )
            == OUTCOME_UNSUPPORTED
        )
    assert db.read_rows() == []


def test_missing_or_injected_item_id_is_invalid(db):
    db.add_user("+201000000008")
    assert store_event(db.factory, None) == OUTCOME_INVALID
    assert store_event(db.factory, _event(tracked_item_id=None)) == OUTCOME_INVALID
    assert (
        store_event(db.factory, _event(tracked_item_id="1; DROP TABLE users"))
        == OUTCOME_INVALID
    )
    assert db.read_rows() == []


# --- the numbers a card is allowed to show ---------------------------------


def test_local_egp_price_and_metadata_delta_land_as_claimed(db):
    user = db.add_user("+201000000009")
    item = db.add_item(user, "rtx-5060-compumarts")
    store_event(
        db.factory, _event(tracked_item_id=item), now=datetime(2026, 10, 29, 12, 0, 0)
    )
    (row,) = db.read_rows()
    assert float(row.price_egp) == 8320.0
    assert float(row.discount_pct) == 13.33
    # old_price_usd 300 is a USD reading; the column and the card are EGP.
    assert float(row.reference_price_egp) == pytest.approx(300 / 0.032)


def test_threshold_reference_is_the_users_target(db):
    user = db.add_user("+201000000010")
    item = db.add_item(user, "tee-r219636")
    store_event(
        db.factory,
        _event(
            tracked_item_id=item,
            alert_type="threshold_crossed",
            target_price=45.0,
            metadata={"below_target_by": 1.2},
        ),
        now=datetime(2026, 10, 29, 12, 0, 0),
    )
    (row,) = db.read_rows()
    assert float(row.reference_price_egp) == pytest.approx(45 / 0.032)


def test_discount_is_computed_when_the_emitter_did_not(db):
    user = db.add_user("+201000000011")
    item = db.add_item(user, "tee")
    store_event(
        db.factory,
        _event(
            tracked_item_id=item,
            new_price_local=8000.0,
            old_price_usd=320.0,  # -> 10000 EGP reference
            metadata={},
        ),
        now=datetime(2026, 10, 29, 12, 0, 0),
    )
    (row,) = db.read_rows()
    assert float(row.discount_pct) == pytest.approx(20.0)


def test_wild_price_degrades_to_null_but_the_event_still_lands(db):
    user = db.add_user("+201000000012")
    item = db.add_item(user, "tee")
    store_event(
        db.factory,
        _event(tracked_item_id=item, new_price_local=1e18, metadata={}),
        now=datetime(2026, 10, 29, 12, 0, 0),
    )
    (row,) = db.read_rows()
    assert row.price_egp is None  # NUMERIC(12,2) cannot hold it: no bogus card


def test_discount_is_bounded_to_a_real_claim(db):
    """A "120% discount" or a negative one is a data error, not a deal."""
    user = db.add_user("+201000000013")
    day = datetime(2026, 10, 29, 12, 0, 0)
    for claimed, expected, product in (
        (140.0, 100.0, "tee-a"),
        (-5.0, 0.0, "tee-b"),
    ):
        item = db.add_item(user, product)
        store_event(
            db.factory,
            _event(
                tracked_item_id=item,
                new_price_local=1000.0,
                metadata={"drop_percentage": claimed},
            ),
            now=day,
        )
        row = db.read_rows()[-1]
        assert float(row.discount_pct) == expected


def test_junk_url_and_markup_category_are_dropped(db):
    user = db.add_user("+201000000014")
    item = db.add_item(user, "tee")
    store_event(
        db.factory,
        _event(
            tracked_item_id=item,
            url="javascript:alert(1)",
            metadata={"category": "<img src=x>evil"},
        ),
        now=datetime(2026, 10, 29, 12, 0, 0),
    )
    (row,) = db.read_rows()
    assert row.url is None
    assert row.category is None


def test_category_is_filled_from_the_users_tracker(db):
    user = db.add_user("+201000000015")
    item = db.add_item(user, "tee-r219636")
    with db.factory() as session:
        session.add(
            Alert(user_id=user, sku="tee-r219636", category="Apparel", target_url="x")
        )
        session.commit()

    store_event(
        db.factory,
        _event(
            tracked_item_id=item,
            canonical_product_id="tee-r219636",
            metadata={},
        ),
        now=datetime(2026, 10, 29, 12, 0, 0),
    )
    (row,) = db.read_rows()
    assert row.category == "Apparel"


# --- stream reliability -----------------------------------------------------


def test_process_message_acks_every_decided_message(db):
    """Asyncio is driven explicitly: the suite does not depend on a plugin."""
    user = db.add_user("+201000000017")
    item = db.add_item(user, "rtx-5060-compumarts")

    async def scenario():
        redis = AsyncMock()
        redis.xack = AsyncMock(return_value=1)
        fields = {"payload": json.dumps(_event(tracked_item_id=item)).encode()}
        await process_message(
            redis, "stream:alerts", "cg_alerts_api", "1-0", fields, db.factory
        )
        return redis

    redis = asyncio.run(scenario())
    assert redis.xack.await_count == 1
    assert len(db.read_rows()) == 1


def test_undecodable_message_is_still_acked(db):
    """A message the consumer can never make a row from must not pin the feed."""

    async def scenario():
        redis = AsyncMock()
        redis.xack = AsyncMock(return_value=1)
        outcome = await process_message(
            redis,
            "stream:alerts",
            "cg_alerts_api",
            "1-0",
            {"payload": b"{"},
            db.factory,
        )
        return outcome, redis

    outcome, redis = asyncio.run(scenario())
    assert outcome == OUTCOME_INVALID
    assert redis.xack.await_count == 1


def test_failed_write_is_not_acked(db):
    """A pending entry is observable lag; an acked one is lost data."""

    def broken_factory():
        raise RuntimeError("database gone")

    async def scenario():
        redis = AsyncMock()
        redis.xack = AsyncMock(return_value=1)
        outcome = await process_message(
            redis,
            "stream:alerts",
            "cg_alerts_api",
            "1-0",
            {"payload": json.dumps(_event()).encode()},
            broken_factory,
        )
        return outcome, redis

    outcome, redis = asyncio.run(scenario())
    assert outcome == OUTCOME_FAILED
    assert redis.xack.await_count == 0


def test_consumer_ensures_group_before_reading_then_acks_batch(db, monkeypatch):
    """The loop's contract: connect -> ensure_group -> read -> ack per message."""
    user = db.add_user("+201000000016")
    item = db.add_item(user, "rtx-5060-compumarts")
    payload = json.dumps(_event(tracked_item_id=item)).encode()

    redis = AsyncMock()
    redis.xreadgroup = AsyncMock(
        side_effect=[
            [("stream:alerts", [("1-0", {"payload": payload})])],
            asyncio.CancelledError(),
        ]
    )
    redis.xack = AsyncMock(return_value=1)
    monkeypatch.setattr(RedisStreamClient, "create", AsyncMock(return_value=redis))

    async def scenario():
        return await asyncio.gather(
            consume_loop(db.factory, redis_url="redis://unused"),
            return_exceptions=True,
        )

    results = asyncio.run(scenario())
    assert isinstance(results[0], asyncio.CancelledError)
    assert redis.ensure_group.await_count >= 1
    assert redis.xack.await_count == 1
    assert len(db.read_rows()) == 1


# --- hostile payload shapes -------------------------------------------------


def test_non_object_metadata_never_crashes_the_write(db):
    """metadata is display context; a hostile shape must not lose the event.

    The old ``(event.get('metadata') or {}).get(...)`` raised AttributeError on
    a list/string/number, which left the message pending forever.
    """
    user = db.add_user("+201000000021")
    day = datetime(2026, 10, 29, 12, 0, 0)

    for index, metadata in enumerate(
        ([], "drop", 7, None, {"drop_percentage": "lots"})
    ):
        product = f"tee-{index}"
        owned = db.add_item(user, product)
        assert (
            store_event(
                db.factory,
                _event(tracked_item_id=owned, metadata=metadata),
                now=day,
            )
            == OUTCOME_STORED
        ), f"metadata shape {type(metadata)} broke the write"
    assert len(db.read_rows()) == 5


def test_fractional_and_non_numeric_item_ids_are_invalid(db):
    user = db.add_user("+201000000022")
    db.add_item(user, "tee")
    for bad in ("1.5", 1.5, "abc", [], True):
        assert store_event(db.factory, _event(tracked_item_id=bad)) == OUTCOME_INVALID
    assert db.read_rows() == []


def test_oversized_url_is_dropped_but_the_event_lands(db):
    user = db.add_user("+201000000023")
    item = db.add_item(user, "tee")
    store_event(
        db.factory,
        _event(tracked_item_id=item, url="https://x.example/" + "a" * 4096),
        now=datetime(2026, 10, 29, 12, 0, 0),
    )
    (row,) = db.read_rows()
    assert row.url is None


def test_discount_stays_null_without_a_reference_price(db):
    """ "The price changed" is a fact; "it fell N%" is not claimable then."""
    user = db.add_user("+201000000024")
    item = db.add_item(user, "tee")
    store_event(
        db.factory,
        _event(
            tracked_item_id=item,
            old_price_usd=None,
            target_price=None,
            metadata={},
        ),
        now=datetime(2026, 10, 29, 12, 0, 0),
    )
    (row,) = db.read_rows()
    assert row.price_egp is not None
    assert row.reference_price_egp is None
    assert row.discount_pct is None


def test_payload_user_id_matching_the_owner_is_accepted(db):
    """A truthful payload is not punished for naming the owner it agrees with."""
    user = db.add_user("+201000000025")
    item = db.add_item(user, "tee-r219636")
    assert (
        store_event(db.factory, _event(tracked_item_id=item, user_id=user))
        == OUTCOME_STORED
    )
    (row,) = db.read_rows()
    assert row.user_id == user


def test_dedupe_uses_event_time_across_midnight(db):
    """Two price drops either side of midnight are two days, not one.

    Processing-time dedupe would fold them together whenever the backlog
    drained after 00:00, rewriting what the user would have seen that day.
    """
    user = db.add_user("+201000000026")
    item = db.add_item(user, "tee")
    evening = _event(tracked_item_id=item, timestamp="2026-10-28T23:59:00")
    morning = _event(tracked_item_id=item, timestamp="2026-10-29T00:01:00")

    assert store_event(db.factory, evening) == OUTCOME_STORED
    assert store_event(db.factory, morning) == OUTCOME_STORED
    rows = db.read_rows()
    assert len(rows) == 2
    created = sorted(float(row.created_at.timestamp()) for row in rows)
    assert created[0] < created[-1]


# --- consumer reliability under failure --------------------------------------


class _FailingRedis:
    """A Redis whose pending list keeps handing back the same broken entry.

    Mirrors what XREADGROUP really does: a message the consumer failed on stays
    pending for this consumer and is re-delivered on the next '0' read, until
    something acks it.
    """

    def __init__(self, entry):
        self.entry = entry
        self.acked = []
        self.ensure_group_calls = 0
        self.pending_reads = 0

    async def ensure_group(self, stream, group, mkstream=True):
        self.ensure_group_calls += 1

    async def xreadgroup(self, *, group, consumer, streams, count, block=None):
        (read_id,) = list(streams.values())
        if read_id == "0":
            self.pending_reads += 1
            # A real pending list stops returning an entry once it is acked;
            # modelling that is what keeps this test from spinning forever.
            if self.acked:
                return [[b"stream:alerts", []]]
            return [[b"stream:alerts", [self.entry]]]
        raise asyncio.CancelledError

    async def xack(self, stream, group, message_id):
        self.acked.append(message_id)
        return 1


def test_broken_write_is_reclaimed_then_discarded_and_the_gauge_drops(db, monkeypatch):
    """A permanently failing write must not pin the feed, and the loop must end
    with the gauge at 0 rather than a confident 1 for a dead consumer.
    """
    payload = json.dumps(_event(tracked_item_id=1)).encode()
    redis = _FailingRedis(("1-0", {"payload": payload}))
    monkeypatch.setattr(RedisStreamClient, "create", AsyncMock(return_value=redis))
    # The retry backoff is real production behaviour (no hot spin on a poison
    # pill); dialled to zero here so the bounded-retry contract is asserted in
    # milliseconds instead of 15 seconds of sleep.
    monkeypatch.setattr("services.api.alert_events_consumer.READ_BACKOFF_SECONDS", 0.0)

    def broken_factory():
        raise RuntimeError("database gone")

    async def scenario():
        return await asyncio.gather(
            consume_loop(broken_factory, redis_url="redis://unused"),
            return_exceptions=True,
        )

    results = asyncio.run(scenario())
    assert isinstance(results[0], asyncio.CancelledError)
    # Re-claimed exactly MAX_DELIVERY_ATTEMPTS times, acked as discarded, plus
    # the one further pending read that then finds the list empty.
    assert redis.pending_reads == MAX_DELIVERY_ATTEMPTS + 1
    assert redis.acked == ["1-0"]
    assert redis.ensure_group_calls >= 1
    gauge = REGISTRY.get_sample_value("el72_alert_events_consumer_up")
    assert gauge == 0, "a finished consumer task must not leave the gauge at 1"
    assert db.read_rows() == []


def test_ack_failure_does_not_kill_the_loop(db):
    """An ack error leaves the entry pending; it must never end the task."""

    async def scenario():
        redis = AsyncMock()
        redis.xack = AsyncMock(side_effect=ConnectionError("redis gone"))
        user = db.add_user("+201000000027")
        item = db.add_item(user, "rtx-5060-compumarts")
        fields = {"payload": json.dumps(_event(tracked_item_id=item)).encode()}
        outcome = await process_message(
            redis, "stream:alerts", "cg_alerts_api", "1-0", fields, db.factory
        )
        return outcome

    assert asyncio.run(scenario()) == OUTCOME_STORED
    assert len(db.read_rows()) == 1
