"""First-party event ingest tests (plans/p4 MS1).

The contract: a batch is validated row by row against the taxonomy; an
unknown event name fails the whole batch, a badly shaped row is skipped and
counted; the user id comes only from the token; no phone-shaped value is ever
stored; and the schema's allowlist cannot drift from the code's.
"""

import atexit
import os
import re
from pathlib import Path

# Same isolation pattern as test_affiliate.py: main's module-level engine gets
# a pid-keyed SQLite file, while the routers talk to the StaticPool engines
# below through dependency overrides.
os.environ["DATABASE_URL"] = f"sqlite:///./test_events_{os.getpid()}.db"
os.environ["SECRET_KEY"] = "test-events-secret"
os.environ.setdefault("APP_ENV", "dev")

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api import events as events_rules
from services.api.dependencies import (
    create_access_token,
    get_db,
    get_optional_timescale_db,
)
from services.api.events import EVENT_TYPES, EventRejected, validate_event
from services.api.main import app
from services.api.models import User
from services.api.routers import events as events_router

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL = REPO_ROOT / "infra" / "sql" / "schema" / "timescaledb.sql"
MIGRATION_SQL = (
    REPO_ROOT / "infra" / "sql" / "migrations" / "timescaledb" / "0003_app_events.sql"
)

# A SQLite stand-in for the hypertable: same columns, server-side defaults for
# the two values the API never sends (id and ts).
APP_EVENTS_DDL = """
CREATE TABLE app_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id TEXT,
    session_id TEXT NOT NULL,
    event TEXT NOT NULL,
    sku TEXT, store_id TEXT, category TEXT, source TEXT, channel TEXT,
    product_id TEXT, deal_id TEXT, item_id TEXT, event_id TEXT,
    properties TEXT
)
"""

SESSION = "a1b2c3d4e5f60718293a4b5c6d7e8f90"


def _remove_db_file() -> None:
    name = os.environ["DATABASE_URL"].split("///", 1)[-1].lstrip("./")
    try:
        os.remove(name)
    except OSError:
        pass


atexit.register(_remove_db_file)


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture
def pg_engine():
    engine = _engine()
    from services.api.models import Base

    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def ts_engine():
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(text(APP_EVENTS_DDL))
    yield engine
    engine.dispose()


def _override(engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def dependency():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    return dependency


@pytest.fixture
def client(pg_engine, ts_engine):
    app.dependency_overrides[get_db] = _override(pg_engine)
    app.dependency_overrides[get_optional_timescale_db] = _override(ts_engine)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _stored(ts_engine):
    with ts_engine.connect() as conn:
        return [
            dict(r._mapping) for r in conn.execute(text("SELECT * FROM app_events"))
        ]


def _token(pg_engine, phone="+201000000001"):
    Session = sessionmaker(bind=pg_engine)
    db = Session()
    user = User(phone=phone, password_hash="x", salt="y", tier="free")
    db.add(user)
    db.commit()
    db.refresh(user)
    user_id = user.id
    db.close()
    from services.api.dependencies import SECRET_KEY

    return create_access_token({"sub": phone}, secret_key=SECRET_KEY), user_id


def _event(**overrides):
    row = {"event": "search", "session_id": SESSION}
    row.update(overrides)
    return row


def _rejected(reason):
    value = REGISTRY.get_sample_value("el72_events_rejected_total", {"reason": reason})
    return value or 0.0


# --- schema and taxonomy ------------------------------------------------------


def _app_events_block(path):
    body = path.read_text(encoding="utf-8")
    start = body.index("CREATE TABLE IF NOT EXISTS app_events")
    return body[start:].strip()


def test_schema_allowlist_matches_the_code_taxonomy():
    block = _app_events_block(SCHEMA_SQL)
    check = re.search(r"CHECK \(event IN \((.*?)\)\)", block, re.S)
    assert check, "app_events must pin the taxonomy with a CHECK constraint"
    in_schema = set(re.findall(r"'([a-z_]+)'", check.group(1)))
    assert in_schema == set(EVENT_TYPES)


def test_migration_and_canonical_schema_define_the_same_table():
    assert _app_events_block(SCHEMA_SQL) == _app_events_block(MIGRATION_SQL)


def test_the_hypertable_key_includes_the_time_column_and_retention_is_set():
    block = _app_events_block(SCHEMA_SQL)
    assert "PRIMARY KEY (id, ts)" in block
    assert "create_hypertable('app_events', 'ts')" in block
    assert "add_retention_policy('app_events', INTERVAL '180 days', true)" in block


# --- row validation -------------------------------------------------------------


def test_a_valid_row_keeps_only_known_columns():
    row = validate_event(
        _event(
            sku="ABC123",
            store_id="amazon_eg",
            category="Laptops",
            source="Deal_Feed",
            channel="in_app",
            properties={"query_length": 12, "matched": True},
        )
    )
    assert row["source"] == "deal_feed"
    assert row["properties"] == {"query_length": 12, "matched": True}
    assert "user_id" not in row and "ts" not in row


@pytest.mark.parametrize(
    "raw",
    [
        "not an object",
        {"session_id": SESSION},
        _event(session_id=None),
        _event(session_id="has spaces"),
        _event(user_id="7"),
        _event(query="gaming laptop"),
        _event(sku="https://evil.example/x"),
        _event(sku="x" * 129),
        _event(store_id=5),
        _event(event_id="y" * 65),
        _event(properties=[1, 2]),
        _event(properties={"nested": {"a": 1}}),
        _event(properties={"Bad-Key": 1}),
        _event(properties={f"k{i}": i for i in range(21)}),
        _event(properties={"long": "z" * 201}),
        _event(properties={f"k{i}": "v" * 60 for i in range(20)}),
        _event(properties={"nan": float("nan")}),
    ],
)
def test_badly_shaped_rows_are_refused_as_malformed(raw):
    with pytest.raises(EventRejected) as exc:
        validate_event(raw)
    assert exc.value.reason == events_rules.REASON_MALFORMED


@pytest.mark.parametrize(
    "raw",
    [
        _event(properties={"note": "call me on 01012345678"}),
        _event(properties={"note": "+20 101 234 5678"}),
        _event(sku="201012345678"),
        _event(category="0020-10-1234-5678"),
    ],
)
def test_phone_shaped_values_are_refused_as_pii(raw):
    with pytest.raises(EventRejected) as exc:
        validate_event(raw)
    assert exc.value.reason == events_rules.REASON_PII


@pytest.mark.parametrize(
    "raw",
    [
        _event(properties={"query": "gaming laptop"}),
        _event(properties={"note": "<b>hi</b>"}),
        _event(properties={"phone": 1012345678}),
        _event(properties={"big": -(10**9)}),
        _event(session_id="01012345678"),
        _event(event_id="20101234567890"),
    ],
)
def test_free_text_large_numbers_and_digit_only_tokens_are_refused(raw):
    # Free text has no place in properties, a number this large is an
    # identifier rather than a count, and a digit-only "random" token is what a
    # phone number looks like when it lands in an id field.
    with pytest.raises(EventRejected) as exc:
        validate_event(raw)
    assert exc.value.reason == events_rules.REASON_MALFORMED


@pytest.mark.parametrize("value", ["010.1234.5678", "010/1234/5678", "010,1234,5678"])
def test_common_phone_separators_do_not_hide_a_number(value):
    with pytest.raises(EventRejected) as exc:
        validate_event(_event(properties={"note": value}))
    assert exc.value.reason == events_rules.REASON_PII


@pytest.mark.parametrize("channel", [[], {}, ["in_app"], 5])
def test_a_non_string_channel_degrades_to_null_instead_of_crashing(channel):
    assert validate_event(_event(channel=channel))["channel"] is None


def test_random_client_tokens_are_never_mistaken_for_phones():
    # A random session or event id can contain a phone-shaped digit run.
    row = validate_event(
        _event(session_id="ab01012345678cd", event_id="ff01012345678ee")
    )
    assert row["session_id"] == "ab01012345678cd"


def test_long_numeric_product_ids_are_not_phones():
    assert validate_event(_event(sku="1012345678901234"))["sku"] == "1012345678901234"


def test_bad_context_labels_degrade_to_null_instead_of_costing_the_event():
    row = validate_event(
        _event(category="<script>", source="has space", channel="carrier_pigeon")
    )
    assert row["category"] is None and row["source"] is None
    assert row["channel"] is None


# --- the endpoint ----------------------------------------------------------------


def test_an_anonymous_batch_is_stored_without_a_user(client, ts_engine):
    resp = client.post(
        "/events", json={"events": [_event(), _event(event="product_view")]}
    )
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 2, "rejected": 0}
    rows = _stored(ts_engine)
    assert [r["event"] for r in rows] == ["search", "product_view"]
    assert all(r["user_id"] is None and r["session_id"] == SESSION for r in rows)


def test_a_signed_in_batch_carries_the_user_from_the_token(
    client, pg_engine, ts_engine
):
    token, user_id = _token(pg_engine)
    resp = client.post(
        "/events",
        json={"events": [_event(event="track_created", item_id="42")]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202
    (row,) = _stored(ts_engine)
    assert row["user_id"] == str(user_id)
    assert row["item_id"] == "42"


def test_an_invalid_token_is_an_anonymous_session_not_an_error(client, ts_engine):
    resp = client.post(
        "/events",
        json={"events": [_event()]},
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert resp.status_code == 202
    assert _stored(ts_engine)[0]["user_id"] is None


def test_one_bad_row_is_skipped_and_counted_while_the_rest_are_stored(
    client, ts_engine
):
    before = _rejected(events_rules.REASON_MALFORMED)
    resp = client.post(
        "/events",
        json={"events": [_event(), _event(user_id="999"), _event(event="limit_hit")]},
    )
    assert resp.json() == {"accepted": 2, "rejected": 1}
    assert _rejected(events_rules.REASON_MALFORMED) == before + 1
    assert all(r["user_id"] is None for r in _stored(ts_engine))


def test_a_phone_number_is_never_stored(client, ts_engine):
    before = _rejected(events_rules.REASON_PII)
    resp = client.post(
        "/events",
        json={"events": [_event(properties={"note": "01112345678"}), _event()]},
    )
    assert resp.json() == {"accepted": 1, "rejected": 1}
    assert _rejected(events_rules.REASON_PII) == before + 1
    assert "01112345678" not in str(_stored(ts_engine))


def test_properties_are_stored_as_json(client, ts_engine):
    client.post("/events", json={"events": [_event(properties={"results": 3})]})
    assert _stored(ts_engine)[0]["properties"] == '{"results": 3}'


def test_an_unknown_event_name_fails_the_whole_batch(client, ts_engine):
    resp = client.post(
        "/events", json={"events": [_event(), _event(event="screen_scrolled")]}
    )
    assert resp.status_code == 400
    assert "screen_scrolled" in resp.json()["detail"]
    assert _stored(ts_engine) == []


def test_more_than_fifty_events_is_too_large(client, ts_engine):
    resp = client.post("/events", json={"events": [_event()] * 51})
    assert resp.status_code == 413
    assert _stored(ts_engine) == []


def test_an_oversized_body_is_too_large(client, ts_engine):
    padding = "x" * (events_rules.MAX_BODY_BYTES + 1)
    resp = client.post(
        "/events",
        content=f'{{"events": [], "pad": "{padding}"}}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 413


@pytest.mark.parametrize("body", ["not json", "[]", '{"events": {}}'])
def test_a_body_that_is_not_a_batch_is_a_bad_request(client, body):
    resp = client.post(
        "/events", content=body, headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 400


def test_an_empty_batch_is_accepted_as_nothing(client, ts_engine):
    resp = client.post("/events", json={"events": []})
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 0, "rejected": 0}


def test_without_an_event_store_nothing_is_pretended(client):
    def no_store():
        yield None

    app.dependency_overrides[get_optional_timescale_db] = no_store
    resp = client.post("/events", json={"events": [_event()]})
    assert resp.status_code == 503


def test_a_failed_write_is_a_503_and_counts_as_store_unavailable(client, ts_engine):
    with ts_engine.begin() as conn:
        conn.execute(text("DROP TABLE app_events"))
    before = _rejected(events_rules.REASON_STORE_UNAVAILABLE)

    resp = client.post("/events", json={"events": [_event(), _event()]})

    assert resp.status_code == 503
    assert _rejected(events_rules.REASON_STORE_UNAVAILABLE) == before + 2


def test_a_row_with_a_list_for_channel_is_stored_not_a_server_error(client, ts_engine):
    resp = client.post("/events", json={"events": [_event(channel={})]})
    assert resp.status_code == 202
    assert _stored(ts_engine)[0]["channel"] is None


def test_the_rate_limit_key_never_carries_the_phone_number(pg_engine):
    from starlette.requests import Request

    phone = "+201000000009"
    token, _ = _token(pg_engine, phone)
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
            "client": ("10.0.0.1", 1234),
        }
    )
    key = events_router._events_rate_key(request)
    assert key.startswith("user:")
    assert phone not in key and phone.lstrip("+") not in key


def test_the_ingest_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(events_router, "EVENTS_RATE_LIMIT", "2/minute")
    for _ in range(2):
        assert client.post("/events", json={"events": []}).status_code == 202
    assert client.post("/events", json={"events": []}).status_code == 429


def test_the_response_never_echoes_event_content(client):
    resp = client.post(
        "/events", json={"events": [_event(sku="SECRETSKU1", category="Laptops")]}
    )
    assert "SECRETSKU1" not in resp.text and "Laptops" not in resp.text
