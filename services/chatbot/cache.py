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

Cached payloads are copies of JSON-safe primitives only. A cached entry is
shared by every later search of that store, so it must never alias a caller's
list and must never carry one session's ``result_id``/``position`` into another.
"""

import copy
import hashlib
import json
import logging
import os
import time
from collections import OrderedDict
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Tunables; overridable through the environment for the container.
CACHE_TTL_SECONDS = float(os.getenv("CACHE_TTL_SECONDS", "900"))
CACHE_NEGATIVE_TTL_SECONDS = float(os.getenv("CACHE_NEGATIVE_TTL_SECONDS", "120"))
CACHE_MAX_ENTRIES = int(os.getenv("CACHE_MAX_ENTRIES", "256"))
# Products per cached entry. A store page can list hundreds of items; the
# service only ever shows a handful, and the DB mirror would otherwise grow
# with page size rather than with demand.
CACHE_MAX_PRODUCTS = int(os.getenv("CACHE_MAX_PRODUCTS", "40"))
# Rows are swept periodically rather than on every write.
CACHE_SWEEP_EVERY_WRITES = 20

# Fields that belong to one session's rendering of a result. They are
# regenerated per session in main.py, so a cached payload must not carry them.
_SESSION_ONLY_FIELDS = frozenset({"result_id", "position"})

# Separator that cannot appear in a store id or a normalized query, so a
# store id containing "|" can never forge another entry's key.
_KEY_SEPARATOR = "\x1f"


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
    whitespace, trailing punctuation, ``40000.0`` vs ``40000``. The parts are
    joined with a separator that cannot occur in them and then hashed, so no
    combination of store id and query can collide with another entry's key.

    The key deliberately has no locale or currency part: every store id here
    names one Egyptian storefront whose pages price in EGP, so ``store_id``
    already carries those dimensions. If a store is ever added with per-country
    variants, its id must encode the variant, not the query.

    Returns:
        The hex digest used as ``chat_query_cache.cache_key``.
    """
    normalized_store = " ".join((store_id or "").lower().split())
    normalized_query = " ".join((query or "").lower().split()).strip(" -,:;")
    bounds = (
        f"{min_price:g}" if min_price is not None else "-",
        f"{max_price:g}" if max_price is not None else "-",
    )
    raw = _KEY_SEPARATOR.join([normalized_store, normalized_query, *bounds])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    """[value] reduced to what JSON can carry.

    Store extraction can hand back ``Decimal`` prices or date objects; those
    would make the cache write fail and the whole entry fall back to a crawl.
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Decimal):
        try:
            return float(value)
        except (ValueError, OverflowError):
            return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


def _normalize_products(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A detached, JSON-safe copy of [products], capped at [CACHE_MAX_PRODUCTS].

    Session-only fields are dropped: the chatbot service mints a fresh row id
    per session, and a cached id from another session would address a row that
    session has no claim on.
    """
    normalized: List[Dict[str, Any]] = []
    for product in products[:CACHE_MAX_PRODUCTS]:
        if not isinstance(product, dict):
            continue
        normalized.append(
            {
                str(key): _json_safe(value)
                for key, value in product.items()
                if key not in _SESSION_ONLY_FIELDS
            }
        )
    return normalized


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
        # The first DB-backed search of a process sweeps what the previous
        # process left behind, instead of waiting for 20 writes.
        self._swept = db_session_factory is None

    def get(self, key: str) -> Optional[List[Dict[str, Any]]]:
        """Cached products for [key], or ``None`` when nothing is cached.

        Counts a hit only for a real cache read, so the metrics exposed on
        ``/metrics`` reflect the store-level cache, not the first search of a
        process.

        Returns:
            A detached list; mutating it cannot corrupt the cached entry.
        """
        self._sweep_once()

        cached = self._memory.get(key)
        if cached is not None:
            self.hits += 1
            return copy.deepcopy(cached)

        stored, remaining_ttl = self._db_lookup(key)
        if stored is not None:
            # Promote with the DB row's own remaining life: a negative entry
            # must not gain the full positive TTL just by being re-read.
            self._memory.set(key, stored, remaining_ttl)
            self.hits += 1
            return list(stored)

        self.misses += 1
        return None

    def set(self, key: str, store_id: str, products: List[Dict[str, Any]]) -> None:
        """Cache [products] for [key]; an empty list is a negative entry."""
        entry = _normalize_products(products)
        ttl = self.negative_ttl_seconds if not entry else self.ttl_seconds
        self._memory.set(key, copy.deepcopy(entry), ttl)
        self._writes += 1
        if self._writes % CACHE_SWEEP_EVERY_WRITES == 0:
            self._delete_expired()
        if self._db_session_factory is None:
            return
        self._db_store(key, store_id, entry, ttl)

    # -- database mirror ----------------------------------------------------

    def _sweep_once(self) -> None:
        """Sweep expired rows once per process, on the first DB-backed read."""
        if self._swept:
            return
        self._swept = True
        self._delete_expired()

    def _db_lookup(self, key: str) -> tuple:
        """Read a live (unexpired) entry from ``chat_query_cache``.

        Returns:
            ``(products, remaining_ttl_seconds)`` or ``(None, 0.0)``.
        """
        if self._db_session_factory is None:
            return None, 0.0
        now = time.time()
        try:
            with self._db_session_factory() as db:
                row = db.execute(
                    text(
                        "SELECT results, expires_at_epoch FROM chat_query_cache "
                        "WHERE cache_key = :cache_key AND expires_at_epoch > :now"
                    ),
                    {"cache_key": key, "now": now},
                ).fetchone()
            if row is None:
                return None, 0.0
            payload = row.results
            if isinstance(payload, str):
                payload = json.loads(payload)
            remaining = float(row.expires_at_epoch) - now
            return list(payload), max(0.0, min(remaining, self.ttl_seconds))
        except Exception as exc:  # noqa: BLE001 - a cache read must never fail a search
            logger.warning("chat_query_cache read failed: %s", exc)
            return None, 0.0

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
                    text(
                        "DELETE FROM chat_query_cache " "WHERE expires_at_epoch < :now"
                    ),
                    {"now": time.time()},
                )
                db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("chat_query_cache sweep failed: %s", exc)
