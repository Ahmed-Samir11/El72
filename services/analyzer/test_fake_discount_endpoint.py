"""Endpoint tests for GET /intelligence/fake-discount/{sku}.

The analyzer's startup event (which creates real asyncpg pools) is NOT run by
``TestClient`` here, so we inject a fake pool onto ``app.state`` and clean it
up afterwards. This keeps the tests hermetic — no Postgres required.
"""

import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "postgres://user:pass@localhost/testdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest
from fastapi.testclient import TestClient

from services.analyzer.app import app

NOW = datetime(2025, 9, 1, tzinfo=timezone.utc)


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, query, *args):
        return self._rows


class _AcquireCtx:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return _FakeConn(self._rows)

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, rows):
        self._rows = rows

    def acquire(self):
        return _AcquireCtx(self._rows)


def _rows(prices, store_id="amazon_eg", advertised=None):
    rows = []
    n = len(prices)
    for i, price in enumerate(prices):
        days_ago = 90 - i * (90 // max(n - 1, 1))
        rows.append(
            {
                "time": NOW - timedelta(days=days_ago),
                "store_id": store_id,
                "price_local": price,
                "advertised_price": advertised,
            }
        )
    return rows


@pytest.fixture()
def client():
    # Deliberately NOT a context manager: that would fire the startup event,
    # which creates real Redis/Postgres pools. We inject a fake pool instead.
    return TestClient(app)


@pytest.fixture()
def with_pool():
    """Context manager: install a fake pool with the given rows, restore after."""

    def _install(rows):
        previous = getattr(app.state, "ts_pool", None)
        app.state.ts_pool = _FakePool(rows)
        return previous

    def _restore(previous):
        if previous is None:
            if hasattr(app.state, "ts_pool"):
                del app.state.ts_pool
        else:
            app.state.ts_pool = previous

    return _install, _restore


def test_fake_discount_endpoint_flags_fake_discount(client, with_pool):
    install, restore = with_pool
    # Typical ~1200, current 1180, advertised "was" 1800 -> suspicious.
    previous = install(_rows([1200] * 19 + [1180], advertised=1800))
    try:
        response = client.get("/intelligence/fake-discount/sku-1")
        assert response.status_code == 200
        body = response.json()
        assert body["is_suspicious"] is True
        assert body["stats"]["reference_source"] == "advertised"
        assert body["stats"]["current_price"] == 1180
        assert "typically sold for" in body["summary"]
    finally:
        restore(previous)


def test_fake_discount_endpoint_genuine_discount(client, with_pool):
    install, restore = with_pool
    previous = install(_rows([1200] * 19 + [900]))
    try:
        response = client.get("/intelligence/fake-discount/sku-1")
        assert response.status_code == 200
        body = response.json()
        assert body["is_suspicious"] is False
        assert "genuine discount" in body["summary"]
    finally:
        restore(previous)


def test_fake_discount_endpoint_unknown_sku_is_insufficient_history(client, with_pool):
    install, restore = with_pool
    # No rows at all -> 200 with insufficient_history, not a 500.
    previous = install([])
    try:
        response = client.get("/intelligence/fake-discount/does-not-exist")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "insufficient_history"
        assert body["is_suspicious"] is False
    finally:
        restore(previous)


def test_fake_discount_endpoint_store_scope(client, with_pool):
    install, restore = with_pool
    # amazon_eg at 1200, noon at 1150; scoped to amazon_eg sees noon as competitor.
    rows = _rows([1200] * 15, store_id="amazon_eg") + _rows(
        [1150] * 15, store_id="noon"
    )
    previous = install(rows)
    try:
        response = client.get(
            "/intelligence/fake-discount/sku-1", params={"store_id": "amazon_eg"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["store_id"] == "amazon_eg"
        assert body["stats"]["competitor_prices"] == [1150]
    finally:
        restore(previous)


def test_fake_discount_endpoint_503_when_pool_missing(client):
    # Ensure no pool is present for this test.
    previous = getattr(app.state, "ts_pool", None)
    if previous is not None:
        del app.state.ts_pool
    try:
        response = client.get("/intelligence/fake-discount/sku-1")
        assert response.status_code == 503
    finally:
        if previous is not None:
            app.state.ts_pool = previous
