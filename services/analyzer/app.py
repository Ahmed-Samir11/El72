import os
import asyncio
import json
import logging
import uuid
import contextvars
import time
from typing import Dict, Any, List, Optional

import asyncpg
import numpy as np
from fastapi import FastAPI, Response
from pythonjsonlogger import jsonlogger
from prometheus_client import Gauge

from services.common.redis_client import RedisStreamClient
from services.analyzer import ml_detector
from services.analyzer.intent_upsert import upsert_retailer_analytics_batch
from services.analyzer.settings import AnalyzerSettings

settings = AnalyzerSettings()

# Structured JSON logging
trace_id_var = contextvars.ContextVar("trace_id", default=None)


class TraceIdFilter(logging.Filter):
    def filter(self, record):
        record.trace_id = trace_id_var.get() or ""
        return True


logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s %(trace_id)s')
logHandler.setFormatter(formatter)
root = logging.getLogger()
root.setLevel(logging.INFO)
root.addHandler(logHandler)
root.addFilter(TraceIdFilter())
logger = logging.getLogger(settings.service_name)

app = FastAPI(title="Elhaq Analyzer")

# Prometheus metrics
PUBLISH_QUEUE_SIZE = Gauge("analyzer_publish_queue_size", "Size of the publish queue")
DLQ_STREAM_LENGTH = Gauge("analyzer_dlq_stream_length", "Length of the analyzer DLQ stream")
CONSUMER_PENDING = Gauge("analyzer_consumer_pending", "Number of pending messages for consumer group")
PG_POOL_WAITERS = Gauge("analyzer_pg_pool_waiters", "Number of waiters on the Postgres pool")
TS_POOL_WAITERS = Gauge("analyzer_ts_pool_waiters", "Number of waiters on the Timescale pool")


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
    # Publisher queue for confirmed deals (batched)
    app.state.publish_queue: asyncio.Queue = asyncio.Queue()
    app.state.publisher_task = asyncio.create_task(publisher_loop())
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

    # Start metrics sampler for queue/DLQ/consumer lag and DB pool waiters
    async def _metrics_sampler():
        raw = app.state.redis
        while True:
            try:
                # publish queue size
                try:
                    PUBLISH_QUEUE_SIZE.set(app.state.publish_queue.qsize())
                except Exception:
                    PUBLISH_QUEUE_SIZE.set(0)

                # DLQ length (stream)
                try:
                    dlq_len = await app.state.redis.redis.xlen(settings.dlq_stream)
                except Exception:
                    dlq_len = 0
                DLQ_STREAM_LENGTH.set(dlq_len)

                # Consumer pending (XPENDING) — try multiple formats
                try:
                    xp = await app.state.redis.redis.xpending(settings.stream_price_ingest, settings.consumer_group)
                    if isinstance(xp, dict) and "pending" in xp:
                        pending = int(xp.get("pending") or 0)
                    elif isinstance(xp, int):
                        pending = xp
                    elif isinstance(xp, (list, tuple)):
                        pending = len(xp)
                    else:
                        pending = 0
                except Exception:
                    pending = 0
                CONSUMER_PENDING.set(pending)

                # DB pool waiters (best-effort using internal queue if available)
                try:
                    pg_waiters = 0
                    if hasattr(app.state.pg_pool, "_queue"):
                        q = getattr(app.state.pg_pool, "_queue")
                        pg_waiters = q.qsize() if hasattr(q, "qsize") else len(q)
                except Exception:
                    pg_waiters = 0
                PG_POOL_WAITERS.set(pg_waiters)

                try:
                    ts_waiters = 0
                    if hasattr(app.state.ts_pool, "_queue"):
                        q = getattr(app.state.ts_pool, "_queue")
                        ts_waiters = q.qsize() if hasattr(q, "qsize") else len(q)
                except Exception:
                    ts_waiters = 0
                TS_POOL_WAITERS.set(ts_waiters)
            except Exception:
                logger.exception("metrics sampler error")
            await asyncio.sleep(max(1, settings.ml_cpu_sample_interval))

    app.state.metrics_sampler_task = asyncio.create_task(_metrics_sampler())

    # Expose metrics endpoint via FastAPI
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

    @app.get("/metrics")
    async def metrics():
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def normalize_message_payload(fields: Dict[Any, Any], redis_client: RedisStreamClient = None, dlq_stream: str = None, msg_id: str = None, orig_stream: str = None) -> Optional[Dict[str, Any]]:
    """Normalize fields from XREADGROUP to a dict payload.

    If the payload cannot be parsed into a dict, move the original fields to DLQ (if redis_client provided)
    and return None.
    """
    raw = None
    try:
        raw = fields.get(b"payload") or fields.get("payload") or fields
        if isinstance(raw, (bytes, bytearray)):
            text = raw.decode(errors="ignore")
            try:
                obj = json.loads(text)
            except Exception:
                # not JSON — treat as raw string
                obj = text
        else:
            obj = raw

        if isinstance(obj, dict):
            return obj
        # non-dict payload
        if redis_client and dlq_stream:
            # preserve original fields and metadata in DLQ
            dlq_item = {
                "orig_stream": orig_stream or settings.stream_price_ingest,
                "orig_msg_id": msg_id or "",
                "raw": obj,
            }
            try:
                await redis_client.xadd(dlq_stream, {"payload": dlq_item})
            except Exception:
                logger.exception("Failed to push to DLQ for msg %s", msg_id, extra={"msg_id": msg_id, "stream": orig_stream})
        return None
    except Exception:
        # On unexpected error, try to DLQ the raw fields
        if redis_client and dlq_stream:
            try:
                await redis_client.xadd(dlq_stream, {"payload": {"orig_stream": orig_stream or settings.stream_price_ingest, "orig_msg_id": msg_id or "", "raw_fields": str(fields)}})
            except Exception:
                logger.exception("Failed to push unparsable message to DLQ", extra={"msg_id": msg_id, "stream": orig_stream})
        return None


async def publisher_loop():
    """Background publisher that batches confirmed deal publishes to Redis.

    Behavior:
    - Collects up to `settings.publish_batch_size` items or waits `publish_batch_interval_s`
    - Uses `xadd_many` to publish in a single pipeline
    - Retries on failure, moves items to DLQ after retries
    """
    redis: RedisStreamClient = app.state.redis
    q: asyncio.Queue = app.state.publish_queue
    batch_size = settings.publish_batch_size
    interval = settings.publish_batch_interval_s
    dlq = settings.dlq_stream
    while True:
        try:
            item = await q.get()
            batch = [item]
            start = time.monotonic()
            # drain up to batch_size quickly
            while len(batch) < batch_size:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=interval)
                    batch.append(item)
                except asyncio.TimeoutError:
                    break

            # prepare fields for xadd_many
            fields_list = []
            for it in batch:
                # each item already structured
                fields_list.append({"payload": it})

            # attempt publish with retries
            success = False
            for attempt in range(max(1, settings.publish_retry_attempts)):
                try:
                    await redis.xadd_many(settings.stream_confirmed, fields_list)
                    try:
                        # increment metric by batch size if supported
                        ml_detector.ML_PUBLISHED.inc(len(batch))
                    except Exception:
                        pass
                    success = True
                    break
                except Exception:
                    await asyncio.sleep(settings.publish_retry_backoff_s * (2 ** attempt))

            if not success:
                # move each item to DLQ with metadata
                for it in batch:
                    try:
                        await redis.xadd(dlq, {"payload": {"failed_publish": it}})
                    except Exception:
                        logger.exception("Failed to DLQ publish item", extra={"sku": it.get("sku"), "trace_id": it.get("trace_id")})

        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Publisher loop error")
            await asyncio.sleep(1)


@app.middleware("http")
async def add_trace_id(request, call_next):
    """Middleware to ensure a `trace_id` is present and available via contextvar.

    If the incoming request contains `X-Trace-Id` it will be used; otherwise a new
    UUID v4 is generated. The trace id is stored in `trace_id_var` and included in logs.
    """
    header_tid = request.headers.get("X-Trace-Id")
    tid = header_tid or str(uuid.uuid4())
    token = trace_id_var.set(tid)
    try:
        response = await call_next(request)
        response.headers["X-Trace-Id"] = tid
        return response
    finally:
        trace_id_var.reset(token)


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
    await _cancel_and_wait(getattr(app.state, "metrics_sampler_task", None), "metrics_sampler_task", timeout=5.0)
    await _cancel_and_wait(getattr(app.state, "publisher_task", None), "publisher_task", timeout=5.0)

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
            res = await redis.xreadgroup(settings.consumer_group, settings.consumer_name, {settings.stream_price_ingest: ">"}, count=10, block=5000)
            if not res:
                await asyncio.sleep(0.1)
                continue
            for stream, messages in res:
                for msg_id, fields in messages:
                    # Normalize payload (handles bytes/str/json) and DLQs unparsable messages
                    payload = await normalize_message_payload(fields, redis_client=redis, dlq_stream=settings.dlq_stream, msg_id=msg_id, orig_stream=stream)
                    if not payload:
                        # Move on to next message (payload moved to DLQ by normalize_message_payload)
                        await redis.xack(stream, settings.consumer_group, msg_id)
                        continue

                    # propagate trace_id from payload if available, otherwise generate
                    trace_id = payload.get("trace_id") or str(uuid.uuid4())

                    sku = payload.get("sku")
                    store = payload.get("store")

                    logger.info("processing message", extra={"stream": stream, "msg_id": msg_id, "sku": sku, "store": store, "trace_id": trace_id})

                    # Basic filtering
                    if payload.get("in_stock") is False:
                        await redis.xack(stream, settings.consumer_group, msg_id)
                        continue

                    # Persist to timeseries
                    try:
                        async with ts_pool.acquire() as conn:
                            await insert_price_history(conn, payload)
                            # Build window and score using same connection to avoid double-acquire
                            recent = await fetch_recent_prices(conn, sku, store, limit=20)
                        window = np.array(recent[::-1]) if recent else np.array([])

                        # ML scoring with metrics
                        ml_detector.ML_CALLS.inc()
                        start = time.perf_counter()
                        if settings.ml_method == "mad":
                            # keep fast MAD scorer inline to avoid thread hop
                            score = ml_detector.score_prices(window, method="mad")
                        else:
                            # Offload CPU-bound scoring to threadpool
                            score = await asyncio.to_thread(ml_detector.score_prices, window, settings.ml_method)
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

                            # Publish confirmed deal (enqueue to publisher)
                            publish_payload = {
                                "sku": sku,
                                "store": store,
                                "price": payload.get("price"),
                                "timestamp": payload.get("timestamp"),
                                "anomaly_score": score,
                                "trace_id": trace_id,
                                "orig_stream": stream,
                                "orig_msg_id": msg_id,
                            }
                            try:
                                await app.state.publish_queue.put(publish_payload)
                            except Exception:
                                logger.exception("Failed to enqueue publish payload", extra={"sku": sku, "msg_id": msg_id, "trace_id": trace_id})

                        # ACK only after successful DB operations and enqueue
                        await redis.xack(stream, settings.consumer_group, msg_id)
                    except Exception:
                        logger.exception("Error processing message", extra={"msg_id": msg_id, "stream": stream, "sku": sku, "store": store, "trace_id": trace_id})
                        # don't ack — message will remain pending for manual/or later reprocessing
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(1)


@app.get("/health")
async def health():
    """Health endpoint including model status and basic metrics."""
    model_loaded = getattr(ml_detector, "_loaded_model", None) is not None
    meta = getattr(ml_detector, "_loaded_model_meta", None)
    return {
        "status": "ok",
        "model_loaded": model_loaded,
        "model_meta": meta,
        "ml_method": settings.ml_method,
        "ml_threshold": settings.ml_threshold,
    }
