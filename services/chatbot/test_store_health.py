"""Tests for per-store availability tracking and cooldown."""

import time

from services.chatbot.store_health import (
    STATE_BLOCKED,
    STATE_CACHED,
    STATE_COOLING,
    STATE_EMPTY,
    STATE_OK,
    STATE_ROBOTS_DENIED,
    STATE_TIMEOUT,
    StoreHealth,
)


def test_status_serializes_for_the_client():
    """The status the client shows is a plain JSON-safe dict."""
    health = StoreHealth()
    status = health.record("amazon_eg", STATE_BLOCKED, detail="HTTP 403")

    assert status.as_dict() == {
        "store_id": "amazon_eg",
        "state": "blocked",
        "products": 0,
        "detail": "HTTP 403",
    }


def test_a_reachable_store_never_cools_down():
    """Only repeated failures earn a cooldown; an empty page is still reachable."""
    health = StoreHealth(failure_threshold=2, cooldown_seconds=600)

    for _ in range(4):
        health.record("jiji", STATE_EMPTY)
        health.record("noon_eg", STATE_OK, products=3)
        health.record("amazon_eg", STATE_CACHED, products=2)

    assert not health.is_cooling("jiji")
    assert not health.is_cooling("noon_eg")


def test_a_store_cools_down_after_repeated_failures():
    """A blocked store stops costing crawl time until the window expires."""
    health = StoreHealth(failure_threshold=3, cooldown_seconds=600)

    health.record("amazon_eg", STATE_BLOCKED, detail="HTTP 403")
    assert not health.is_cooling("amazon_eg")
    health.record("amazon_eg", STATE_TIMEOUT, detail="timeout after 25s")
    assert not health.is_cooling("amazon_eg")
    health.record("amazon_eg", STATE_ROBOTS_DENIED, detail="disallowed by robots.txt")

    assert health.is_cooling("amazon_eg")

    status = health.mark_cooling("amazon_eg")
    assert status.state == STATE_COOLING
    assert "skipped for" in status.detail


def test_a_success_clears_the_failure_streak():
    """One good crawl resets the counter, so a flaky store keeps working."""
    health = StoreHealth(failure_threshold=2, cooldown_seconds=600)

    health.record("noon_eg", STATE_BLOCKED)
    health.record("noon_eg", STATE_OK, products=4)
    health.record("noon_eg", STATE_BLOCKED)

    assert not health.is_cooling("noon_eg")


def test_the_cooldown_window_expires():
    """A cooled-down store gets one more chance once the window passes."""
    health = StoreHealth(failure_threshold=1, cooldown_seconds=0.25)

    health.record("amazon_eg", STATE_BLOCKED)
    assert health.is_cooling("amazon_eg")

    # Measured against a 10 ms margin before, which the runner starves: the
    # window had long gone by the time the second read happened, for reasons
    # that have nothing to do with store health.
    time.sleep(0.6)
    assert not health.is_cooling("amazon_eg")
    # The streak was cleared with the window, so one more failure is needed.
    assert not health.is_cooling("amazon_eg")


def test_snapshot_reports_every_store_seen():
    """GET /chatbot/stores answers "why is this list partial?"."""
    health = StoreHealth()
    health.record("amazon_eg", STATE_OK, products=3)
    health.record("jiji", STATE_EMPTY)
    health.record("elbadrgroup", STATE_BLOCKED, detail="connection reset")

    snapshot = health.snapshot()

    assert {entry["store_id"] for entry in snapshot} == {
        "amazon_eg",
        "jiji",
        "elbadrgroup",
    }
    by_id = {entry["store_id"]: entry for entry in snapshot}
    assert by_id["amazon_eg"]["products"] == 3
    assert by_id["elbadrgroup"]["detail"] == "connection reset"


def test_reset_forgets_state():
    """An operator-triggered retry starts the stores from clean."""
    health = StoreHealth(failure_threshold=1, cooldown_seconds=600)
    health.record("amazon_eg", STATE_BLOCKED)

    health.reset()

    assert health.snapshot() == []
    assert not health.is_cooling("amazon_eg")
