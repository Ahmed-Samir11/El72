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
from pydantic import BaseModel, field_validator

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
# Per-request timeout. Includes time spent queued behind other requests on the
# LLM server, so it must cover a full extraction on slow local hardware.
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "120"))
# Number of LLM requests in flight at once. Should match the server's parallel
# slots (llama-server defaults to 1); extra requests only queue server-side and
# time out client-side.
LLM_MAX_CONCURRENCY = int(os.getenv("LLM_MAX_CONCURRENCY", "1"))
_llm_semaphore = asyncio.Semaphore(LLM_MAX_CONCURRENCY)
# Reasoning models spend most of the token budget "thinking" before emitting
# JSON, which makes extraction too slow and truncates the output. Disable it
# via the chat template (understood by llama-server; ignored elsewhere).
LLM_DISABLE_THINKING = os.getenv("LLM_DISABLE_THINKING", "true").lower() == "true"
LLM_EXTRA_BODY: Dict[str, Any] = (
    {"chat_template_kwargs": {"enable_thinking": False}}
    if LLM_DISABLE_THINKING
    else {}
)

# Crawl4AI Configuration
CRAWL_TIMEOUT = 30
CRAWL_WAIT_FOR = "networkidle"
MAX_TOKENS_EXTRACTION = 1500
# Cap on products extracted per store page, keeping LLM output (and latency)
# bounded.
MAX_PRODUCTS_PER_STORE = 10
# Number of top-ranked matches each store contributes to the results.
MAX_RESULTS_PER_STORE = 3
# Overall budget for a multi-store search. Stores still pending when it expires
# are dropped so the client (receive timeout 120s) gets partial results instead
# of a timeout.
SEARCH_DEADLINE = float(os.getenv("SEARCH_DEADLINE", "100"))


# =============================================================================
# LM Studio Client
# =============================================================================


_llm_client: Optional[AsyncOpenAI] = None


def get_lm_studio_client() -> AsyncOpenAI:
    """Get the singleton AsyncOpenAI client configured for the LLM server."""
    global _llm_client
    if _llm_client is None:
        # No automatic retries: a retry after a timeout re-queues the same
        # long request on a single-slot server and delays everyone else.
        _llm_client = AsyncOpenAI(
            base_url=LM_STUDIO_URL,
            api_key="not-needed",
            timeout=LLM_TIMEOUT,
            max_retries=0,
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

    @field_validator("price", mode="before")
    @classmethod
    def _coerce_price(cls, value: Any) -> Optional[float]:
        """Accept prices the LLM returns as text, e.g. "9,000" or "EGP 1,299.50"."""
        if value is None or isinstance(value, (int, float)):
            return value
        match = re.search(r"\d[\d,]*(?:\.\d+)?", str(value))
        if not match:
            return None
        return float(match.group().replace(",", ""))


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
        # Same domain as the scraper's ElBadrGroupScraper; elbadrgroup.com
        # refuses connections.
        base_url="https://elbadrgroupeg.store",
        search_url_pattern="{base_url}/index.php?route=product/search&search={encoded_query}",
    ),
    StoreConfig(
        store_id="2b_egypt",
        store_name="2B Egypt",
        base_url="https://2b.com.eg",
        # /search?q= redirects to a results page for the literal word "search".
        search_url_pattern="{base_url}/en/catalogsearch/result/?q={encoded_query}",
    ),
    StoreConfig(
        store_id="alfrensia",
        store_name="Alfrensia",
        base_url="https://alfrensia.com",
        # WooCommerce product search; /en/search?q= returns 404.
        search_url_pattern="{base_url}/en/?s={encoded_query}&post_type=product",
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
        async with _llm_semaphore:
            response = await client.chat.completions.create(
                model=LM_STUDIO_MODEL,
                messages=[
                    {"role": "system", "content": INTENT_EXTRACTION_PROMPT},
                    {"role": "user", "content": message},
                ],
                temperature=0.0,
                max_tokens=200,
                extra_body=LLM_EXTRA_BODY,
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

    async def extract(
        self, content: str, url: str = None, query: Optional[str] = None
    ) -> str:
        """Extract structured data from content using local LLM."""
        system_prompt = f"""{self.extraction_prompt}

Expected JSON schema:
{json.dumps(self.schema, indent=2)}

URL: {url or 'unknown'}
"""
        query_hint = f"The user searched for: {query}\n\n" if query else ""

        try:
            async with _llm_semaphore:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": (
                                f"{query_hint}"
                                f"Extract product information from this page "
                                f"content:\n\n{content[:8000]}"
                            ),
                        },
                    ],
                    max_tokens=MAX_TOKENS_EXTRACTION,
                    temperature=0.1,
                    extra_body=LLM_EXTRA_BODY,
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


# Prices as they appear on Egyptian store pages: "EGP 1,299", "1,299 جنيه",
# "ج.م 1,299", "LE 1299".
_PRICE_MARKER = re.compile(
    r"(?:EGP|LE|ج\.?\s?م|جنيه)\s?[\d,]{3,}|[\d,]{3,}(?:\.\d+)?\s?(?:EGP|LE|ج\.?\s?م|جنيه)",
    re.IGNORECASE,
)
# How much text before the first price to keep, so the first product's title,
# link and image stay in the window.
_LISTING_LEAD_CHARS = 1500


def _focus_on_listings(content: str) -> str:
    """Drop the page header/menus that precede the product listings.

    Store pages often start with thousands of characters of navigation, which
    would otherwise fill the LLM's input window before any product appears.
    The first price marks where the listings begin.
    """
    match = _PRICE_MARKER.search(content)
    if not match:
        return content
    return content[max(0, match.start() - _LISTING_LEAD_CHARS) :]


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

        content = _focus_on_listings(content)

        try:
            strategy = LMStudioExtractionStrategy(
                schema=SearchResultsSchema.model_json_schema(),
                extraction_prompt=SEARCH_RESULTS_EXTRACTION_PROMPT,
            )

            result_json = await strategy.extract(content, search_url, query=query)

            result_dict = json.loads(result_json)
            return SearchResultsSchema.model_validate(result_dict)

        except Exception as e:
            logger.error(
                f"Search extraction failed for {query} on {store.store_id}: {e}"
            )
            return None

    def _rank_matches(
        self, query: str, products: List[SearchResultItem]
    ) -> List[SearchResultItem]:
        """Rank products by relevance to the query, best first.

        Uses token overlap scoring.

        Args:
            query: Original search query
            products: List of search result items

        Returns:
            Products sorted by descending relevance score
        """
        query_lower = query.lower()
        query_tokens = set(query_lower.split())

        def score(product: SearchResultItem) -> float:
            title_lower = product.title.lower()
            title_tokens = set(title_lower.split())

            # Token overlap score
            token_hits = len(query_tokens & title_tokens)

            # Length bonus (shorter titles often more relevant)
            length_bonus = 1.0 / (1 + len(title_lower) / 100)

            # Phrase bonus (exact phrase match)
            phrase_bonus = 1.0 if query_lower in title_lower else 0.0

            return token_hits + length_bonus + phrase_bonus

        return sorted(products, key=score, reverse=True)

    def _find_best_match(
        self, query: str, products: List[SearchResultItem]
    ) -> Optional[SearchResultItem]:
        """Find the best matching product from search results, or None."""
        ranked = self._rank_matches(query, products)
        return ranked[0] if ranked else None

    async def _search_one_store(
        self, query: str, store: StoreConfig, max_price: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """Search a single store and return its top matches (may be empty).

        The price filter is applied before picking the top matches, so a store
        whose best match is over budget can still contribute cheaper items.
        """
        async with _search_semaphore:
            try:
                extracted = await self._extract_search_results(query, store)
                if not extracted or not extracted.products:
                    return []

                candidates = [
                    p
                    for p in extracted.products
                    if p.title and p.url
                    # With a budget, an unpriced item can't be shown to fit it.
                    and (
                        max_price is None
                        or (p.price is not None and 0 < p.price <= max_price)
                    )
                ]
                matches = self._rank_matches(query, candidates)
                matches = matches[:MAX_RESULTS_PER_STORE]

                results: List[Dict[str, Any]] = []
                for item in matches:
                    # Resolve relative URLs
                    product_url = item.url
                    if not product_url.startswith("http"):
                        product_url = f"{store.base_url}{product_url}"
                    image_url = item.image_url or ""
                    if image_url.startswith("//"):
                        image_url = f"https:{image_url}"
                    elif image_url.startswith("/"):
                        image_url = f"{store.base_url}{image_url}"

                    results.append(
                        {
                            "store_id": store.store_id,
                            "store_name": store.store_name,
                            "title": item.title,
                            "price": item.price if item.price is not None else 0.0,
                            "currency": item.currency,
                            "url": product_url,
                            "image_url": image_url,
                            "in_stock": bool(item.in_stock),
                        }
                    )
                return results
            except Exception as e:
                logger.error(f"Search failed for store {store.store_id}: {e}")
                return []

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
        # Fire concurrent searches across stores (bounded by semaphore), and
        # keep whatever has finished when the deadline expires.
        tasks = [
            asyncio.ensure_future(self._search_one_store(query, store, max_price))
            for store in self.stores
        ]
        done, pending = await asyncio.wait(tasks, timeout=SEARCH_DEADLINE)
        if pending:
            logger.warning(
                "Search deadline (%ss) hit; dropping %d pending store(s)",
                SEARCH_DEADLINE,
                len(pending),
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        results: List[Dict[str, Any]] = []
        for task in tasks:
            if task not in done:
                continue
            if task.exception() is not None:
                logger.error("Store search raised exception: %s", task.exception())
                continue
            # Price filter was already applied per store.
            results.extend(task.result())

        # Each store contributed its most relevant matches; sort them by
        # price (ascending) for budget-conscious users, unpriced (0) last.
        results.sort(key=lambda r: (r["price"] <= 0, r["price"]))

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

SEARCH_RESULTS_EXTRACTION_PROMPT = f"""
You are extracting product listings from an e-commerce search results page.

For each product listing/card on the page, extract:
1. Product title
2. URL/link to the product page
3. Price (if shown), as a plain number without currency or thousands
   separators (e.g. 12999.0, not "EGP 12,999")
4. Currency
5. Image thumbnail URL
6. Stock status (if indicated)

Also extract pagination info if visible:
- Total results count
- Current page number
- Whether there's a next page

Return ONLY a compact JSON object with a "products" array and pagination
fields. Include at most {MAX_PRODUCTS_PER_STORE} products: the ones most
relevant to the user's search, skipping ads and unrelated items.
"""
