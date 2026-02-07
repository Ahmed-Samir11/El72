"""
Playwright engine — fallback crawler.

Wraps the existing EL72 Playwright-based scrapers (services/scraper/)
behind the same interface as Crawl4AIEngine.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Make the legacy scraper package importable
_SCRAPER_DIR = Path(__file__).resolve().parents[3] / "services" / "scraper"
if str(_SCRAPER_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRAPER_DIR))


class PlaywrightEngine:
    """
    CrawlerEngine fallback using the battle-tested EL72 Playwright scrapers.

    The existing scrapers only return *one* product per search (first result).
    We call them once per store and return a singleton list.
    """

    def __init__(self) -> None:
        self._browser = None
        self._playwright = None

    async def _ensure_browser(self):
        if self._browser is not None:
            return
        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
        except Exception:
            logger.exception("Failed to launch Playwright browser")
            raise

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def search_and_extract(
        self,
        url: str,
        schema: type[BaseModel],
        *,
        store_id: str = "amazon_eg",
    ) -> list[dict]:
        """
        Use the legacy scraper to search for a product.

        *url* is expected to be a search query string (not a URL) when
        coming from the crawl manager fallback path.

        Returns a list of raw dicts (usually length 0 or 1).
        """
        try:
            from store_scrapers import ScraperFactory  # type: ignore[import-untyped]
        except ImportError:
            logger.error("Legacy scrapers not available on sys.path")
            return []

        scraper = ScraperFactory.get_scraper(store_id)
        if scraper is None:
            logger.warning("No Playwright scraper for store %s", store_id)
            return []

        await self._ensure_browser()
        page = await self._browser.new_page()

        try:
            result = await scraper.scrape(page, url, canonical_product_id="search")
            if result is None:
                return []
            return [
                {
                    "name": result.title or "Unknown",
                    "price": result.price,
                    "currency": result.currency,
                    "image_url": result.image_url,
                    "product_url": result.url,
                    "delivery_estimate": None,
                    "rating": None,
                    "review_count": None,
                    "in_stock": result.in_stock,
                    "variants": [],
                }
            ]
        except Exception:
            logger.exception("Playwright scrape failed for %s", url)
            return []
        finally:
            await page.close()
