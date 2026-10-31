"""Live TimescaleDB checks for the app_events table (plans/p4 MS1).

test_events.py runs the ingest path against a SQLite stand-in, and
services/common/test_migration_files.py only parses the SQL, so neither shows
that create_hypertable, the retention policy, the event CHECK or the JSONB cast
work on the real engine. These tests do, against a database that
scripts/db-bootstrap.sh has just set up. The bootstrap applies the app_events
block twice (schema file, then migration 0003), so its success already shows
the block can be re-run.

They skip unless EL72_LIVE_TIMESCALE_URL is set. It is its own name, not
TIMESCALE_URL, so a developer's real database is never written to by accident.
The CI db-bootstrap job also sets EL72_LIVE_DB_REQUIRED=1, which turns the skip
into a failure so a missing URL cannot pass the job silently.
"""

import atexit
import os
import re
import uuid

# Same isolation pattern as test_events.py: main's module-level engine gets a
# pid-keyed SQLite file; the routers reach the live database only through the
# dependency override below.
os.environ["DATABASE_URL"] = f"sqlite:///./test_events_live_{os.getpid()}.db"
os.environ["SECRET_KEY"] = "test-events-live-secret"
os.environ.setdefault("APP_ENV", "dev")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from services.api.dependencies import get_db, get_optional_timescale_db
from services.api.events import EVENT_TYPES
from services.api.main import app
from services.api.models import Base
from services.api.test_events import MIGRATION_SQL, _engine, _override


def _remove_db_file() -> None:
    name = os.environ["DATABASE_URL"].split("///", 1)[-1].lstrip("./")
    try:
        os.remove(name)
    except OSError:
        pass


atexit.register(_remove_db_file)

LIVE_URL = os.getenv("EL72_LIVE_TIMESCALE_URL")

if not LIVE_URL and os.getenv("EL72_LIVE_DB_REQUIRED") == "1":
    raise RuntimeError("EL72_LIVE_DB_REQUIRED=1 but EL72_LIVE_TIMESCALE_URL is unset")

pytestmark = pytest.mark.skipif(
    not LIVE_URL, reason="EL72_LIVE_TIMESCALE_URL is not set"
)


@pytest.fixture
def pg_engine():
    # Only get_optional_user touches it, and no test sends a token.
    engine = _engine()
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def live_engine():
    engine = create_engine(LIVE_URL)
    yield engine
    engine.dispose()


def _session_id() -> str:
    # Unique per test so cleanup only touches this test's rows.
    return f"live{uuid.uuid4().hex}"


def test_app_events_is_a_hypertable(live_engine):
    with live_engine.connect() as conn:
        found = conn.execute(
            text(
                "SELECT count(*) FROM timescaledb_information.hypertables "
                "WHERE hypertable_name = 'app_events'"
            )
        ).scalar_one()
    assert found == 1


def test_retention_policy_matches_the_migration(live_engine):
    declared = re.search(
        r"add_retention_policy\(\s*'app_events',\s*INTERVAL\s*'([^']+)'",
        MIGRATION_SQL.read_text(encoding="utf-8"),
    )
    assert declared, "0003_app_events.sql no longer declares a retention interval"

    with live_engine.connect() as conn:
        jobs = (
            conn.execute(
                text(
                    "SELECT (config->>'drop_after')::interval "
                    "= CAST(:want AS interval) "
                    "FROM timescaledb_information.jobs "
                    "WHERE proc_name = 'policy_retention' "
                    "AND hypertable_name = 'app_events'"
                ),
                {"want": declared.group(1)},
            )
            .scalars()
            .all()
        )
    # Exactly one job: re-running the block must not stack a second policy.
    assert jobs == [True]


def test_event_check_accepts_exactly_the_code_taxonomy(live_engine):
    session_id = _session_id()
    insert = text("INSERT INTO app_events (session_id, event) VALUES (:sid, :event)")
    with live_engine.connect() as conn:
        tx = conn.begin()
        try:
            for event in sorted(EVENT_TYPES):
                conn.execute(insert, {"sid": session_id, "event": event})
            with pytest.raises(IntegrityError, match="app_events_event_allowlist"):
                with conn.begin_nested():
                    conn.execute(insert, {"sid": session_id, "event": "not_an_event"})
        finally:
            tx.rollback()


def test_ingest_writes_jsonb_rows_to_the_hypertable(live_engine, pg_engine):
    session_id = _session_id()
    app.dependency_overrides[get_db] = _override(pg_engine)
    app.dependency_overrides[get_optional_timescale_db] = _override(live_engine)
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/events",
                json={
                    "events": [
                        {
                            "event": "search",
                            "session_id": session_id,
                            "properties": {"results": 7, "lang": "ar"},
                        },
                        {
                            "event": "error_observed",
                            "session_id": session_id,
                            "properties": {"reason": "network_error"},
                        },
                    ]
                },
            )
        assert resp.status_code == 202
        assert resp.json() == {"accepted": 2, "rejected": 0}

        with live_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT event, jsonb_typeof(properties) AS kind, "
                    "properties->'results' AS results, user_id, "
                    "ts > NOW() - INTERVAL '5 minutes' AS fresh "
                    "FROM app_events WHERE session_id = :sid ORDER BY event"
                ),
                {"sid": session_id},
            ).all()
        assert [(r.event, r.kind) for r in rows] == [
            ("error_observed", "object"),
            ("search", "object"),
        ]
        # Stored as a JSON number, not as a string inside a JSON string.
        assert rows[1].results == 7
        assert all(r.user_id is None and r.fresh for r in rows)
    finally:
        app.dependency_overrides.clear()
        with live_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM app_events WHERE session_id = :sid"),
                {"sid": session_id},
            )
