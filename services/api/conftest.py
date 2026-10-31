"""Shared pytest fixtures for the API service tests.

The slowapi Limiter is a module-level singleton backed by in-memory storage,
and every TestClient shares the same "testclient" client IP. Without a reset
between tests, per-minute quotas would accumulate across the whole suite and
start returning spurious 429s. The autouse fixture below gives every test a
fresh rate-limit state.

SECRET_KEY has no default in the service itself (a hard-coded signing key would
let anyone forge tokens), so the suite supplies a test-only value before any
API module is imported.
"""

import os

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-used-in-production")


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    # Import inside the fixture (not at module level): importing
    # services.api.dependencies at collection time would create its
    # engine before test modules finalize DATABASE_URL.
    from services.api.payment_security import security_monitor
    from services.api.routers.affiliate import limiter as affiliate_limiter
    from services.api.routers.payment import limiter

    limiter.reset()
    affiliate_limiter.reset()
    security_monitor.reset()
    yield
    limiter.reset()
    affiliate_limiter.reset()
    security_monitor.reset()
