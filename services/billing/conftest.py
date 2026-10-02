"""Shared fixtures for the billing service test suite.

The slowapi limiter is process-global and every TestClient shares the same
"testclient" IP, so the rate-limit state must be reset around each test to
keep quota exhaustion from leaking between tests.
"""

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    # Deferred import: importing services.billing.main at collection time
    # would create its SQLAlchemy engine before DATABASE_URL is finalized by
    # other test modules. Importing inside the fixture body defers that to
    # test-execution time, when the env is stable.
    from services.billing.main import limiter

    limiter.reset()
    yield
    limiter.reset()
