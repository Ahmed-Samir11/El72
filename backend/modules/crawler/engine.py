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
                "results page. For each product return: name, price (number only), "
                "currency, image_url, product_url (href), delivery_estimate, "
                "rating, review_count, in_stock (boolean), variants. "
                "Return ONLY a JSON array of objects."
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
