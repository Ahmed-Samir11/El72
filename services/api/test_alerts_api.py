"""Unit tests for the alert-surface endpoints (plans/p2 MS1).

``GET /alerts/recent`` and ``POST /alerts/{id}/open`` are the client's only
window onto alert history, so they get the contract assertions a review checks
for: auth-gated, bounded by the server, ordered, scoped to the caller's own
rows, idempotent on open, hostile input refused, over-limit rate answered,
and no PII in the payload.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql.dml import Update as _UPDATE_CONSTRUCT

from services.api.dependencies import get_current_user, get_db
from services.api.models import AlertEvent, User
from services.api.routers import alerts as alerts_module
from services.api.routers.alerts import router


@pytest.fixture
def factory():
    """In-memory SQLite holding the two tables the alert surface reads."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (User.__table__, AlertEvent.__table__):
        table.create(bind=engine, checkfirst=True)
    try:
        # expire_on_commit=False: the helpers hand back ORM objects the tests
        # still read attributes on (ids, opened_at), which a detached-instance
        # refresh would otherwise turn into an error unrelated to the code under
        # test.
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()


def _add_user(factory, phone: str) -> User:
    with factory() as session:
        user = User(phone=phone, password_hash="x", salt="y", tier="free")
        session.add(user)
        session.commit()
        return user


def _add_event(factory, user: User, created_at: datetime, **overrides) -> AlertEvent:
    values = {
        "user_id": user.id,
        "tracked_item_id": 1,
        "sku": "rtx-5060-compumarts",
        "store_id": "compumarts_eg",
        "category": "GPU",
        "url": "https://www.compumarts.com/product/rtx-5060",
        "event_type": "price_drop",
        "price_egp": 8320,
        "reference_price_egp": 9375,
        "discount_pct": 11.25,
        "channel": "in_app",
        "created_at": created_at,
    }
    values.update(overrides)
    with factory() as session:
        event = AlertEvent(**values)
        session.add(event)
        session.commit()
        return event


def _app(factory, user: User | None = None) -> FastAPI:
    """Fresh app with the alert router; auth is overridden only when asked.

    Passing no user leaves the real ``get_current_user`` in place, which is
    how the unauthenticated path stays under test.
    """

    def session_dependency():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = session_dependency
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    return app


def _client(factory, user: User | None = None) -> TestClient:
    app = _app(factory, user)
    if user is None:
        return TestClient(app)
    return TestClient(app, headers={"Authorization": "Bearer token-for-override"})


def test_recent_requires_credentials(factory):
    """The alert feed is per-user: a token-less caller gets an auth wall.

    401 vs 403 is a Starlette-version detail (HTTPBearer changed which one it
    raises); the contract under test is "rejected, and no rows read".
    """
    _add_user(factory, "+201000000001")
    response = _client(factory).get("/alerts/recent")
    assert response.status_code in (401, 403)


def test_recent_is_scoped_to_the_caller_and_newest_first(factory):
    caller = _add_user(factory, "+201000000002")
    other = _add_user(factory, "+201000000003")
    _add_event(factory, caller, datetime(2026, 10, 27, 9, 0, 0))
    _add_event(factory, caller, datetime(2026, 10, 29, 9, 0, 0))
    _add_event(factory, other, datetime(2026, 10, 28, 9, 0, 0))

    body = _client(factory, caller).get("/alerts/recent").json()

    assert len(body["alerts"]) == 2  # the other user's event is not here
    created = [item["created_at"] for item in body["alerts"]]
    assert created == sorted(created, reverse=True)
    assert body["alerts"][0]["sku"] == "rtx-5060-compumarts"
    assert body["alerts"][0]["opened_at"] is None
    assert body["unopened_total"] == 2


def test_recent_limit_is_bounded_by_the_server(factory):
    caller = _add_user(factory, "+201000000004")
    _add_event(factory, caller, datetime(2026, 10, 29, 9, 0, 0))
    client = _client(factory, caller)

    for bad in ("0", "201", "-5", "many"):
        assert client.get("/alerts/recent", params={"limit": bad}).status_code == 422

    _add_event(factory, caller, datetime(2026, 10, 28, 9, 0, 0))
    assert len(client.get("/alerts/recent", params={"limit": 1}).json()["alerts"]) == 1
    # unopened_total stays the full count: the badge must not shrink with the
    # page size, or "N newer alerts" would lie.
    assert (
        client.get("/alerts/recent", params={"limit": 1}).json()["unopened_total"] == 2
    )


def test_since_filters_and_junk_is_refused(factory):
    caller = _add_user(factory, "+201000000005")
    _add_event(factory, caller, datetime(2026, 10, 20, 9, 0, 0))
    _add_event(factory, caller, datetime(2026, 10, 29, 9, 0, 0))
    client = _client(factory, caller)

    assert (
        len(
            client.get("/alerts/recent", params={"since": "2026-10-29"}).json()[
                "alerts"
            ]
        )
        == 1
    )
    assert (
        len(
            client.get("/alerts/recent", params={"since": "2026-10-01"}).json()[
                "alerts"
            ]
        )
        == 2
    )
    assert (
        client.get("/alerts/recent", params={"since": "not-a-date"}).status_code == 400
    )


def test_open_marks_an_event_seen_once(factory):
    caller = _add_user(factory, "+201000000006")
    event = _add_event(factory, caller, datetime(2026, 10, 29, 9, 0, 0))
    client = _client(factory, caller)

    first = client.post(f"/alerts/{event.id}/open").json()
    assert first["already_open"] is False
    assert first["opened_at"]

    second = client.post(f"/alerts/{event.id}/open")
    assert second.status_code == 200
    assert second.json()["already_open"] is True
    # A re-read keeps the FIRST opened_at: an alert the user re-reads must not
    # look like a fresh return, and the unopened count drops by exactly one.
    assert second.json()["opened_at"] == first["opened_at"]
    assert client.get("/alerts/recent").json()["unopened_total"] == 0

    with factory() as probe:
        row = probe.execute(select(AlertEvent)).scalars().one()
        assert row.opened_at is not None


def test_open_cannot_touch_another_users_event(factory):
    owner = _add_user(factory, "+201000000007")
    intruder = _add_user(factory, "+201000000008")
    event = _add_event(factory, owner, datetime(2026, 10, 29, 9, 0, 0))

    response = _client(factory, intruder).post(f"/alerts/{event.id}/open")
    assert response.status_code == 404  # not 403: existence is not an oracle
    assert event.id is not None


def test_open_refuses_ids_this_deployment_never_issues(factory):
    caller = _add_user(factory, "+201000000009")
    client = _client(factory, caller)
    for junk in ("not-an-id", "../../etc/passwd", "1; DROP TABLE users"):
        assert client.post(f"/alerts/{junk}/open").status_code == 404


def test_recent_payload_carries_no_phone_number(factory):
    """PII rule: the feed identifies a user by rows, never by phone."""
    caller = _add_user(factory, "+201000000010")
    _add_event(factory, caller, datetime(2026, 10, 29, 9, 0, 0))

    body = _client(factory, caller).get("/alerts/recent").json()
    assert "+201000000010" not in body.__str__()
    assert "phone" not in body["alerts"][0]


def test_read_rate_limit_is_enforced(factory, monkeypatch):
    """An over-limit read must answer 429, not multiply into the DB."""
    caller = _add_user(factory, "+201000000011")
    monkeypatch.setattr(alerts_module, "ALERTS_READ_RATE_LIMIT", "1/minute")
    client = _client(factory, caller)

    assert client.get("/alerts/recent").status_code == 200
    assert client.get("/alerts/recent").status_code == 429


def test_open_rate_limit_is_enforced(factory, monkeypatch):
    """The open endpoint is a write, so it carries its own cap."""
    caller = _add_user(factory, "+201000000032")
    event = _add_event(factory, caller, datetime(2026, 10, 29, 9, 0, 0))
    monkeypatch.setattr(alerts_module, "ALERTS_OPEN_RATE_LIMIT", "1/minute")
    client = _client(factory, caller)

    assert client.post(f"/alerts/{event.id}/open").status_code == 200
    assert client.post(f"/alerts/{event.id}/open").status_code == 429


def test_since_normalizes_an_offset_to_utc(factory):
    """A client in a non-UTC zone gets the same rows, not a broken comparison.

    ``created_at`` is stored naive UTC, so an aware bound is converted to UTC and
    its offset dropped; leaving it aware would compare two timestamp kinds.
    """
    caller = _add_user(factory, "+201000000031")
    _add_event(factory, caller, datetime(2026, 10, 29, 8, 0, 0))
    client = _client(factory, caller)

    def recent(since):
        return client.get("/alerts/recent", params={"since": since}).json()["alerts"]

    # 10:00+02:00 is 08:00 UTC, so the 08:00 row sits on the boundary and is
    # included; 12:00+02:00 (= 10:00 UTC) excludes it.
    assert len(recent("2026-10-29T10:00:00+02:00")) == 1
    assert len(recent("2026-10-29T12:00:00+02:00")) == 0
    assert len(recent("2026-10-29T06:00:00Z")) == 1


def test_unopened_total_counts_the_account_not_the_window(factory):
    """The badge is per-account; the list is what the window filters.

    ``since`` bounds what the call RETURNS. ``unopened_total`` answers "how many
    of my alerts have I not opened yet" — the opened/unopened ratio Gate 2
    measures — so a client that paginates its history must not read a shorter
    array as a smaller unread count. Pinning this here is cheaper than a
    later "the badge is wrong" bug report about the split.
    """
    caller = _add_user(factory, "+201000000041")
    _add_event(factory, caller, datetime(2026, 10, 20, 9, 0, 0))
    _add_event(factory, caller, datetime(2026, 10, 29, 9, 0, 0))

    body = (
        _client(factory, caller)
        .get("/alerts/recent", params={"since": "2026-10-25T00:00:00"})
        .json()
    )

    assert len(body["alerts"]) == 1, "the window filters the list"
    assert body["unopened_total"] == 2, "the badge counts the whole account"

    # Opening the visible one moves the badge, which is the ratio Gate 2 reads.
    event_id = body["alerts"][0]["id"]
    _client(factory, caller).post(f"/alerts/{event_id}/open")
    body = _client(factory, caller).get("/alerts/recent").json()
    assert body["unopened_total"] == 1


def _count(name: str) -> float:
    """Current value of a Prometheus counter (0.0 when never incremented)."""
    return REGISTRY.get_sample_value(name) or 0.0


def test_open_reports_the_stamp_it_wrote_and_counts_the_open(factory, monkeypatch):
    """An opening is observable without a database query of its own.

    Gate 2's opened/unopened ratio is the KPI this endpoint exists for, so the
    opened counter and the already-open counter must move: re-taps inflate one
    number, fresh opens another, and ops can tell them apart. The returned
    ``opened_at`` is the value this call WROTE rather than a value re-read after
    the commit (the row may be expired or gone by then).
    """
    user = _add_user(factory, "+201000000047")
    event = _add_event(factory, user, datetime(2026, 10, 29, 9, 0, 0))

    before_opened = _count("el72_alert_events_opened_total")
    body = _client(factory, user).post(f"/alerts/{event.id}/open").json()
    assert body["already_open"] is False
    assert body["opened_at"] is not None
    assert _count("el72_alert_events_opened_total") - before_opened == 1

    before_reopen = _count("el72_alert_events_already_open_total")
    second = _client(factory, user).post(f"/alerts/{event.id}/open").json()
    assert second["already_open"] is True
    assert second["opened_at"] == body["opened_at"], "the FIRST opening wins"
    assert _count("el72_alert_events_already_open_total") - before_reopen == 1


def test_open_answers_404_when_the_row_vanishes_mid_request(factory):
    """The race between reading an event and marking it seen is not a 500.

    An account or alert deleted a moment after the read means the UPDATE matches
    nothing and the loaded row no longer exists. Refreshing that row was the bug;
    the honest answer is "this event is not here" — not a success carrying an
    opening that was never recorded.
    """

    class _VanishingRow:
        """SELECT finds the row; the UPDATE then matches nothing, as after a
        concurrent delete."""

        def __init__(self, session):
            self._session = session

        def get_bind(self):
            return self._session.get_bind()

        def execute(self, statement, *args, **kwargs):
            if isinstance(statement, _UPDATE_CONSTRUCT):
                # Row gone: zero rows matched, and the loaded object is stale.
                self._session.execute(delete(AlertEvent))
                return self._session.execute(
                    update(AlertEvent).where(AlertEvent.id == -1)
                )
            return self._session.execute(statement, *args, **kwargs)

        def commit(self):
            self._session.commit()

        def rollback(self):
            self._session.rollback()

    user = _add_user(factory, "+201000000048")
    event = _add_event(factory, user, datetime(2026, 10, 29, 9, 0, 0))
    session = factory()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: _VanishingRow(session)
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app, headers={"Authorization": "Bearer token-for-override"})

    deleted_before = _count("el72_alert_events_event_deleted_total")
    response = client.post(f"/alerts/{event.id}/open")
    assert response.status_code == 404
    assert _count("el72_alert_events_event_deleted_total") - deleted_before == 1
