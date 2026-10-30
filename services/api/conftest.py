"""Shared pytest fixtures for the API service tests.

The slowapi Limiter is a module-level singleton backed by in-memory storage,
and every TestClient shares the same "testclient" client IP. Without a reset
between tests, per-minute quotas would accumulate across the whole suite and
start returning spurious 429s. The autouse fixture below gives every test a
fresh rate-limit state.
"""

import os

import pytest

# The API owns an in-process stream:alerts consumer (plans/p2 MS1). Tests measure
# the API, not the pipeline: with the default (consumer on) every TestClient startup
# would spawn a task retrying against a Redis that is not there, which is log noise
# and metric pollution, not a fact under test. The consumer's own behaviour is
# covered in test_alert_events_consumer.py, and its on/off switch in
# test_alert_events_startup.py.
os.environ.setdefault("ALERT_EVENTS_CONSUMER", "false")


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    # Import inside the fixture (not at module level): importing
    # services.api.dependencies at collection time would create its
    # engine before test modules finalize DATABASE_URL.
    from services.api.payment_security import security_monitor
    from services.api.routers.affiliate import limiter as affiliate_limiter
    from services.api.routers.alerts import limiter as alerts_limiter
    from services.api.routers.payment import limiter

    limiter.reset()
    affiliate_limiter.reset()
    alerts_limiter.reset()
    security_monitor.reset()
    yield
    limiter.reset()
    affiliate_limiter.reset()
    alerts_limiter.reset()
    security_monitor.reset()
