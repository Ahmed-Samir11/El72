"""Shared pytest fixtures for the API service tests.

The slowapi Limiter is a module-level singleton backed by in-memory storage,
and every TestClient shares the same "testclient" client IP. Without a reset
between tests, per-minute quotas would accumulate across the whole suite and
start returning spurious 429s. The autouse fixture below gives every test a
fresh rate-limit state.
"""

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    # Import inside the fixture (not at module level): importing
    # services.api.dependencies at collection time would create its
    # engine before test modules finalize DATABASE_URL.
    from services.api.routers.payment import limiter

    limiter.reset()
    yield
    limiter.reset()
