import os
import asyncio
import json
import logging
import uuid
from typing import Dict, Any, List

import asyncpg
import numpy as np
from fastapi import FastAPI, Response
from pythonjsonlogger import jsonlogger

from services.common.redis_client import RedisStreamClient
from services.analyzer import ml_detector
from services.analyzer.intent_upsert import upsert_retailer_analytics_batch
from services.analyzer.settings import AnalyzerSettings

settings = AnalyzerSettings()

# Structured JSON logging
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s')
logHandler.setFormatter(formatter)
root = logging.getLogger()
root.setLevel(logging.INFO)
root.addHandler(logHandler)
logger = logging.getLogger(settings.service_name)

app = FastAPI(title="Elhaq Analyzer")


@app.on_event("startup")
async def startup():
    """Application startup handler.

    - Initializes Redis stream client and consumer group
    - Creates Postgres connection pools
    - Starts background consume loop
    """
    # Redis
    app.state.redis = await RedisStreamClient.create(settings.redis_url)
    await app.state.redis.ensure_group(settings.stream_price_ingest, settings.consumer_group, mkstream=True)

    # Postgres pools
    if not settings.database_url:
        logger.error("DATABASE_URL is not set. Exiting.")
        raise SystemExit("DATABASE_URL is required")
    ts_url = settings.timescale_url or settings.database_url
    app.state.pg_pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
    app.state.ts_pool = await asyncpg.create_pool(ts_url, min_size=1, max_size=5)

    # background consumer
    app.state.loop = asyncio.create_task(consume_loop())
    # Load persisted ML model (if any)
    try:
        ml_detector.load_model_from_dir(settings.model_dir)
    except Exception:
        logger.exception("Failed to load ML model on startup")

    # Start CPU sampling for metrics
    async def _cpu_sampler():
        import psutil
        proc = psutil.Process()
        while True:
            try:
                # non-blocking percentage since last call
                cpu = proc.cpu_percent(interval=None)
                ml_detector.ML_PROCESS_CPU_PERCENT.set(cpu)
            except Exception:
                logger.exception("CPU sampler error")
            await asyncio.sleep(settings.ml_cpu_sample_interval)

    app.state.metrics_task = asyncio.create_task(_cpu_sampler())

    # Expose metrics endpoint via FastAPI
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

    @app.get("/metrics")
    async def metrics():
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.on_event("shutdown")
async def shutdown():
    """Application shutdown handler.

    Cancels background tasks and closes connections/pools.
    """
    # Orderly shutdown: cancel tasks and await completion with timeout
    async def _cancel_and_wait(task, name: str, timeout: float = 30.0):
        if not task:
            return
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("%s did not finish within %s seconds", name, timeout)
        except asyncio.CancelledError:
            pass

    await _cancel_and_wait(app.state.loop, "consumer_loop", timeout=30.0)
    await _cancel_and_wait(getattr(app.state, "metrics_task", None), "metrics_task", timeout=5.0)

    # Close connections
    try:
        await app.state.redis.close()
    except Exception:
        logger.exception("Error closing redis client")
    try:
        await app.state.pg_pool.close()
    except Exception:
        logger.exception("Error closing pg pool")
    try:
        await app.state.ts_pool.close()
    except Exception:
        logger.exception("Error closing ts pool")


def compute_price_bucket(price: float) -> str:
    """Compute simple price bucket for reporting/aggregation.

    Returns one of: `0-4999`, `5000-9999`, `10000+`.
    """
    if price < 5000:
        return "0-4999"
    if price < 10000:
        return "5000-9999"
    return "10000+"


async def insert_price_history(conn: asyncpg.Connection, event: Dict[str, Any]) -> None:
    """Insert a price event into the `price_history` timeseries table.

    Parameters
    - `conn`: an active asyncpg connection
    - `event`: mapping with keys `timestamp`, `sku`, `store`, `price`, `in_stock`
    """
    await conn.execute(
        """
        INSERT INTO price_history (time, sku, store_id, price_egp, in_stock)
        VALUES (to_timestamp($1)::timestamptz, $2, $3, $4, $5)
        """,
        event.get("timestamp"),
        event.get("sku"),
        event.get("store"),
        float(event.get("price")),
        bool(event.get("in_stock", True)),
    )


async def fetch_recent_prices(conn: asyncpg.Connection, sku: str, store: str, limit: int = 20) -> List[float]:
    """Fetch recent price values for a given `sku` and `store`.

    Returns a list of floats ordered newest->oldest (the caller may reorder).
    """
    rows = await conn.fetch(
        "SELECT price_egp FROM price_history WHERE sku=$1 AND store_id=$2 ORDER BY time DESC LIMIT $3",
        sku,
        store,
        limit,
    )
    return [float(r["price_egp"]) for r in rows]


async def find_alerting_users(conn: asyncpg.Connection, sku: str) -> List[Dict[str, Any]]:
    """Return a list of alerts (user-level subscriptions) for `sku`.

    This function is conservative: if the `alerts` table is not present it returns an empty list.
    Each returned dict should contain at least `user_id` and optionally `category`.
    """
    try:
        rows = await conn.fetch("SELECT user_id, category FROM alerts WHERE sku = $1", sku)
        return [dict(r) for r in rows]
    except Exception:
        return []


async def consume_loop():
    """Background loop that reads events from the price ingest stream and processes them.

    Responsibilities:
    - Read messages from `stream:price_ingest` via consumer group
    - Persist to timeseries
    - Run anomaly scoring and trigger analytics upserts
    - Publish confirmed deals to `stream:confirmed_deals` after DB writes

    The loop acknowledges messages only after successful DB operations.
    """
    redis: RedisStreamClient = app.state.redis
    ts_pool: asyncpg.Pool = app.state.ts_pool
    pg_pool: asyncpg.Pool = app.state.pg_pool
    while True:
        try:
            res = await redis.xreadgroup(GROUP, CONSUMER, {STREAM: ">"}, count=10, block=5000)
            if not res:
                await asyncio.sleep(0.1)
                continue
            for stream, messages in res:
                for msg_id, fields in messages:
                    trace_id = str(uuid.uuid4())
                    payload_b = fields.get(b"payload") or fields.get("payload")
                    try:
                        payload = json.loads(payload_b) if isinstance(payload_b, (bytes, bytearray)) else payload_b
                    except Exception:
                        payload = payload_b

                    sku = (payload.get("sku") if isinstance(payload, dict) else None)
                    store = (payload.get("store") if isinstance(payload, dict) else None)

                    # Basic filtering
                    if payload.get("in_stock") is False:
                        await redis.xack(STREAM, GROUP, msg_id)
                        continue

                    # Persist to timeseries
                    try:
                        async with ts_pool.acquire() as conn:
                            await insert_price_history(conn, payload)
                            # Build window and score using same connection to avoid double-acquire
                            recent = await fetch_recent_prices(conn, sku, store, limit=20)
                        window = np.array(recent[::-1]) if recent else np.array([])

                        # ML scoring with metrics (use async scorer for heavy methods)
                        ml_detector.ML_CALLS.inc()
                        start = time.perf_counter()
                        if settings.ml_method == "mad":
                            score = ml_detector.score_prices(window, method="mad")
                        else:
                            score = await ml_detector.score_prices_async(window, method=settings.ml_method)
                        ml_detector.ML_LATENCY_SECONDS.observe(time.perf_counter() - start)

                        # If anomaly, handle monetization and publish
                        if score > settings.ml_threshold:
                            # Find users who have alerts for this SKU
                            async with pg_pool.acquire() as conn:
                                alerting = await find_alerting_users(conn, sku)
                                # Build batch items for upsert to avoid N+1 DB calls
                                bucket = compute_price_bucket(float(payload.get("price")))
                                items = []
                                for a in alerting:
                                    category = a.get("category") or "unknown"
                                    items.append((store, category, bucket, 1, 1.0))
                                if items:
                                    await upsert_retailer_analytics_batch(conn, items)

                            # Publish confirmed deal (after DB writes)
                            # Publish confirmed deal (after DB writes) with retries and dead-letter on failure
                            publish_payload = {"sku": sku, "store": store, "price": payload.get("price"), "timestamp": payload.get("timestamp"), "anomaly_score": score}
                            success = False
                            for attempt in range(settings.xadd_retries):
                                try:
                                    await redis.xadd(settings.stream_confirmed, {"payload": publish_payload})
                                    ml_detector.ML_PUBLISHED.inc()
                                    success = True
                                    break
                                except Exception:
                                    await asyncio.sleep(settings.xadd_backoff_s * (2 ** attempt))
                            if not success:
                                ml_detector.ML_PUBLISH_FAILURES.inc()
                                try:
                                    raw = app.state.redis.redis
                                    await raw.rpush("queue:failed_publishes", json.dumps({"payload": publish_payload, "trace_id": trace_id}))
                                except Exception:
                                    logger.exception("Failed to persist failed publish for %s", sku)

                        # ACK only after successful DB operations
                        await redis.xack(STREAM, GROUP, msg_id)
                    except Exception as e:
                        logger.exception("Error processing message %s: %s", msg_id, e)
                        # don't ack — message will remain pending for manual/or later reprocessing
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(1)


@app.get("/health")
async def health():
    """Simple health endpoint used by orchestration and readiness checks."""
    return {"status": "ok"}
