"""Unit tests for analyzer app helpers and background loops."""

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest

from services.analyzer import app as analyzer_app
from services.analyzer.app import (
    compute_price_bucket,
    fetch_recent_prices,
    find_alerting_users,
    health,
    insert_price_history,
    normalize_message_payload,
    publisher_loop,
    settings,
)


def test_compute_price_bucket_boundaries():
    assert compute_price_bucket(0) == "0-4999"
    assert compute_price_bucket(4999.99) == "0-4999"
    assert compute_price_bucket(5000) == "5000-9999"
    assert compute_price_bucket(9999) == "5000-9999"
    assert compute_price_bucket(10000) == "10000+"


@pytest.mark.asyncio
async def test_normalize_payload_dict_bytes_json():
    fields = {b"payload": json.dumps({"sku": "A", "price": 1}).encode()}
    result = await normalize_message_payload(fields)
    assert result == {"sku": "A", "price": 1}


@pytest.mark.asyncio
async def test_normalize_payload_dict_payload():
    # Non-bytes dict payloads are returned as-is (bytes JSON is parsed above).
    fields = {"payload": {"sku": "B"}}
    result = await normalize_message_payload(fields)
    assert result["sku"] == "B"


@pytest.mark.asyncio
async def test_normalize_payload_unparsed_string_goes_to_dlq():
    redis = AsyncMock()
    fields = {"payload": json.dumps({"sku": "B"})}
    result = await normalize_message_payload(
        fields, redis_client=redis, dlq_stream="dlq", msg_id="1-0"
    )
    assert result is None
    redis.xadd.assert_awaited()


@pytest.mark.asyncio
async def test_normalize_non_dict_goes_to_dlq():
    redis = AsyncMock()
    fields = {b"payload": b"not-a-json-object"}
    result = await normalize_message_payload(
        fields, redis_client=redis, dlq_stream="dlq", msg_id="1-0", orig_stream="s"
    )
    assert result is None
    redis.xadd.assert_awaited()


@pytest.mark.asyncio
async def test_normalize_non_dict_dlq_failure_returns_none():
    redis = AsyncMock()
    redis.xadd.side_effect = Exception("dlq down")
    result = await normalize_message_payload(
        {b"payload": b"plain-text"},
        redis_client=redis,
        dlq_stream="dlq",
        msg_id="1-0",
    )
    assert result is None


@pytest.mark.asyncio
async def test_normalize_unexpected_error_dlqs_raw():
    redis = AsyncMock()

    class BadFields(dict):
        def get(self, *args, **kwargs):
            raise RuntimeError("boom")

    result = await normalize_message_payload(
        BadFields(),
        redis_client=redis,
        dlq_stream="dlq",
        msg_id="9-0",
    )
    assert result is None
    redis.xadd.assert_awaited()


@pytest.mark.asyncio
async def test_insert_and_fetch_prices():
    conn = AsyncMock()
    conn.fetch.return_value = [{"price_egp": 10}, {"price_egp": 12}]
    await insert_price_history(
        conn, {"timestamp": 1, "sku": "S", "store": "amazon", "price": 10, "in_stock": True}
    )
    conn.execute.assert_awaited()
    prices = await fetch_recent_prices(conn, "S", "amazon", limit=2)
    assert prices == [10.0, 12.0]


@pytest.mark.asyncio
async def test_find_alerting_users_success_and_error():
    conn = AsyncMock()
    conn.fetch.return_value = [{"user_id": 1, "category": "laptops"}]
    assert await find_alerting_users(conn, "SKU") == [{"user_id": 1, "category": "laptops"}]

    conn.fetch.side_effect = Exception("no table")
    assert await find_alerting_users(conn, "SKU") == []


@pytest.mark.asyncio
async def test_publisher_loop_success():
    redis = AsyncMock()
    queue = asyncio.Queue()
    analyzer_app.app.state.redis = redis
    analyzer_app.app.state.publish_queue = queue

    await queue.put({"sku": "A", "trace_id": "t1"})

    original_batch = settings.publish_batch_size
    original_interval = settings.publish_batch_interval_s
    original_retries = settings.publish_retry_attempts
    settings.publish_batch_size = 1
    settings.publish_batch_interval_s = 0.01
    settings.publish_retry_attempts = 1

    task = asyncio.create_task(publisher_loop())
    await asyncio.sleep(0.05)
    task.cancel()
    await task

    redis.xadd_many.assert_awaited()
    settings.publish_batch_size = original_batch
    settings.publish_batch_interval_s = original_interval
    settings.publish_retry_attempts = original_retries


@pytest.mark.asyncio
async def test_publisher_loop_dlq_on_failure():
    redis = AsyncMock()
    redis.xadd_many.side_effect = Exception("publish fail")
    queue = asyncio.Queue()
    analyzer_app.app.state.redis = redis
    analyzer_app.app.state.publish_queue = queue

    await queue.put({"sku": "C", "trace_id": "t3"})

    original_batch = settings.publish_batch_size
    original_interval = settings.publish_batch_interval_s
    original_retries = settings.publish_retry_attempts
    original_backoff = settings.publish_retry_backoff_s
    settings.publish_batch_size = 1
    settings.publish_batch_interval_s = 0.01
    settings.publish_retry_attempts = 1
    settings.publish_retry_backoff_s = 0

    task = asyncio.create_task(publisher_loop())
    await asyncio.sleep(0.05)
    task.cancel()
    await task

    redis.xadd.assert_awaited()
    settings.publish_batch_size = original_batch
    settings.publish_batch_interval_s = original_interval
    settings.publish_retry_attempts = original_retries
    settings.publish_retry_backoff_s = original_backoff


@pytest.mark.asyncio
async def test_health_endpoint():
    res = await health()
    assert res["status"] == "ok"
    assert "ml_method" in res


@pytest.mark.asyncio
async def test_trace_middleware_sets_header():
    async def call_next(request):
        from starlette.responses import JSONResponse

        return JSONResponse({"ok": True})

    response = await analyzer_app.add_trace_id(
        type("Req", (), {"headers": {"X-Trace-Id": "trace-abc"}})(),
        call_next,
    )
    assert response.headers["X-Trace-Id"] == "trace-abc"

    response2 = await analyzer_app.add_trace_id(
        type("Req", (), {"headers": {}})(),
        call_next,
    )
    assert response2.headers.get("X-Trace-Id")


@pytest.mark.asyncio
async def test_consume_loop_filters_out_of_stock_and_acks():
    redis = AsyncMock()
    redis.xreadgroup.side_effect = [
        [
            (
                "stream:price_ingest",
                [
                    (
                        "1-0",
                        {
                            b"payload": json.dumps(
                                {"sku": "S", "store": "a", "price": 10, "in_stock": False}
                            ).encode()
                        },
                    )
                ],
            )
        ],
        asyncio.CancelledError(),
    ]
    analyzer_app.app.state.redis = redis
    analyzer_app.app.state.ts_pool = MagicMock()
    analyzer_app.app.state.pg_pool = MagicMock()

    with patch(
        "services.analyzer.app.normalize_message_payload",
        new=AsyncMock(
            return_value={"sku": "S", "store": "a", "price": 10, "in_stock": False}
        ),
    ):
        await analyzer_app.consume_loop()

    redis.xack.assert_awaited()


@pytest.mark.asyncio
async def test_consume_loop_waits_when_stream_is_empty():
    redis = AsyncMock()
    redis.xreadgroup.side_effect = [[], asyncio.CancelledError()]
    analyzer_app.app.state.redis = redis
    analyzer_app.app.state.ts_pool = MagicMock()
    analyzer_app.app.state.pg_pool = MagicMock()

    await analyzer_app.consume_loop()
    assert redis.xreadgroup.await_count == 2


@pytest.mark.asyncio
async def test_consume_loop_anomaly_publishes():
    redis = AsyncMock()
    payload = {
        "sku": "S",
        "store": "amazon",
        "price": 1000,
        "timestamp": 1,
        "in_stock": True,
        "trace_id": "t",
    }
    redis.xreadgroup.side_effect = [
        [("stream:price_ingest", [("2-0", {b"payload": json.dumps(payload).encode()})])],
        asyncio.CancelledError(),
    ]

    ts_conn = AsyncMock()
    ts_conn.fetch.return_value = [{"price_egp": float(x)} for x in range(100, 120)]
    ts_pool = MagicMock()
    ts_pool.acquire.return_value.__aenter__.return_value = ts_conn
    ts_pool.acquire.return_value.__aexit__.return_value = False

    pg_conn = AsyncMock()
    pg_conn.fetch.return_value = [{"user_id": 1, "category": "gpu"}]
    pg_pool = MagicMock()
    pg_pool.acquire.return_value.__aenter__.return_value = pg_conn
    pg_pool.acquire.return_value.__aexit__.return_value = False

    analyzer_app.app.state.redis = redis
    analyzer_app.app.state.ts_pool = ts_pool
    analyzer_app.app.state.pg_pool = pg_pool
    analyzer_app.app.state.publish_queue = asyncio.Queue()

    original_threshold = settings.ml_threshold
    original_method = settings.ml_method
    settings.ml_threshold = 0.0
    settings.ml_method = "mad"

    with patch(
        "services.analyzer.app.upsert_retailer_analytics_batch", new=AsyncMock()
    ) as upsert:
        await analyzer_app.consume_loop()

    assert analyzer_app.app.state.publish_queue.qsize() == 1
    upsert.assert_awaited()
    redis.xack.assert_awaited()

    settings.ml_threshold = original_threshold
    settings.ml_method = original_method


@pytest.mark.asyncio
async def test_shutdown_cancels_tasks():
    redis = AsyncMock()
    pg_pool = AsyncMock()
    ts_pool = AsyncMock()

    async def forever():
        await asyncio.Event().wait()

    analyzer_app.app.state.redis = redis
    analyzer_app.app.state.pg_pool = pg_pool
    analyzer_app.app.state.ts_pool = ts_pool
    analyzer_app.app.state.loop = asyncio.create_task(forever())
    analyzer_app.app.state.metrics_task = asyncio.create_task(forever())
    analyzer_app.app.state.metrics_sampler_task = asyncio.create_task(forever())
    analyzer_app.app.state.publisher_task = asyncio.create_task(forever())

    await analyzer_app.shutdown()

    redis.close.assert_awaited()
    pg_pool.close.assert_awaited()
    ts_pool.close.assert_awaited()


@pytest.mark.asyncio
async def test_startup_initializes_stream_pools_and_background_tasks():
    redis = MagicMock()
    redis.ensure_group = AsyncMock()
    redis.close = AsyncMock()
    redis.redis = MagicMock()
    redis.redis.xlen = AsyncMock(return_value=0)
    redis.redis.xpending = AsyncMock(return_value=0)
    pg_pool = MagicMock()
    pg_pool.close = AsyncMock()
    ts_pool = MagicMock()
    ts_pool.close = AsyncMock()

    async def forever():
        await asyncio.Event().wait()

    with patch("services.analyzer.app.RedisStreamClient.create", new=AsyncMock(return_value=redis)), \
        patch("services.analyzer.app.asyncpg.create_pool", new=AsyncMock(side_effect=[pg_pool, ts_pool])), \
        patch("services.analyzer.app.consume_loop", new=forever), \
        patch("services.analyzer.app.publisher_loop", new=forever), \
        patch("services.analyzer.app.ml_detector.load_model_from_dir") as load_model:
        await analyzer_app.startup()

    redis.ensure_group.assert_awaited_once()
    assert analyzer_app.app.state.pg_pool is pg_pool
    assert analyzer_app.app.state.ts_pool is ts_pool
    load_model.assert_called_once_with(settings.model_dir)
    assert any(route.path == "/metrics" for route in analyzer_app.app.routes)
    await analyzer_app.shutdown()


@pytest.mark.asyncio
async def test_startup_fails_fast_without_database_url():
    original_database_url = settings.database_url
    settings.database_url = ""
    try:
        with patch("services.analyzer.app.RedisStreamClient.create", new=AsyncMock(return_value=AsyncMock())):
            with pytest.raises(SystemExit, match="DATABASE_URL is required"):
                await analyzer_app.startup()
    finally:
        settings.database_url = original_database_url


@pytest.mark.asyncio
async def test_trace_id_filter():
    filt = analyzer_app.TraceIdFilter()
    record = MagicMock()
    assert filt.filter(record) is True
    assert hasattr(record, "trace_id")
