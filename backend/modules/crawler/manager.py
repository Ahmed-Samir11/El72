"""
Crawl Manager — orchestrates multi-store product search.

Tries Crawl4AI first; falls back to Playwright scrapers per-store.
Pushes partial results as each store completes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional, Awaitable

from backend.models.product import Product
from backend.modules.crawler.engine import Crawl4AIEngine
from backend.modules.crawler.playwright_engine import PlaywrightEngine
from backend.modules.crawler.adapters.amazon import AmazonAdapter
from backend.modules.crawler.adapters.noon import NoonAdapter
from backend.modules.crawler.adapters.jumia import JumiaAdapter
from backend.modules.crawler.adapters.base import RetailerAdapter

logger = logging.getLogger(__name__)

# ── Adapter registry (Lego: snap adapters in/out here) ──────────────
ADAPTERS: dict[str, RetailerAdapter] = {
    "amazon": AmazonAdapter(),
    "noon": NoonAdapter(),
    "jumia": JumiaAdapter(),
}

# Mapping from adapter key → Playwright store_id (for fallback)
_PW_STORE_IDS: dict[str, str] = {
    "amazon": "amazon_eg",
    "noon": "noon",
    "jumia": "jumia",
}


class CrawlManager:
    """
    High-level API consumed by the tool endpoints.

    Usage:
        mgr = CrawlManager()
        products = await mgr.search("bulk snacks party")
        await mgr.close()
    """

    def __init__(self) -> None:
        self._crawl4ai = Crawl4AIEngine()
        self._playwright = PlaywrightEngine()

    async def close(self) -> None:
        await self._crawl4ai.close()
        await self._playwright.close()

    # ------------------------------------------------------------------
    async def search(
        self,
        query: str,
        category: str = "",
        stores: list[str] | None = None,
        on_store_done: Optional[Callable[[str, list[Product]], Awaitable[None]]] = None,
    ) -> list[Product]:
        """
        Search across multiple stores in parallel.

        Args:
            query: free-text search query
            category: shopping category label (e.g. "snacks")
            stores: subset of adapter keys; None = all
            on_store_done: optional async callback fired when each store finishes

        Returns:
            Flattened list of normalised Products from all stores.
        """
        store_keys = stores or list(ADAPTERS.keys())
        tasks = [
            self._search_store(key, query, category, on_store_done)
            for key in store_keys
            if key in ADAPTERS
        ]
        results = await asyncio.gather(*tasks)
        return [p for batch in results for p in batch]

    # ------------------------------------------------------------------
    async def _search_store(
        self,
        store_key: str,
        query: str,
        category: str,
        on_done: Optional[Callable[[str, list[Product]], Awaitable[None]]],
    ) -> list[Product]:
        adapter = ADAPTERS[store_key]
        url = adapter.build_search_url(query)
        products: list[Product] = []

        # ── Primary: Crawl4AI ──
        try:
            raw_items = await self._crawl4ai.search_and_extract(
                url, adapter.get_product_schema()
            )
            if raw_items:
                products = [adapter.normalize(r, category=category) for r in raw_items]
                logger.info(
                    "%s via Crawl4AI: %d products for '%s'",
                    adapter.name, len(products), query,
                )
        except Exception:
            logger.warning("%s Crawl4AI failed, trying Playwright fallback", adapter.name)

        # ── Fallback: Playwright ──
        if not products:
            pw_store = _PW_STORE_IDS.get(store_key)
            if pw_store:
                try:
                    raw_items = await self._playwright.search_and_extract(
                        query, adapter.get_product_schema(), store_id=pw_store
                    )
                    products = [adapter.normalize(r, category=category) for r in raw_items]
                    logger.info(
                        "%s via Playwright: %d products for '%s'",
                        adapter.name, len(products), query,
                    )
                except Exception:
                    logger.exception("%s Playwright fallback also failed", adapter.name)

        if on_done:
            await on_done(store_key, products)

        return products
