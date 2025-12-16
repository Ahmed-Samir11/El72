from __future__ import annotations

import json
import asyncio
from typing import Any, Dict, Optional, Iterable

import redis.asyncio as aioredis
from redis.exceptions import ResponseError


class RedisStreamClient:
    """Async singleton wrapper for Redis Streams used across services.

    Responsibilities:
    - Create consumer groups idempotently
    - XADD events (JSON-encoded)
    - XREADGROUP and XACK

    Usage:
        client = await RedisStreamClient.create(url=REDIS_URL)
        await client.ensure_group('stream:price_ingest', 'cg_analyzer')
        await client.xadd('stream:price_ingest', {'payload': json.dumps(payload)})
    """

    _instance: Optional["RedisStreamClient"] = None

    def __init__(self, redis: aioredis.Redis):
        """Initialize the client with an active `aioredis.Redis` connection.

        Parameters
        - `redis`: an instance of `redis.asyncio.Redis` already configured.
        """
        self._redis = redis

    @classmethod
    async def create(cls, url: str, password: Optional[str] = None) -> "RedisStreamClient":
        """Create or return the singleton instance.

        Parameters
        - `url`: Redis connection URL (e.g., `redis://host:6379`).
        - `password`: Optional Redis password.

        Returns
        - `RedisStreamClient` singleton instance. Raises if connection `PING` fails.
        """
        if cls._instance is None:
            redis = aioredis.from_url(url, password=password, decode_responses=False)
            # Test connection
            await redis.ping()
            cls._instance = cls(redis)
        return cls._instance

    @property
    def redis(self) -> aioredis.Redis:
        """Return the underlying `redis.asyncio.Redis` instance."""
        return self._redis

    async def ensure_group(self, stream: str, group: str, mkstream: bool = True) -> None:
        """Ensure a consumer group exists for a stream.

        This is idempotent: if the group already exists the error is ignored.

        Parameters
        - `stream`: Redis stream key
        - `group`: consumer group name
        - `mkstream`: whether to create the stream if it does not exist
        """
        try:
            await self._redis.xgroup_create(stream, group, id="$", mkstream=mkstream)
        except ResponseError as e:
            # Group already exists -> ignore
            if "BUSYGROUP" in str(e):
                return
            raise

    async def xadd(self, stream: str, fields: Dict[str, Any], maxlen: Optional[int] = None) -> str:
        """Push a message to `stream` with `fields` encoded as bytes.

        Non-bytes values are JSON-serialized. Returns the Redis message id.

        Parameters
        - `stream`: stream key to XADD to
        - `fields`: mapping of field->value
        - `maxlen`: optional max length for trimming the stream
        """
        # Encode non-bytes values as JSON strings
        encoded: Dict[str, bytes] = {}
        for k, v in fields.items():
            if isinstance(v, (bytes, bytearray)):
                encoded[k] = bytes(v)
            elif isinstance(v, str):
                encoded[k] = v.encode()
            else:
                encoded[k] = json.dumps(v, default=str).encode()

        msg_id = await self._redis.xadd(stream, encoded, maxlen=maxlen)
        return msg_id

    async def xreadgroup(
        self,
        group: str,
        consumer: str,
        streams: Dict[str, str],
        count: int = 1,
        block: int = 0,
    ) -> Dict[str, Iterable[tuple]]:
        """Read messages for `consumer` from `group` using XREADGROUP.

        Parameters
        - `group`: consumer group name
        - `consumer`: consumer id
        - `streams`: mapping stream->id (e.g. {'stream:price_ingest': '>'})
        - `count`: max number of messages
        - `block`: block milliseconds (0 = no block)

        Returns the raw XREADGROUP result.
        """
        result = await self._redis.xreadgroup(group, consumer, streams=streams, count=count, block=block)
        return result

    async def xack(self, stream: str, group: str, message_id: str) -> int:
        """Acknowledge a message id in `stream` for `group`.

        Returns the number of messages acknowledged (0 or 1).
        """
        return await self._redis.xack(stream, group, message_id)

    async def close(self) -> None:
        """Close the underlying Redis connection cleanly."""
        await self._redis.close()
