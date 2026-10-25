"""Tests for chatbot search-result caching (in-process TTL/LRU + DB mirror)."""

import time

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from services.chatbot.cache import (
    SearchResultCache,
    TTLLRUCache,
    make_cache_key,
)

# ---------------------------------------------------------------------------
# In-process cache
# ---------------------------------------------------------------------------


def test_ttl_lru_cache_expires_entries():
    """An entry older than its TTL is gone, not stale-served."""
    cache = TTLLRUCache(ttl_seconds=0.05, max_entries=8)
    cache.set("k", [{"title": "Laptop"}])
    assert cache.get("k") is not None

    time.sleep(0.06)
    assert cache.get("k") is None


def test_ttl_lru_cache_evicts_the_least_recently_used():
    """A long chat session must not grow the cache without bound."""
    cache = TTLLRUCache(ttl_seconds=60, max_entries=2)
    cache.set("a", [1])
    cache.set("b", [2])
    # Reading "a" makes "b" the oldest entry.
    assert cache.get("a") == [1]
    cache.set("c", [3])

    assert cache.get("b") is None
    assert cache.get("a") == [1]
    assert cache.get("c") == [3]
    assert len(cache) == 2


def test_ttl_lru_cache_clear_forgets_everything():
    cache = TTLLRUCache()
    cache.set("k", [1])
    cache.clear()
    assert cache.get("k") is None
    assert len(cache) == 0


# ---------------------------------------------------------------------------
# Cache keys
# ---------------------------------------------------------------------------


def test_make_cache_key_normalizes_the_query():
    """Case, spacing and trailing punctuation must not split the cache."""
    assert make_cache_key("amazon_eg", "Gaming  Laptop,") == make_cache_key(
        "amazon_eg", "gaming laptop"
    )


def test_make_cache_key_separates_price_windows():
    """A refined search ("under 12k" then "under 10k") is a different query."""
    base = make_cache_key("amazon_eg", "laptop")
    assert make_cache_key("amazon_eg", "laptop", max_price=12000) != base
    assert make_cache_key("amazon_eg", "laptop", max_price=10000) != make_cache_key(
        "amazon_eg", "laptop", max_price=12000
    )
    # 10000.0 and 10000 are the same window.
    assert make_cache_key("amazon_eg", "laptop", max_price=10000.0) == make_cache_key(
        "amazon_eg", "laptop", max_price=10000
    )
    # Different stores never share an entry.
    assert make_cache_key("jiji", "laptop") != make_cache_key("amazon_eg", "laptop")


# ---------------------------------------------------------------------------
# Search cache, with and without the database mirror
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session_factory(tmp_path):
    """A SQLite stand-in for the chat_query_cache table."""
    engine = create_engine(f"sqlite:///{tmp_path / 'query_cache.db'}")
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    db.execute(
        text(
            "CREATE TABLE chat_query_cache ("
            "cache_key TEXT NOT NULL UNIQUE, "
            "store_id TEXT NOT NULL, "
            "results TEXT NOT NULL, "
            "created_at TIMESTAMP, "
            "expires_at_epoch REAL NOT NULL)"
        )
    )
    db.commit()
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def test_cache_records_a_miss_then_a_hit():
    cache = SearchResultCache()
    key = make_cache_key("amazon_eg", "laptop", max_price=60000)

    assert cache.get(key) is None
    assert cache.misses == 1

    cache.set(key, "amazon_eg", [{"title": "Lenovo LOQ", "price": 55000.0}])
    cached = cache.get(key)

    assert cached == [{"title": "Lenovo LOQ", "price": 55000.0}]
    assert cache.hits == 1


def test_empty_results_are_cached_with_a_shorter_ttl():
    """A store that had nothing stays cheap without being frozen forever."""
    cache = SearchResultCache(negative_ttl_seconds=0.05)
    key = make_cache_key("jiji", "gaming laptop")

    cache.set(key, "jiji", [])
    assert cache.get(key) == []

    time.sleep(0.06)
    assert cache.get(key) is None


def test_warm_results_survive_a_restart(db_session_factory):
    """The DB mirror is what makes a container restart cheap for the user."""
    writing = SearchResultCache(db_session_factory)
    key = make_cache_key("amazon_eg", "laptop", max_price=60000)
    writing.set(key, "amazon_eg", [{"title": "Acer Nitro V", "price": 55799.0}])

    reading = SearchResultCache(db_session_factory)
    assert reading.get(key) == [{"title": "Acer Nitro V", "price": 55799.0}]
    assert reading.hits == 1


def test_an_expired_db_row_is_not_served(db_session_factory):
    """A cache row past its expiry must be treated as absent, not stale."""
    with db_session_factory() as db:
        db.execute(
            text(
                "INSERT INTO chat_query_cache "
                "(cache_key, store_id, results, expires_at_epoch) "
                "VALUES (:k, :s, :r, :e)"
            ),
            {
                "k": make_cache_key("jiji", "monitor"),
                "s": "jiji",
                "r": '[{"title": "Stale"}]',
                "e": time.time() - 60,
            },
        )
        db.commit()

    cache = SearchResultCache(db_session_factory)
    assert cache.get(make_cache_key("jiji", "monitor")) is None


def test_expired_rows_are_swept(db_session_factory):
    """The table is swept periodically so it cannot grow without bound."""
    with db_session_factory() as db:
        for age, key in ((-60, "old|monitor"), (9999, "fresh|monitor")):
            db.execute(
                text(
                    "INSERT INTO chat_query_cache "
                    "(cache_key, store_id, results, expires_at_epoch) "
                    "VALUES (:k, :s, :r, :e)"
                ),
                {
                    "k": key,
                    "s": "jiji",
                    "r": "[]",
                    "e": time.time() + age,
                },
            )
        db.commit()

    cache = SearchResultCache(db_session_factory)
    cache._delete_expired()

    with db_session_factory() as db:
        remaining = db.execute(
            text("SELECT cache_key FROM chat_query_cache")
        ).fetchall()
    assert [row.cache_key for row in remaining] == ["fresh|monitor"]
