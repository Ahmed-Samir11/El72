"""Tests for intent upsert helpers."""

from unittest.mock import AsyncMock

import pytest

from services.analyzer.intent_upsert import (
    upsert_retailer_analytics,
    upsert_retailer_analytics_batch,
)


@pytest.mark.asyncio
async def test_upsert_batch_empty_noop():
    conn = AsyncMock()
    await upsert_retailer_analytics_batch(conn, [])
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_upsert_batch_and_single():
    conn = AsyncMock()
    items = [("amazon", "gpu", "0-4999", 1, 1.0), ("noon", "cpu", "5000-9999", 2, 0.5)]
    await upsert_retailer_analytics_batch(conn, items)
    conn.execute.assert_awaited_once()
    args = conn.execute.await_args[0]
    assert args[1] == ["amazon", "noon"]
    assert args[4] == [1, 2]

    conn.execute.reset_mock()
    await upsert_retailer_analytics(conn, "store", "cat", "10000+", 3, 2.0)
    conn.execute.assert_awaited_once()
