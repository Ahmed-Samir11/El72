"""Product search service for the chatbot.

Uses Crawl4AI with local LLM inference (LM Studio) to search for products
across all supported stores. The chatbot service uses Crawl4AI as a library
(not an import from the scraper service) to keep the service isolated.
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from crawl4ai import AsyncWebCrawler

from openai import AsyncOpenAI
from pydantic import BaseModel

try:
    from services.chatbot.arabic_nlp import (
        detect_language,
        parse_arabic_intent,
        translate_query_for_search,
    )
except ImportError:
    from arabic_nlp import (
        detect_language,
        parse_arabic_intent,
        translate_query_for_search,
    )

logger = logging.getLogger(__name__)

# Concurrency limit for multi-store search to avoid overwhelming the client.
MAX_CONCURRENT_STORES = 4
_search_semaphore = asyncio.Semaphore(MAX_CONCURRENT_STORES)

# LM Studio Configuration (OpenAI-compatible local endpoint)
LM_STUDIO_URL = os.getenv("LLM_BASE_URL", "http://host.docker.internal:8080/v1")
LM_STUDIO_MODEL = os.getenv("LLM_MODEL", "local-model")

# Crawl4AI Configuration
CRAWL_TIMEOUT = 30
CRAWL_WAIT_FOR = "networkidle"
MAX_TOKENS_EXTRACTION = 2000


# =============================================================================
# LM Studio Client
# =============================================================================


_llm_client: Optional[AsyncOpenAI] = None


def get_lm_studio_client() -> AsyncOpenAI:
    """Get the singleton AsyncOpenAI client configured for the LLM server."""
    global _llm_client
    if _llm_client is None:
        _llm_client = AsyncOpenAI(
            base_url=LM_STUDIO_URL, api_key="not-needed", timeout=60.0
        )
    return _llm_client


# =============================================================================
# Extraction Schemas (local copies for service isolation)
# =============================================================================


class SearchResultItem(BaseModel):
    """Schema for a single product in search results."""

    title: str
    url: str
    price: Optional[float] = None
    currency: str = "EGP"
    image_url: Optional[str] = None
    in_stock: Optional[bool] = True


class SearchResultsSchema(BaseModel):
    """Schema for extracting product listings from search results."""

    products: List[SearchResultItem] = []
    total_results: Optional[int] = None
    current_page: Optional[int] = None
    has_next_page: Optional[bool] = None


# =============================================================================
# Store Configuration
# =============================================================================


class StoreConfig:
    """Configuration for a single store scraper."""

    def __init__(
        self,
        store_id: str,
        store_name: str,
        base_url: str,
        search_url_pattern: str,
    ):
        self.store_id = store_id
        self.store_name = store_name
        self.base_url = base_url
        self.search_url_pattern = search_url_pattern

    def get_search_url(self, query: str) -> str:
        """Build the search URL for a product query."""
        encoded_query = quote_plus(query)
        return self.search_url_pattern.format(
            base_url=self.base_url, encoded_query=encoded_query
        )


# Supported stores for search. Mirrors the store list in services/api/main.py.
STORES: List[StoreConfig] = [
    StoreConfig(
        store_id="amazon_eg",
        store_name="Amazon Egypt",
        base_url="https://www.amazon.eg",
        search_url_pattern="{base_url}/s?k={encoded_query}",
    ),
    StoreConfig(
        store_id="noon",
        store_name="Noon Egypt",
        base_url="https://www.noon.com",
        search_url_pattern="{base_url}/egypt-en/search?search={encoded_query}",
    ),
    StoreConfig(
        store_id="jumia",
        store_name="Jumia Egypt",
        base_url="https://www.jumia.com.eg",
        search_url_pattern="{base_url}/search?q={encoded_query}",
    ),
    StoreConfig(
        store_id="elbadrgroup",
        store_name="ElBadr Group",
        base_url="https://elbadrgroup.com",
        search_url_pattern="{base_url}/index.php?route=product/search&search={encoded_query}",
    ),
    StoreConfig(
        store_id="2b_egypt",
        store_name="2B Egypt",
        base_url="https://www.2b.com.eg",
        search_url_pattern="{base_url}/search?q={encoded_query}",
    ),
    StoreConfig(
        store_id="sigma_computer",
        store_name="Sigma Computer",
        base_url="https://www.sigma-computer.com",
        search_url_pattern="{base_url}/en/search?s={encoded_query}",
    ),
    StoreConfig(
        store_id="egyprice",
        store_name="EgyPrice",
        base_url="https://egyprice.com",
        search_url_pattern="{base_url}/search?q={encoded_query}",
    ),
]


# =============================================================================
# Intent Parsing
# =============================================================================


def _parse_english_intent(message: str) -> Dict[str, Any]:
    """Parse a user message into a search query and optional price filter.

    Looks for price-related keywords (under, below, less than, max, etc.)
    followed by a number. Returns the query (message minus price filter)
    and an optional max_price.

    Examples:
        "gaming laptop under 50000 EGP"
            -> {"query": "gaming laptop", "max_price": 50000}
        "iPhone 15 Pro Max" -> {"query": "iPhone 15 Pro Max", "max_price": None}
        "Samsung TV below 30000" -> {"query": "Samsung TV", "max_price": 30000}
    """
    msg = message.strip()
    max_price: Optional[float] = None
    query = msg

    # Strip common English filler phrases so the search query targets the
    # actual product rather than conversational noise (e.g. "show me all 2k
    # monitors" -> "2k monitors"). Mirrors the Arabic filler stripping in
    # parse_arabic_intent.
    query = re.sub(
        r"^(?:show me all|show me|find me|find|i want to|i want|looking for|search for|search)\b\s*",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(r"\s+", " ", query).strip()

    # Price filter patterns (case-insensitive)
    patterns = [
        r"\bunder\s+([\d,]+)\s*(?:EGP)?\b",
        r"\bbelow\s+([\d,]+)\s*(?:EGP)?\b",
        r"\bless than\s+([\d,]+)\s*(?:EGP)?\b",
        r"\bmax\s+([\d,]+)\s*(?:EGP)?\b",
        r"\bmaximum\s+([\d,]+)\s*(?:EGP)?\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            price_str = match.group(1).replace(",", "")
            try:
                max_price = float(price_str)
            except ValueError:
                continue
            # Remove the matched price phrase from the query
            query = query[: match.start()] + query[match.end() :]
            query = re.sub(r"\s+", " ", query).strip()
            break

    # If no keyword pattern matched, check for a standalone number at the end
    if max_price is None:
        standalone = re.search(r"\b([\d,]+)\s*(?:EGP)?\s*$", query, re.IGNORECASE)
        if standalone:
            price_str = standalone.group(1).replace(",", "")
            try:
                max_price = float(price_str)
            except ValueError:
                pass
            else:
                query = query[: standalone.start()].strip()

    return {"query": query, "max_price": max_price}


def parse_intent(message: str) -> Dict[str, Any]:
    """Parse English or Egyptian Arabic search intent (regex fallback).

    Contract:
      - "query": The search query in English (what to send to stores).
      - "display_query": The user's original text (for display in UI).
      - "max_price": Optional float price ceiling.
      - "language": "ar" or "en".
    """
    language = detect_language(message)
    if language == "ar":
        result = parse_arabic_intent(message)
        display_query = result["query"]
        result["query"] = translate_query_for_search(result["query"])
        result["search_query"] = result["query"]
    else:
        result = _parse_english_intent(message)
        display_query = result["query"]
        result["search_query"] = result["query"]
    result["display_query"] = display_query
    result["language"] = language
    return result


# =============================================================================
# LLM-Based Intent Extraction
# =============================================================================

INTENT_EXTRACTION_PROMPT = """You are a product search assistant for an Egyptian e-commerce platform.

Given the user's message (which may be in Egyptian Arabic, English, or a mix), extract:
1. "query": The product search query in ENGLISH (translate if needed). Be specific (e.g. "27 inch 2K QHD monitor", not just "monitor").
2. "max_price": The maximum price in EGP as a number, or null if no price constraint.
3. "language": "ar" if the message is primarily Arabic, "en" if primarily English.

Respond with ONLY a JSON object: {"query": "...", "max_price": 12000, "language": "ar"}

Examples:
- "عايز شاشات 2k بسعر أقل من 12 ألف" → {"query": "2K monitor", "max_price": 12000, "language": "ar"}
- "gaming laptop under 50000" → {"query": "gaming laptop", "max_price": 50000, "language": "en"}
- "Samsung 27 inch 2K QHD" → {"query": "Samsung 27 inch 2K QHD monitor", "max_price": null, "language": "en"}
- "لابتوب جيمينج ب 30 ألف" → {"query": "gaming laptop", "max_price": 30000, "language": "ar"}
"""


async def llm_extract_intent(message: str) -> Optional[Dict[str, Any]]:
    """Use the LLM to extract search intent from a user message.

    Returns a dict with "query", "max_price", "language" keys,
    or None if the LLM call fails.
    """
    try:
        client = get_lm_studio_client()
        response = await client.chat.completions.create(
            model=LM_STUDIO_MODEL,
            messages=[
                {"role": "system", "content": INTENT_EXTRACTION_PROMPT},
                {"role": "user", "content": message},
            ],
            temperature=0.0,
            max_tokens=200,
        )
        raw = response.choices[0].message.content.strip()
        # Extract JSON from the response (handle markdown code blocks).
        if "```" in raw:
            raw = raw.split("```")[1].strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
        data = json.loads(raw)
        # Validate and coerce max_price.
        raw_price = data.get("max_price")
        max_price: Optional[float] = None
        if raw_price is not None:
            try:
                max_price = float(raw_price)
                if max_price < 0:
                    max_price = None
            except (ValueError, TypeError):
                max_price = None
        # Validate language.
        lang = data.get("language", "en")
        if lang not in ("ar", "en"):
            lang = "en"
        return {
            "query": data.get("query", ""),
            "max_price": max_price,
            "language": lang,
        }
    except Exception as e:
        logger.warning(f"LLM intent extraction failed: {e}")
        return None


# =============================================================================
# LLM Extraction Strategy
# =============================================================================


class LMStudioExtractionStrategy:
    """Custom extraction strategy that uses LM Studio for local inference."""

    def __init__(
        self,
        schema: dict,
        extraction_prompt: str,
        model: str = None,
        **kwargs,
    ):
        self.schema = schema
        self.extraction_prompt = extraction_prompt
        self.model = model or LM_STUDIO_MODEL
        self.client = get_lm_studio_client()

    async def extract(self, content: str, url: str = None) -> str:
        """Extract structured data from content using local LLM."""
        system_prompt = f"""{self.extraction_prompt}

Expected JSON schema:
{json.dumps(self.schema, indent=2)}

URL: {url or 'unknown'}
"""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Extract product information from this page content:\n\n"
                            f"{content[:8000]}"
                        ),
                    },
                ],
                max_tokens=MAX_TOKENS_EXTRACTION,
                temperature=0.1,
            )

            result = response.choices[0].message.content

            # Try to parse as JSON to validate
            try:
                parsed = json.loads(result)
                return json.dumps(parsed)
            except json.JSONDecodeError:
                import re as _re

                json_match = _re.search(r"\{[\s\S]*\}", result)
                if json_match:
                    return json_match.group()
                logger.warning(f"Could not parse LLM response as JSON: {result[:200]}")
                return result

        except Exception as e:
            logger.error(f"LM Studio extraction failed: {e}")
            raise


# =============================================================================
# Search Service
# =============================================================================


class ChatbotSearchService:
    """Searches for products across all supported stores using Crawl4AI."""

    def __init__(self):
        self.stores = STORES
        self._crawler: Optional[AsyncWebCrawler] = None

    async def _get_crawler(self) -> AsyncWebCrawler:
        """Get or create the async web crawler instance."""
        if self._crawler is None:
            self._crawler = AsyncWebCrawler(headless=True, verbose=False)
            await self._crawler.__aenter__()
        return self._crawler

    async def close(self):
        """Close the crawler and release resources."""
        if self._crawler:
            await self._crawler.__aexit__(None, None, None)
            self._crawler = None

    async def _crawl_page(self, url: str) -> Optional[str]:
        """Crawl a single page and return its content.

        Returns page content (HTML/text) or None if failed.
        """
        try:
            crawler = await self._get_crawler()
            result = await crawler.arun(
                url=url,
                timeout=CRAWL_TIMEOUT * 1000,
                wait_for=CRAWL_WAIT_FOR,
            )
            if result.success:
                return result.markdown or result.html
            else:
                logger.error(f"Crawl failed for {url}: {result.error_message}")
                return None
        except Exception as e:
            logger.error(f"Exception crawling {url}: {e}")
            return None

    async def _extract_search_results(
        self, query: str, store: StoreConfig
    ) -> Optional[SearchResultsSchema]:
        """Search for products on a specific store and extract results.

        Args:
            query: Product search query
            store: Store configuration

        Returns:
            Extracted search results or None if failed
        """
        search_url = store.get_search_url(query)
        content = await self._crawl_page(search_url)

        if not content:
            return None

        try:
            strategy = LMStudioExtractionStrategy(
                schema=SearchResultsSchema.model_json_schema(),
                extraction_prompt=SEARCH_RESULTS_EXTRACTION_PROMPT,
            )

            result_json = await strategy.extract(content, search_url)

            result_dict = json.loads(result_json)
            return SearchResultsSchema.model_validate(result_dict)

        except Exception as e:
            logger.error(
                f"Search extraction failed for {query} on {store.store_id}: {e}"
            )
            return None

    def _find_best_match(
        self, query: str, products: List[SearchResultItem]
    ) -> Optional[SearchResultItem]:
        """Find the best matching product from search results.

        Uses token overlap scoring.

        Args:
            query: Original search query
            products: List of search result items

        Returns:
            Best matching product or None
        """
        if not products:
            return None

        query_lower = query.lower()
        query_tokens = set(query_lower.split())

        best_score = -1
        best_product = None

        for product in products:
            title_lower = product.title.lower()
            title_tokens = set(title_lower.split())

            # Token overlap score
            token_hits = len(query_tokens & title_tokens)

            # Length bonus (shorter titles often more relevant)
            length_bonus = 1.0 / (1 + len(title_lower) / 100)

            # Phrase bonus (exact phrase match)
            phrase_bonus = 1.0 if query_lower in title_lower else 0.0

            score = token_hits + length_bonus + phrase_bonus

            if score > best_score:
                best_score = score
                best_product = product

        return best_product

    async def _search_one_store(
        self, query: str, store: StoreConfig
    ) -> Optional[Dict[str, Any]]:
        """Search a single store and return a result dict or None."""
        async with _search_semaphore:
            try:
                extracted = await self._extract_search_results(query, store)
                if not extracted or not extracted.products:
                    return None

                # Find the best matching product
                best = self._find_best_match(query, extracted.products)
                if not best:
                    return None

                # Resolve relative URLs
                product_url = best.url
                if not product_url.startswith("http"):
                    product_url = f"{store.base_url}{product_url}"

                return {
                    "store_id": store.store_id,
                    "store_name": store.store_name,
                    "title": best.title,
                    "price": best.price if best.price is not None else 0.0,
                    "currency": best.currency,
                    "url": product_url,
                    "image_url": best.image_url or "",
                    "in_stock": bool(best.in_stock),
                }
            except Exception as e:
                logger.error(f"Search failed for store {store.store_id}: {e}")
                return None

    async def search(
        self, query: str, max_price: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """Search for products across all stores.

        Args:
            query: Product search query
            max_price: Optional maximum price filter

        Returns:
            List of search result dicts, ranked by relevance
        """
        # Fire concurrent searches across stores (bounded by semaphore).
        tasks = [self._search_one_store(query, store) for store in self.stores]
        store_results = await asyncio.gather(*tasks, return_exceptions=True)

        results: List[Dict[str, Any]] = []
        for result in store_results:
            if isinstance(result, Exception):
                logger.error("Store search raised exception: %s", result)
                continue
            if result is None:
                continue
            # Apply price filter
            if max_price is not None and result["price"] > max_price:
                continue
            results.append(result)

        # Rank by relevance: products with exact phrase match first, then by
        # token overlap. Since we already picked the best match per store,
        # sort by price (ascending) for budget-conscious users.
        results.sort(key=lambda r: r["price"])

        return results

    async def search_with_intent(self, message: str) -> Dict[str, Any]:
        """Parse intent from a message and search for products.

        Uses LLM-based extraction first (handles Arabic/English/mixed),
        falls back to regex parsing if the LLM is unavailable.

        Args:
            message: User message (e.g., "gaming laptop under 50000 EGP")

        Returns:
            Dict with "query", "max_price", and "results" keys
        """
        # Try LLM-based extraction first (handles Arabic, English, mixed).
        llm_intent = await llm_extract_intent(message)
        if llm_intent and llm_intent["query"]:
            query = llm_intent["query"]
            max_price = llm_intent["max_price"]
            language = llm_intent["language"]
            display_query = message  # Show the user's original text.
        else:
            # Fallback to regex/dictionary parsing.
            intent = parse_intent(message)
            query = intent["search_query"]
            max_price = intent["max_price"]
            language = intent["language"]
            display_query = intent["display_query"]

        if not query:
            return {
                "query": "",
                "search_query": "",
                "display_query": display_query,
                "max_price": max_price,
                "results": [],
                "language": language,
            }

        results = await self.search(query, max_price)

        return {
            "query": query,
            "search_query": query,
            "display_query": display_query,
            "max_price": max_price,
            "results": results,
            "language": language,
        }


# =============================================================================
# Extraction Prompts
# =============================================================================

SEARCH_RESULTS_EXTRACTION_PROMPT = """
You are extracting product listings from an e-commerce search results page.

For each product listing/card on the page, extract:
1. Product title
2. URL/link to the product page
3. Price (if shown)
4. Currency
5. Image thumbnail URL
6. Stock status (if indicated)

Also extract pagination info if visible:
- Total results count
- Current page number
- Whether there's a next page

Return ONLY the JSON object with a "products" array and pagination fields.
Extract ALL visible products, not just the first few.
"""
