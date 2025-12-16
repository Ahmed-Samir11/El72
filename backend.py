"""
Backend consumer for the Golden Path test.

Responsibilities:
- Ensure consumer group `cg_analyzer` exists for `stream:price_ingest`.
- Read messages with XREADGROUP, simulate historical price (2x current), detect >20% drop,
  then XADD an alert to `stream:confirmed_deals` and XACK the original message.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict

import redis
from redis.exceptions import ResponseError

STREAM = "stream:price_ingest"
CONFIRMED = "stream:confirmed_deals"
GROUP = "cg_analyzer"
CONSUMER = "analyzer-test-1"
REDIS_URL = "redis://localhost:6379/0"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backend")


def ensure_group(client: redis.Redis, stream: str, group: str) -> None:
    try:
        client.xgroup_create(stream, group, id="$", mkstream=True)
        logger.info("Created consumer group %s on %s", group, stream)
    except ResponseError as e:
        # BUSYGROUP -> already exists
        if "BUSYGROUP" in str(e):
            logger.info("Consumer group %s already exists", group)
        else:
            logger.exception("Error creating consumer group")
            raise


def process_message(fields: Dict[bytes, Any]) -> Dict[str, Any]:
    payload_b = fields.get(b"payload") or fields.get("payload")
    if isinstance(payload_b, (bytes, bytearray)):
        payload = json.loads(payload_b.decode())
    elif isinstance(payload_b, str):
        payload = json.loads(payload_b)
    else:
        payload = payload_b
    return payload


def run():
    r = redis.from_url(REDIS_URL)
    try:
        r.ping()
    except Exception:
        logger.exception("Cannot connect to Redis at %s", REDIS_URL)
        return

    ensure_group(r, STREAM, GROUP)

    logger.info("Starting consume loop (ctrl+c to stop)")
    while True:
        try:
            # block 5s to wait for messages
            res = r.xreadgroup(GROUP, CONSUMER, {STREAM: ">"}, count=1, block=5000)
            if not res:
                time.sleep(0.1)
                continue

            for stream_key, messages in res:
                for msg_id, fields in messages:
                    logger.info("Received %s %s", stream_key, msg_id)
                    try:
                        payload = process_message(fields)
                        current_price = float(payload.get("price"))
                        # Forced historical price = 2x current to simulate a big drop
                        historical = current_price * 2.0
                        drop_pct = (historical - current_price) / historical * 100.0
                        logger.info(
                            "Price check: current=%.2f historical=%.2f drop=%.1f%%",
                            current_price,
                            historical,
                            drop_pct,
                        )

                        if drop_pct > 20.0:
                            alert = {
                                "sku": payload.get("sku"),
                                "title": payload.get("title"),
                                "store": payload.get("store"),
                                "price": current_price,
                                "historical": historical,
                                "drop_pct": drop_pct,
                                "timestamp": int(time.time()),
                            }
                            try:
                                r.xadd(CONFIRMED, {"payload": json.dumps(alert)})
                                logger.info(
                                    "✅ DEAL DETECTED -> published to %s: %s",
                                    CONFIRMED,
                                    alert,
                                )
                            except Exception:
                                logger.exception("Failed to publish confirmed deal")

                        # ACK only after processing
                        r.xack(STREAM, GROUP, msg_id)
                        logger.info("ACKed %s", msg_id)
                    except Exception:
                        logger.exception("Failed to process message %s", msg_id)
                        # do not ack: leave message pending for manual inspection
        except KeyboardInterrupt:
            logger.info("Shutting down consumer")
            break
        except Exception:
            logger.exception("Consumer loop error; sleeping before retry")
            time.sleep(1)


if __name__ == "__main__":
    run()
