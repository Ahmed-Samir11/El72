"""Shared fixtures for the billing service test suite.

The slowapi limiter is process-global and every TestClient shares the same
"testclient" IP, so the rate-limit state must be reset around each test to
keep quota exhaustion from leaking between tests.
"""

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    # Deferred import: importing services.billing.main at collection time
    # would create its SQLAlchemy engine from whatever DATABASE_URL happens
    # to be set at that moment. Importing inside the fixture body defers that
    # to test-execution time; the engine is never used because get_db is
    # overridden with an in-memory SQLite session in each test.
    from services.api.payment_security import security_monitor
    from services.billing.main import limiter

    limiter.reset()
    security_monitor.reset()
    yield
    limiter.reset()
    security_monitor.reset()
