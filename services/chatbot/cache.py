"""Result caching for chatbot search.

A search costs one crawl (and possibly one LLM extraction) per store, so the
same question asked twice in a session used to cost the same as the first one.
Results are therefore cached per ``(store_id, query, price bounds)``:

* in-process, with a TTL and an LRU bound, which covers the common case of a
  user refining a search ("under 12k?" then "under 10k?");
* mirrored into the ``chat_query_cache`` table when a database is configured,
  so warm results survive a container restart.

Empty results are cached too, with a shorter TTL: a store that returned nothing
for a query will not have started returning something seconds later, and a
blocked store should stop being re-crawled on every message.
"""

import json
import logging
import os
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Tunables; overridable through the environment for the container.
CACHE_TTL_SECONDS = float(os.getenv("CACHE_TTL_SECONDS", "900"))
CACHE_NEGATIVE_TTL_SECONDS = float(os.getenv("CACHE_NEGATIVE_TTL_SECONDS", "120"))
CACHE_MAX_ENTRIES = int(os.getenv("CACHE_MAX_ENTRIES", "256"))


class TTLLRUCache:
    """Bounded in-process cache with per-entry expiry.

    Deliberately dependency-free (no ``cachetools``): the chatbot image pins
    few packages and this is ~30 lines. Not thread-safe by design — the service
    is a single asyncio event loop.
    """

    def __init__(
        self,
        ttl_seconds: float = CACHE_TTL_SECONDS,
        max_entries: int = CACHE_MAX_ENTRIES,
    ):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max(1, max_entries)
        self._entries: "OrderedDict[str, tuple]" = OrderedDict()

    def get(self, key: str) -> Any:
        """The cached value for [key], or ``None`` when absent or expired."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return value

    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        """Store [value] under [key] with an optional per-entry [ttl_seconds]."""
        ttl = self.ttl_seconds if ttl_seconds is None else ttl_seconds
        self._entries[key] = (time.monotonic() + ttl, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        """Forget everything (used by tests and store cooldown resets)."""
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


def make_cache_key(
    store_id: str,
    query: str,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
) -> str:
    """A stable key for one store's search.

    Normalized so cosmetic differences hit the same entry: case, repeated
    whitespace, trailing punctuation, ``40000.0`` vs ``40000``.
    """
    normalized_query = " ".join((query or "").lower().split()).strip(" -,:;")
    bounds = (
        f"{min_price:g}" if min_price is not None else "-",
        f"{max_price:g}" if max_price is not None else "-",
    )
    return f"{store_id}|{normalized_query}|{bounds[0]}|{bounds[1]}"


class SearchResultCache:
    """Per-store search cache: in-process LRU plus an optional DB mirror."""

    def __init__(
        self,
        db_session_factory=None,
        ttl_seconds: float = CACHE_TTL_SECONDS,
        negative_ttl_seconds: float = CACHE_NEGATIVE_TTL_SECONDS,
        max_entries: int = CACHE_MAX_ENTRIES,
    ):
        self._memory = TTLLRUCache(ttl_seconds, max_entries)
        self._db_session_factory = db_session_factory
        self.ttl_seconds = ttl_seconds
        self.negative_ttl_seconds = negative_ttl_seconds
        self.hits = 0
        self.misses = 0
        self._writes = 0

    def get(self, key: str) -> Optional[List[Dict[str, Any]]]:
        """Cached products for [key], or ``None`` when nothing is cached.

        Counts a hit only for a real cache read, so the metrics exposed on
        ``/metrics`` reflect the store-level cache, not the first search of a
        process.
        """
        cached = self._memory.get(key)
        if cached is not None:
            self.hits += 1
            return cached

        stored = self._db_lookup(key)
        if stored is not None:
            self._memory.set(key, stored, self.ttl_seconds)
            self.hits += 1
            return stored

        self.misses += 1
        return None

    def set(self, key: str, store_id: str, products: List[Dict[str, Any]]) -> None:
        """Cache [products] for [key]; an empty list is a negative entry."""
        ttl = self.negative_ttl_seconds if not products else self.ttl_seconds
        self._memory.set(key, products, ttl)
        self._writes += 1
        if self._writes % 20 == 0:
            self._delete_expired()
        if self._db_session_factory is None:
            return
        self._db_store(key, store_id, products, ttl)

    # -- database mirror ----------------------------------------------------

    def _db_lookup(self, key: str) -> Optional[List[Dict[str, Any]]]:
        """Read a live (unexpired) entry from ``chat_query_cache``."""
        if self._db_session_factory is None:
            return None
        try:
            with self._db_session_factory() as db:
                row = db.execute(
                    text(
                        "SELECT results FROM chat_query_cache "
                        "WHERE cache_key = :cache_key AND expires_at_epoch > :now"
                    ),
                    {"cache_key": key, "now": time.time()},
                ).fetchone()
            if row is None:
                return None
            payload = row.results
            if isinstance(payload, str):
                payload = json.loads(payload)
            return list(payload)
        except Exception as exc:  # noqa: BLE001 - a cache read must never fail a search
            logger.warning("chat_query_cache read failed: %s", exc)
            return None

    def _db_store(
        self, key: str, store_id: str, products: List[Dict[str, Any]], ttl: float
    ) -> None:
        """Upsert the entry; a cache write must never fail a search either."""
        now = time.time()
        try:
            with self._db_session_factory() as db:
                db.execute(
                    text(
                        "INSERT INTO chat_query_cache "
                        "(cache_key, store_id, results, expires_at_epoch) "
                        "VALUES (:cache_key, :store_id, :results, :expires) "
                        "ON CONFLICT (cache_key) DO UPDATE SET "
                        "results = EXCLUDED.results, "
                        "expires_at_epoch = EXCLUDED.expires_at_epoch"
                    ),
                    {
                        "cache_key": key,
                        "store_id": store_id,
                        "results": json.dumps(products),
                        "expires": now + ttl,
                    },
                )
                db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("chat_query_cache write failed: %s", exc)

    def _delete_expired(self) -> None:
        """Sweep stale DB rows so the table does not grow without bound."""
        if self._db_session_factory is None:
            return
        try:
            with self._db_session_factory() as db:
                db.execute(
                    text("DELETE FROM chat_query_cache WHERE expires_at_epoch < :now"),
                    {"now": time.time()},
                )
                db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("chat_query_cache sweep failed: %s", exc)
