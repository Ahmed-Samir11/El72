"""Startup/shutdown guards for the alert-events consumer (plans/p2 MS1).

The API process OWNS the consumer task, so these pin the two operational states
a deployment can be in, both of which ops must be able to tell apart from an
empty Alerts tab:

* the consumer is OFF by explicit configuration, and the log says the feed will
  stay empty (so "no alerts" is traceable to "consumer disabled", not to "nothing
  happened");
* a second startup in the same process never replaces a RUNNING consumer — two
  tasks on one stream group and one gauge would make "the consumer is up" mean
  "one of them is".
"""

import asyncio
import logging
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from services.api import main as api_main


def test_disabled_consumer_starts_no_task(monkeypatch, caplog):
    """ALERT_EVENTS_CONSUMER=false: no task, and the reason is in the log."""
    monkeypatch.setattr(api_main, "ALERT_EVENTS_CONSUMER_ENABLED", False)
    monkeypatch.delenv("ALERT_EVENTS_CONSUMER", raising=False)
    monkeypatch.setattr(api_main.app.state, "alert_events_task", None, raising=False)

    with caplog.at_level(logging.INFO, logger="services.api.main"):
        asyncio.run(api_main._start_alert_events_consumer())

    assert getattr(api_main.app.state, "alert_events_task", None) is None
    joined = " ".join(record.message for record in caplog.records)
    assert "ALERT_EVENTS_CONSUMER=false" in joined
    assert "feed stays empty" in joined, "an empty feed must be traceable"


def test_second_startup_keeps_the_running_consumer(monkeypatch):
    """A live consumer task is never replaced by a second one.

    Only ``.done()`` is consulted, so the stub below is a faithful stand-in for
    a task whose start would otherwise need a real Redis.
    """

    class _Running:
        def __init__(self):
            self.replaced = False

        def done(self):
            return False

    running = _Running()
    monkeypatch.setattr(api_main, "ALERT_EVENTS_CONSUMER_ENABLED", True)
    monkeypatch.setattr(api_main.app.state, "alert_events_task", running, raising=False)

    def fail_if_a_real_task_is_created():
        raise AssertionError("a second consumer task must not be created")

    monkeypatch.setattr(api_main, "consume_loop", fail_if_a_real_task_is_created)

    asyncio.run(api_main._start_alert_events_consumer())
    assert api_main.app.state.alert_events_task is running
