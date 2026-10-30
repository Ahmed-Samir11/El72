"""Fair-use limits: mode matrix, per-user cap, creation rate window, /usage/limits.

The mode matrix is pinned deliberately: the same endpoint must answer 409/429
under ``fair_use`` (the shipped default), 402 under the legacy ``on`` ledger,
and never refuse under ``off``. A change that quietly weakens one of those
three columns shows up here.
"""

import math
import os
from datetime import datetime, timedelta, timezone
from itertools import count
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api import credits as credits_module
from services.api import usage_limits
from services.api.dependencies import get_current_user, get_db
from services.api.models import Base as ApiBase
from services.api.models import User
from services.api.tracked_items_models import TrackedItem
from services.api.usage_limits import CREDITS_ENFORCEMENT_ENV


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ApiBase.metadata.create_all(bind=engine)
    TrackedItem.__table__.create(bind=engine, checkfirst=True)

    Session = sessionmaker(bind=engine)
    session = Session()
    users = [
        session.query(User).filter(User.phone == phone).first()
        for phone in ("+201000000001", "+201000000002")
    ]
    if users[0] is None:
        users[0] = User(phone="+201000000001", password_hash="x", salt="y", tier="free")
        session.add(users[0])
        session.commit()
        session.refresh(users[0])
        users[1] = User(phone="+201000000002", password_hash="x", salt="y", tier="free")
        session.add(users[1])
        session.commit()
        session.refresh(users[1])

    yield session, users[0], users[1]
    session.close()
    engine.dispose()


_IDS = count(1)


def _add_tracker(session, user, active=True, created_at=None):
    item = TrackedItem(
        user_id=user.id,
        canonical_product_id=f"item-{user.id}-{next(_IDS)}",
        is_active=active,
    )
    if created_at is not None:
        item.created_at = created_at
    session.add(item)
    session.commit()
    return item


def _client(session, user):
    app = FastAPI()
    app.include_router(usage_limits.router)

    def _database():
        yield session

    app.dependency_overrides[get_db] = _database
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


# --- mode resolution -------------------------------------------------------


def test_default_mode_is_fair_use(monkeypatch):
    """An unset variable must land on the free-tracker mode, never on payments."""
    monkeypatch.delenv(CREDITS_ENFORCEMENT_ENV, raising=False)
    assert usage_limits.enforcement_mode() == usage_limits.FAIR_USE


def test_mode_ignores_case_and_refuses_an_unknown_value(monkeypatch, caplog):
    monkeypatch.setenv(CREDITS_ENFORCEMENT_ENV, " FAIR_USE ")
    assert usage_limits.enforcement_mode() == usage_limits.FAIR_USE

    monkeypatch.setenv(CREDITS_ENFORCEMENT_ENV, "paywall")
    caplog.set_level("WARNING")
    assert usage_limits.enforcement_mode() == usage_limits.FAIR_USE
    assert any(
        r.getMessage().startswith("Ignoring an unrecognized CREDITS_ENFORCEMENT")
        for r in caplog.records
    )


def test_payments_surface_is_off_unless_asked_for(monkeypatch):
    monkeypatch.delenv(usage_limits.PAYMENTS_ENABLED_ENV, raising=False)
    monkeypatch.setenv(CREDITS_ENFORCEMENT_ENV, usage_limits.FAIR_USE)
    assert usage_limits.payments_surface_enabled() is False

    monkeypatch.setenv(usage_limits.PAYMENTS_ENABLED_ENV, "true")
    assert usage_limits.payments_surface_enabled() is True

    # The legacy credit model cannot work without a way to buy credits.
    monkeypatch.delenv(usage_limits.PAYMENTS_ENABLED_ENV, raising=False)
    monkeypatch.setenv(CREDITS_ENFORCEMENT_ENV, usage_limits.LEGACY_CREDITS)
    assert usage_limits.payments_surface_enabled() is True


def test_cap_configuration_mistakes_fall_back_to_the_default(monkeypatch, caplog):
    monkeypatch.delenv(usage_limits.MAX_TRACKERS_ENV, raising=False)
    assert usage_limits.max_trackers() == usage_limits.DEFAULT_MAX_TRACKERS

    caplog.set_level("WARNING")
    for bad in ("many", "0", "-5"):
        monkeypatch.setenv(usage_limits.MAX_TRACKERS_ENV, bad)
        assert usage_limits.max_trackers() == usage_limits.DEFAULT_MAX_TRACKERS

    monkeypatch.setenv(usage_limits.MAX_TRACKERS_ENV, "250")
    assert usage_limits.max_trackers() == 250


# --- the cap ---------------------------------------------------------------


def test_fair_use_cap_refuses_with_a_structured_detail(db_session, monkeypatch):
    session, user, _ = db_session
    monkeypatch.setenv(CREDITS_ENFORCEMENT_ENV, usage_limits.FAIR_USE)
    monkeypatch.setenv(usage_limits.MAX_TRACKERS_ENV, "2")

    _add_tracker(session, user)
    _add_tracker(session, user)
    # A paused tracker frees a slot: the cap counts what is actually tracking,
    # which is what makes "delete one to make room" a real affordance.
    _add_tracker(session, user, active=False)

    with pytest.raises(HTTPException) as error:
        usage_limits.enforce_tracker_creation(session, user)

    assert error.value.status_code == 409
    assert error.value.detail == {
        "code": "fair_use_cap",
        "active_trackers": 2,
        "cap": 2,
    }


def test_fair_use_cap_leaves_the_ledger_alone(db_session, monkeypatch):
    """Free tracking is free: reaching the cap must not burn a credit."""
    session, user, _ = db_session
    monkeypatch.setenv(CREDITS_ENFORCEMENT_ENV, usage_limits.FAIR_USE)
    monkeypatch.setenv(usage_limits.MAX_TRACKERS_ENV, "1")
    _add_tracker(session, user)

    with pytest.raises(HTTPException):
        usage_limits.enforce_tracker_creation(session, user)

    assert credits_module.get_balance(session, user) == 100
    assert session.query(credits_module.CreditTransaction).count() == 0


def test_off_mode_bounds_nothing(db_session, monkeypatch):
    session, user, _ = db_session
    monkeypatch.setenv(CREDITS_ENFORCEMENT_ENV, usage_limits.DISABLED)
    monkeypatch.setenv(usage_limits.MAX_TRACKERS_ENV, "1")
    for _ in range(5):
        usage_limits.enforce_tracker_creation(session, user)

    assert credits_module.get_balance(session, user) == 100


# --- the creation rate window -----------------------------------------------


def _fixed_clock(monkeypatch, moment):
    monkeypatch.setattr(usage_limits, "_now", lambda: moment)


def test_creating_too_fast_answers_429_with_retry_after(db_session, monkeypatch):
    session, user, _ = db_session
    monkeypatch.setenv(CREDITS_ENFORCEMENT_ENV, usage_limits.FAIR_USE)
    start = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
    _fixed_clock(monkeypatch, start)

    usage_limits.enforce_tracker_creation(session, user)

    # One second later: the attempt is refused, and because a refused attempt
    # also charges the window, the countdown is re-measured from this attempt.
    _fixed_clock(monkeypatch, start + timedelta(seconds=1))
    with pytest.raises(HTTPException) as error:
        usage_limits.enforce_tracker_creation(session, user)

    assert error.value.status_code == 429
    # The header is what the client counts down from; the detail carries the
    # same number without rounding it away.
    assert error.value.headers == {"Retry-After": "3"}
    assert error.value.detail["code"] == "creation_rate_limit"
    assert error.value.detail["retry_after_seconds"] == pytest.approx(
        usage_limits.MIN_CREATION_INTERVAL_SECONDS
    )


def test_obeying_the_advertised_wait_always_gets_through(db_session, monkeypatch):
    """A client that waits exactly what the server advertised is let through.

    This is the contract the countdown UI is built on: the advertised number
    must never be shorter than the wait the server will actually enforce, which
    is exactly what goes wrong when a refused attempt moves the window forward
    but reports the old remainder.
    """
    session, user, _ = db_session
    monkeypatch.setenv(CREDITS_ENFORCEMENT_ENV, usage_limits.FAIR_USE)
    start = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
    _fixed_clock(monkeypatch, start)
    usage_limits.enforce_tracker_creation(session, user)

    for offset in (0.5, 1, 2, 2.9):
        _fixed_clock(monkeypatch, start + timedelta(seconds=offset))
        with pytest.raises(HTTPException) as error:
            usage_limits.enforce_tracker_creation(session, user)
        assert error.value.status_code == 429

        advertised = float(error.value.detail["retry_after_seconds"])
        assert int(error.value.headers["Retry-After"]) >= math.ceil(advertised)

        # Trust the answer: wait exactly that long, from that attempt.
        _fixed_clock(monkeypatch, start + timedelta(seconds=offset + advertised))
        assert usage_limits.enforce_tracker_creation(session, user) is None


def test_header_and_body_never_disagree_on_a_tiny_window(db_session, monkeypatch):
    """A sub-second window must not report 0.0 seconds in the body while the
    header still says one second."""
    session, user, _ = db_session
    monkeypatch.setenv(CREDITS_ENFORCEMENT_ENV, usage_limits.FAIR_USE)
    monkeypatch.setattr(usage_limits, "MIN_CREATION_INTERVAL_SECONDS", 0.004)

    usage_limits.enforce_tracker_creation(session, user)
    with pytest.raises(HTTPException) as error:
        usage_limits.enforce_tracker_creation(session, user)

    assert error.value.status_code == 429
    assert error.value.detail["retry_after_seconds"] > 0
    assert int(error.value.headers["Retry-After"]) >= math.ceil(
        error.value.detail["retry_after_seconds"]
    )


def test_the_throttle_map_is_bounded_and_prunes_stale_entries(monkeypatch):
    """A long-running process must not grow the window with its user count.

    An entry only constrains its owner for ``MIN_CREATION_INTERVAL_SECONDS``,
    so the map is evicted rather than allowed to expand, and attempts that can
    no longer trigger a 429 are forgotten outright.
    """
    monkeypatch.setattr(usage_limits, "_THROTTLE_MAX_ENTRIES", 3)
    start = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
    _fixed_clock(monkeypatch, start)

    for index in range(8):
        _fixed_clock(monkeypatch, start + timedelta(seconds=index))
        usage_limits._record_attempt(SimpleNamespace(id=1000 + index))
        assert len(usage_limits._last_creation_at) <= 3

    # Six hundred seconds later nothing in the map can answer 429 any more.
    _fixed_clock(monkeypatch, start + timedelta(seconds=600))
    usage_limits._prune_stale(usage_limits._now())
    assert usage_limits._last_creation_at == {}


def test_rate_window_is_per_user(db_session, monkeypatch):
    session, first, second = db_session
    monkeypatch.setenv(CREDITS_ENFORCEMENT_ENV, usage_limits.FAIR_USE)
    start = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
    _fixed_clock(monkeypatch, start)

    usage_limits.enforce_tracker_creation(session, first)
    # A different user creating at the same instant is not held hostage.
    usage_limits.enforce_tracker_creation(session, second)

    with pytest.raises(HTTPException) as error:
        usage_limits.enforce_tracker_creation(session, first)
    assert error.value.status_code == 429


def test_a_refused_attempt_still_counts_as_an_attempt(db_session, monkeypatch):
    """Otherwise a capped user could probe the cap for free."""
    session, user, _ = db_session
    monkeypatch.setenv(CREDITS_ENFORCEMENT_ENV, usage_limits.FAIR_USE)
    monkeypatch.setenv(usage_limits.MAX_TRACKERS_ENV, "1")
    _add_tracker(session, user)

    start = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
    _fixed_clock(monkeypatch, start)
    with pytest.raises(HTTPException) as cap_error:
        usage_limits.enforce_tracker_creation(session, user)
    assert cap_error.value.status_code == 409

    _fixed_clock(monkeypatch, start + timedelta(seconds=1))
    with pytest.raises(HTTPException) as rate_error:
        usage_limits.enforce_tracker_creation(session, user)
    assert rate_error.value.status_code == 429


# --- the legacy ledger stays intact under CREDITS_ENFORCEMENT=on -----------


def test_on_mode_still_deducts_and_still_answers_402(db_session, monkeypatch):
    session, user, _ = db_session
    monkeypatch.setenv(CREDITS_ENFORCEMENT_ENV, usage_limits.LEGACY_CREDITS)

    assert usage_limits.enforce_tracker_creation(session, user) is None
    assert credits_module.get_balance(session, user) == 99
    assert session.query(credits_module.CreditTransaction).count() == 1

    credits_module.deduct(session, user, amount=99)
    with pytest.raises(HTTPException) as error:
        usage_limits.enforce_tracker_creation(session, user)
    assert error.value.status_code == 402


# --- GET /usage/limits ----------------------------------------------------


def test_usage_limits_reports_the_fair_use_state(db_session, monkeypatch):
    session, user, _ = db_session
    monkeypatch.setenv(CREDITS_ENFORCEMENT_ENV, usage_limits.FAIR_USE)
    monkeypatch.setenv(usage_limits.MAX_TRACKERS_ENV, "3")
    _add_tracker(session, user, created_at=datetime(2026, 10, 29, 8, 0, 0))
    _add_tracker(session, user)
    _add_tracker(session, user, active=False)
    usage_limits.enforce_tracker_creation(session, user)

    body = _client(session, user).get("/usage/limits").json()

    assert body["enforcement"] == "fair_use"
    assert body["active_trackers"] == 2
    assert body["cap"] == 3
    assert body["created_last"].endswith("Z")
    # The clock just recorded a creation, so the client has a countdown to show.
    assert 0 < body["retry_after_seconds"] <= 3.0


def test_usage_limits_reports_no_cap_when_fair_use_is_off(db_session, monkeypatch):
    """The client must not render a ceiling the server is not enforcing."""
    session, user, _ = db_session
    monkeypatch.setenv(CREDITS_ENFORCEMENT_ENV, usage_limits.DISABLED)
    monkeypatch.delenv(usage_limits.MAX_TRACKERS_ENV, raising=False)

    body = _client(session, user).get("/usage/limits").json()
    assert body["enforcement"] == "off"
    assert body["cap"] is None
    assert body["active_trackers"] == 0
    assert body["created_last"] is None


def test_usage_limits_never_answers_without_a_session(db_session):
    """Per-user state, so an anonymous caller gets no numbers at all."""
    session, user, _ = db_session
    app = FastAPI()
    app.include_router(usage_limits.router)
    app.dependency_overrides[get_db] = lambda: (yield session)

    response = TestClient(app).get("/usage/limits")
    assert response.status_code == 401
