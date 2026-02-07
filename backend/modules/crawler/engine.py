"""
Crawl4AI engine — primary crawler.

Wraps AsyncWebCrawler + LLMExtractionStrategy behind the CrawlerEngine
interface so the rest of the app never talks to Crawl4AI directly.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from pydantic import BaseModel

from backend.config import get_settings

logger = logging.getLogger(__name__)


class Crawl4AIEngine:
    """
    CrawlerEngine implementation backed by Crawl4AI.

    Uses LLMExtractionStrategy with GPT-4o-mini to extract structured
    product data from any e-commerce search-results page.
    """

    def __init__(self) -> None:
        self._crawler = None

    # ------------------------------------------------------------------
    async def _ensure_crawler(self):
        if self._crawler is not None:
            return
        from crawl4ai import AsyncWebCrawler, BrowserConfig

        cfg = BrowserConfig(headless=True, verbose=False)
        self._crawler = AsyncWebCrawler(config=cfg)
        await self._crawler.__aenter__()

    async def close(self) -> None:
        if self._crawler:
            await self._crawler.__aexit__(None, None, None)
            self._crawler = None

    # ------------------------------------------------------------------
    async def search_and_extract(
        self,
        url: str,
        schema: type[BaseModel],
        *,
        max_products: int = 8,
    ) -> list[dict]:
        """
        Crawl *url* and use an LLM to extract a list of products
        matching *schema*.

        Returns a list of raw dicts (one per product).
        """
        settings = get_settings()
        await self._ensure_crawler()

        from crawl4ai import CrawlerRunConfig, CacheMode, LLMConfig
        from crawl4ai import LLMExtractionStrategy

        llm_strategy = LLMExtractionStrategy(
            llm_config=LLMConfig(
                provider=settings.crawl4ai_llm_provider,
                api_token=settings.openai_api_key,
            ),
            schema=schema.model_json_schema(),
            extraction_type="schema",
            instruction=(
                f"Extract up to {max_products} products from this e-commerce search "
                "results page. For EACH product, these fields are REQUIRED:\n"
                "\n"
                "1. name: the full product title as displayed\n"
                "2. price: numeric price ONLY (no currency symbol, no commas). REQUIRED.\n"
                "3. currency: the currency code shown on the page (USD, EGP, AED, etc.)\n"
                "4. product_url: the FULL absolute URL to the product detail page (must start with http). REQUIRED — this is the link a user would click to see the product.\n"
                "5. delivery_estimate: delivery/shipping text exactly as shown (e.g. 'Free delivery by Thu', 'Delivers in 3-5 days', 'Get it by Feb 12'). If not visible, set to null.\n"
                "6. variants: list of product variants visible on the listing — sizes, colors, pack counts, quantities. E.g. ['Pack of 12', 'Pack of 24'] or ['Size M', 'Size L']. If none shown, return empty array [].\n"
                "7. rating: numeric star rating (e.g. 4.5). Null if not shown.\n"
                "8. review_count: number of reviews as integer. Null if not shown.\n"
                "9. in_stock: boolean — true if available, false if out of stock.\n"
                "10. image_url: always set to null.\n"
                "\n"
                "Return ONLY a valid JSON array of product objects. No markdown, no explanation."
            ),
            chunk_token_threshold=2000,
            overlap_rate=0.05,
            apply_chunking=True,
            input_format="fit_markdown",
            extra_args={"temperature": 0.0, "max_tokens": 2000},
        )

        run_config = CrawlerRunConfig(
            extraction_strategy=llm_strategy,
            cache_mode=CacheMode.BYPASS,
        )

        try:
            result = await self._crawler.arun(url=url, config=run_config)

            if not result.success:
                logger.warning("Crawl4AI failed for %s: %s", url, result.error_message)
                return []

            raw = result.extracted_content
            if not raw:
                return []

            data = json.loads(raw)
            if isinstance(data, dict):
                # Some schemas wrap in an object
                data = data.get("products", data.get("items", [data]))
            if isinstance(data, list):
                return data[:max_products]
            return [data]

        except Exception:
            logger.exception("Crawl4AI extraction error for %s", url)
            return []
