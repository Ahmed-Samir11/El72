"""Shared pytest fixtures for the API service tests.

The slowapi Limiter is a module-level singleton backed by in-memory storage,
and every TestClient shares the same "testclient" client IP. Without a reset
between tests, per-minute quotas would accumulate across the whole suite and
start returning spurious 429s. The autouse fixture below gives every test a
fresh rate-limit state.

The fair-use creation throttle (plans/p3) is process-local state with the same
sharing problem, so it is reset here too. Tests also run with
``CREDITS_ENFORCEMENT=off`` — the mode the plan reserves for dev and test
harnesses — because the point of most endpoint tests is the endpoint, not the
limit; the fair-use, legacy-credit and unlimited behaviors each set the mode
explicitly, so the default (``fair_use``) is never papered over silently.

``PAYMENTS_ENABLED`` is forced on for the suite **before** any test module imports
``services.api.main`` (conftest is imported first), because the payment routers
are mounted once, at import. Flagging them out of the release build must not
silently stop the legacy payment tests from running; the release posture —
no Paymob route at all — is asserted separately in ``test_main.py`` by calling
``mount_routers(..., payment_surface=False)``, an explicit decision rather than
an inherited environment.

SECRET_KEY has no default in the service itself (a hard-coded signing key would
let anyone forge tokens), so the suite supplies a test-only value before any
API module is imported.
"""

import os

import pytest

os.environ["PAYMENTS_ENABLED"] = "true"
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-used-in-production")


@pytest.fixture(autouse=True)
def _reset_rate_limiter(monkeypatch):
    # Import inside the fixture (not at module level): importing
    # services.api.dependencies at collection time would create its
    # engine before test modules finalize DATABASE_URL.
    from services.api.payment_security import security_monitor
    from services.api.routers.affiliate import limiter as affiliate_limiter
    from services.api.routers.payment import limiter
    from services.api.usage_limits import reset_creation_times

    monkeypatch.setenv("CREDITS_ENFORCEMENT", "off")
    reset_creation_times()

    limiter.reset()
    affiliate_limiter.reset()
    security_monitor.reset()
    yield
    limiter.reset()
    affiliate_limiter.reset()
    security_monitor.reset()
    reset_creation_times()
