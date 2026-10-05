"""Staging-token store for the Paymob card flow (Feature 1).

A staging token is bound to the user who requested it and expires after
STAGING_TTL_SECONDS (15 minutes, plan 1.2). It is SINGLE-USE: ``pop`` is an
atomic get-and-delete, so a concurrent replay can never consume the same
token twice (plan 1.4).

The store also provides an atomic per-user counter (``incr``) used for the
per-hour rate limits on /payment/start (plan 1.9).

Production uses Redis (SET/GETDEL/INCR). Tests inject ``InMemoryStagingStore``
via :func:`set_store`.
"""

import os
from typing import Optional, Protocol

STAGING_TTL_SECONDS = 900  # 15 minutes (plan 1.2)

_KEY_PREFIX = "paymob:staging:"


class StagingStore(Protocol):
    """Interface for staging-token storage and rate-limit counters."""

    def set(
        self, token: str, user_id: str, ttl_seconds: int = STAGING_TTL_SECONDS
    ) -> None:
        """Bind a staging token to a user with a TTL."""
        ...

    def pop(self, token: str) -> Optional[str]:
        """Atomically fetch AND delete the token; returns the bound user id.

        Returns ``None`` if the token is unknown or already consumed.
        """
        ...

    def get(self, token: str) -> Optional[str]:
        """Non-destructive lookup of the bound user id (no delete).

        Used to validate ownership BEFORE consuming, so a cross-user
        rejection does not burn the legitimate owner's token.
        """
        ...

    def incr(self, key: str, ttl_seconds: int) -> int:
        """Atomically increment a counter (setting its TTL on first use)."""
        ...


class RedisStagingStore:
    """Redis-backed staging store (production)."""

    def __init__(self, url: str):
        # Lazy import so the redis package is only required when the
        # production store is actually constructed (not at module load time,
        # which would break test collection when redis is not installed).
        import redis

        self._redis = redis.from_url(url, decode_responses=True)

    def set(
        self, token: str, user_id: str, ttl_seconds: int = STAGING_TTL_SECONDS
    ) -> None:
        self._redis.set(_KEY_PREFIX + token, user_id, ex=ttl_seconds)

    def pop(self, token: str) -> Optional[str]:
        # GETDEL is atomic: exactly one concurrent caller can win the token.
        return self._redis.getdel(_KEY_PREFIX + token)

    def get(self, token: str) -> Optional[str]:
        # Non-destructive: a cross-user check must not delete the owner's token.
        return self._redis.get(_KEY_PREFIX + token)

    def incr(self, key: str, ttl_seconds: int) -> int:
        count = self._redis.incr(key)
        if count == 1:
            self._redis.expire(key, ttl_seconds)
        return count


class InMemoryStagingStore:
    """In-memory staging store (tests)."""

    def __init__(self):
        self._tokens: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    def set(
        self, token: str, user_id: str, ttl_seconds: int = STAGING_TTL_SECONDS
    ) -> None:
        self._tokens[token] = user_id

    def pop(self, token: str) -> Optional[str]:
        return self._tokens.pop(token, None)

    def get(self, token: str) -> Optional[str]:
        return self._tokens.get(token)

    def incr(self, key: str, ttl_seconds: int) -> int:
        self._counters[key] = self._counters.get(key, 0) + 1
        return self._counters[key]


_store: Optional[StagingStore] = None


def get_staging_store() -> StagingStore:
    """Lazy singleton. Production builds a Redis store from REDIS_URL; tests
    inject an in-memory store via :func:`set_store`."""
    global _store
    if _store is None:
        _store = RedisStagingStore(os.getenv("REDIS_URL", "redis://localhost:6379"))
    return _store


def set_store(store: Optional[StagingStore]) -> None:
    """Replace the store instance (test hook)."""
    global _store
    _store = store
