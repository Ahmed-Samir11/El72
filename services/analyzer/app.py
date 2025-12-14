import os
import asyncio
import json
import logging
from typing import Dict, Any, List

import asyncpg
import numpy as np
from fastapi import FastAPI

from services.common.redis_client import RedisStreamClient
from services.analyzer import ml_detector
from services.analyzer.intent_upsert import upsert_retailer_analytics

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("analyzer")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
STREAM = "stream:price_ingest"
GROUP = "cg_analyzer"
CONSUMER = os.getenv("ANALYZER_CONSUMER", "analyzer-1")

# Two DB endpoints: relational (for analytics) and timescale (time-series)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://elhaq:elhaq_pass@localhost:5432/elhaq")
TIMESCALE_URL = os.getenv("TIMESCALE_URL", DATABASE_URL)

ANOMALY_THRESHOLD = float(os.getenv("ANOMALY_THRESHOLD", "0.8"))

app = FastAPI(title="Elhaq Analyzer")


@app.on_event("startup")
async def startup():
    # Redis
    app.state.redis = await RedisStreamClient.create(REDIS_URL)
    await app.state.redis.ensure_group(STREAM, GROUP, mkstream=True)

    # Postgres pools
    app.state.pg_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    app.state.ts_pool = await asyncpg.create_pool(TIMESCALE_URL, min_size=1, max_size=5)

    # background consumer
    app.state.loop = asyncio.create_task(consume_loop())


@app.on_event("shutdown")
async def shutdown():
    app.state.loop.cancel()
    await app.state.redis.close()
    await app.state.pg_pool.close()
    await app.state.ts_pool.close()


def compute_price_bucket(price: float) -> str:
    if price < 5000:
        return "0-4999"
    if price < 10000:
        return "5000-9999"
    return "10000+"


async def insert_price_history(conn: asyncpg.Connection, event: Dict[str, Any]) -> None:
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
    rows = await conn.fetch(
        "SELECT price_egp FROM price_history WHERE sku=$1 AND store_id=$2 ORDER BY time DESC LIMIT $3",
        sku,
        store,
        limit,
    )
    return [float(r["price_egp"]) for r in rows]


async def find_alerting_users(conn: asyncpg.Connection, sku: str) -> List[Dict[str, Any]]:
    # Conservative: query an alerts table if present. Otherwise return empty list.
    try:
        rows = await conn.fetch("SELECT user_id, category FROM alerts WHERE sku = $1", sku)
        return [dict(r) for r in rows]
    except Exception:
        return []


async def consume_loop():
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
                    payload_b = fields.get(b"payload") or fields.get("payload")
                    try:
                        payload = json.loads(payload_b) if isinstance(payload_b, (bytes, bytearray)) else payload_b
                    except Exception:
                        payload = payload_b

                    sku = payload.get("sku")
                    store = payload.get("store")

                    # Basic filtering
                    if payload.get("in_stock") is False:
                        await redis.xack(STREAM, GROUP, msg_id)
                        continue

                    # Persist to timeseries
                    try:
                        async with ts_pool.acquire() as conn:
                            await insert_price_history(conn, payload)

                        # Build window and score
                        async with ts_pool.acquire() as conn:
                            recent = await fetch_recent_prices(conn, sku, store, limit=20)
                        window = np.array(recent[::-1]) if recent else np.array([])
                        score = ml_detector.score_prices(window)

                        # If anomaly, handle monetization and publish
                        if score > ANOMALY_THRESHOLD:
                            # Find users who have alerts for this SKU
                            async with pg_pool.acquire() as conn:
                                alerting = await find_alerting_users(conn, sku)
                                # Upsert aggregated analytics for each alert (no PII stored)
                                bucket = compute_price_bucket(float(payload.get("price")))
                                for a in alerting:
                                    # category may be available from alert row
                                    category = a.get("category") or "unknown"
                                    await upsert_retailer_analytics(conn, store, category, bucket, delta_count=1, delta_velocity=1.0)

                            # Publish confirmed deal (after DB writes)
                            await redis.xadd(
                                "stream:confirmed_deals",
                                {"payload": {"sku": sku, "store": store, "price": payload.get("price"), "timestamp": payload.get("timestamp"), "anomaly_score": score}},
                            )

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
    return {"status": "ok"}
