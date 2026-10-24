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
# Product titles and URLs on laptop/PC stores are long; a full answer needs
# up to ~2000 tokens. A cut-off response is salvaged (complete products
# kept), but the budget should normally fit the whole answer.
MAX_TOKENS_EXTRACTION = 2500
# Characters of page text sent to the LLM per store.
LLM_INPUT_CHARS = 8000
# Cap on products extracted per store page, keeping LLM output (and latency)
# bounded.
MAX_PRODUCTS_PER_STORE = 6
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
    # Whether this is the kind of product the user searched for. Store pages
    # pad (or replace, when nothing matches) results with featured items, so
    # a "laptop" search can surface CPUs and monitors; those are dropped.
    relevant: Optional[bool] = True

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


# An amount like "50000", "50,000", "40k" or "1.5k", optionally followed by a
# currency. Group 1 is the number, group 2 an optional "k" (thousands).
_AMOUNT = r"([\d,]+(?:\.\d+)?)\s*(k)?\s*(?:EGP|LE|pounds?)?"


def _amount(number: str, k: Optional[str]) -> Optional[float]:
    """The EGP value of an [_AMOUNT] match, or None if it is not a number."""
    try:
        value = float(number.replace(",", ""))
    except ValueError:
        return None
    return value * 1000 if k else value


def _remove_span(text: str, match: "re.Match[str]") -> str:
    """[text] without [match], with whitespace collapsed."""
    return re.sub(r"\s+", " ", text[: match.start()] + text[match.end() :]).strip()


def _parse_english_intent(message: str) -> Dict[str, Any]:
    """Parse a user message into a search query and optional price filter.

    Recognizes a price range ("from 40k to 70k", "between 40000 and 70000",
    "in the range 40k egp to 70k egp"), a minimum ("over", "above", "more
    than", "at least"), and a maximum ("under", "below", "less than",
    "max"). Amounts may use a "k" suffix for thousands. Returns the query
    (message minus price phrases), min_price and max_price.

    Examples:
        "gaming laptop under 50000 EGP"
            -> {"query": "gaming laptop", "min_price": None, "max_price": 50000}
        "laptops from 40k to 70k"
            -> {"query": "laptops", "min_price": 40000, "max_price": 70000}
        "iPhone 15 Pro Max" -> {"query": "iPhone 15 Pro Max", ...None, None}
    """
    msg = message.strip()
    min_price: Optional[float] = None
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

    # A range sets both bounds; its lead-in words ("in the range", "priced
    # between", "from") are removed along with the amounts.
    range_match = re.search(
        r"(?:\b(?:in\s+the\s+)?(?:price\s+)?range(?:\s+of)?\s+|\bpriced\s+|"
        r"\bbetween\s+|\bfrom\s+)?\b"
        + _AMOUNT
        + r"\s*(?:to|and|-|–)\s*"
        + _AMOUNT
        + r"(?=\s|$)",
        query,
        re.IGNORECASE,
    )
    if range_match:
        low = _amount(range_match.group(1), range_match.group(2))
        high = _amount(range_match.group(3), range_match.group(4))
        if low is not None and high is not None:
            min_price, max_price = _ordered_range(low, high)
            query = _remove_span(query, range_match)

    if min_price is None:
        match = re.search(
            r"\b(?:over|above|more than|at least|min(?:imum)?)\s+" + _AMOUNT,
            query,
            re.IGNORECASE,
        )
        if match:
            min_price = _amount(match.group(1), match.group(2))
            query = _remove_span(query, match)

    if max_price is None:
        match = re.search(
            r"\b(?:under|below|less than|up to|max(?:imum)?)\s+" + _AMOUNT,
            query,
            re.IGNORECASE,
        )
        if match:
            max_price = _amount(match.group(1), match.group(2))
            query = _remove_span(query, match)

    # No keyword: a standalone number at the end is a budget ceiling.
    if min_price is None and max_price is None:
        standalone = re.search(r"\b" + _AMOUNT + r"\s*$", query, re.IGNORECASE)
        if standalone:
            max_price = _amount(standalone.group(1), standalone.group(2))
            if max_price is not None:
                query = query[: standalone.start()].strip()

    return {"query": query, "min_price": min_price, "max_price": max_price}


def parse_intent(message: str) -> Dict[str, Any]:
    """Parse English or Egyptian Arabic search intent (regex fallback).

    Contract:
      - "query": The search query in English (what to send to stores).
      - "display_query": The user's original text (for display in UI).
      - "min_price": Optional float price floor (English ranges/minimums
        only; the Arabic fallback parses a ceiling only).
      - "max_price": Optional float price ceiling.
      - "language": "ar" or "en".
    """
    language = detect_language(message)
    if language == "ar":
        result = parse_arabic_intent(message)
        result.setdefault("min_price", None)
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
1. "query": The product search query in ENGLISH (translate if needed), as a
   shopper would type it into a store's search box: singular nouns
   ("laptop", not "laptops"), no prices. Be specific when the user is
   (e.g. "27 inch 2K QHD monitor").
2. "min_price": The minimum price in EGP as a number, or null.
3. "max_price": The maximum price in EGP as a number, or null.
   "40k" / "40 ألف" means 40000. A range ("from 40k to 70k", "between",
   "من 40 لـ 70 ألف") sets both; "under"/"أقل من" sets only max_price;
   "over"/"more than"/"أكتر من" sets only min_price.
4. "language": "ar" if the message is primarily Arabic, "en" if primarily English.

Respond with ONLY a JSON object: {"query": "...", "min_price": null, "max_price": 12000, "language": "ar"}

Examples:
- "عايز شاشات 2k بسعر أقل من 12 ألف" → {"query": "2K monitor", "min_price": null, "max_price": 12000, "language": "ar"}
- "gaming laptop under 50000" → {"query": "gaming laptop", "min_price": null, "max_price": 50000, "language": "en"}
- "laptops in the range 40k egp to 70k egp" → {"query": "laptop", "min_price": 40000, "max_price": 70000, "language": "en"}
- "Samsung 27 inch 2K QHD" → {"query": "Samsung 27 inch 2K QHD monitor", "min_price": null, "max_price": null, "language": "en"}
- "لابتوب جيمينج من 30 لـ 45 ألف" → {"query": "gaming laptop", "min_price": 30000, "max_price": 45000, "language": "ar"}
"""


def _coerce_price(raw: Any) -> Optional[float]:
    """A non-negative price from an LLM JSON value, else None."""
    if raw is None:
        return None
    try:
        price = float(raw)
    except (ValueError, TypeError):
        return None
    return price if price >= 0 else None


def _ordered_range(
    min_price: Optional[float], max_price: Optional[float]
) -> tuple:
    """(min, max) with the bounds swapped if given in reverse order."""
    if min_price is not None and max_price is not None and min_price > max_price:
        return max_price, min_price
    return min_price, max_price


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
        min_price, max_price = _ordered_range(
            _coerce_price(data.get("min_price")),
            _coerce_price(data.get("max_price")),
        )
        # Validate language.
        lang = data.get("language", "en")
        if lang not in ("ar", "en"):
            lang = "en"
        return {
            "query": data.get("query", ""),
            "min_price": min_price,
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
                                f"content:\n\n{content[:LLM_INPUT_CHARS]}"
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
                json_match = re.search(r"\{[\s\S]*\}", result)
                if json_match:
                    try:
                        json.loads(json_match.group())
                        return json_match.group()
                    except json.JSONDecodeError:
                        pass
                salvaged = _salvage_products_json(result)
                if salvaged is not None:
                    logger.info("Recovered products from truncated LLM JSON")
                    return salvaged
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


def _fits_budget(
    price: Optional[float],
    min_price: Optional[float],
    max_price: Optional[float],
) -> bool:
    """Whether [price] is within the optional [min_price, max_price] range.

    With any bound set, an unpriced item can't be shown to fit, so it is
    excluded; without bounds every item fits.
    """
    if min_price is None and max_price is None:
        return True
    if price is None or price <= 0:
        return False
    if min_price is not None and price < min_price:
        return False
    if max_price is not None and price > max_price:
        return False
    return True


def _focus_on_listings(content: str) -> str:
    """Move the LLM's input window onto the product listings.

    Store pages often start with thousands of characters of navigation, and
    menus can carry a few prices of their own (featured products), so the
    first price is not reliably where the listings begin. The product grid is
    where prices are densest: start the window just before the first price of
    the [LLM_INPUT_CHARS]-long stretch that holds the most prices.
    """
    positions = [m.start() for m in _PRICE_MARKER.finditer(content)]
    if not positions:
        return content
    best_start, best_count = positions[0], 0
    end = 0
    for i, start in enumerate(positions):
        # Two pointers: positions[i:end] all lie within the window at start.
        end = max(end, i)
        while end < len(positions) and positions[end] < start + LLM_INPUT_CHARS:
            end += 1
        if end - i > best_count:
            best_start, best_count = start, end - i
    return content[max(0, best_start - _LISTING_LEAD_CHARS) :]


# Product cards put the image, link and title before the price; keep this
# much text before (and a little after) each in-budget price.
_CARD_LEAD_CHARS = 700
_CARD_TAIL_CHARS = 150


def _marker_amount(marker: str) -> Optional[float]:
    """The number in a [_PRICE_MARKER] match, e.g. "EGP 55,799" -> 55799."""
    m = re.search(r"\d[\d,]*(?:\.\d+)?", marker)
    if not m:
        return None
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return None


def _focus_on_budget(
    content: str, min_price: Optional[float], max_price: Optional[float]
) -> Optional[str]:
    """Only the parts of the page around prices that fit the budget.

    A store's first results page is sorted by relevance, so most of what
    fits in the LLM's input window is out of budget (e.g. 90k-280k laptops
    for a 40k-70k search) while in-budget products sit further down. Cut out
    the text around each in-budget price (each product's card), merge
    overlaps, and join them up to [LLM_INPUT_CHARS]. Returns None without a
    budget or when no price on the page fits, so the caller falls back to
    the whole listing.
    """
    if min_price is None and max_price is None:
        return None
    spans: List[List[int]] = []
    for m in _PRICE_MARKER.finditer(content):
        amount = _marker_amount(m.group())
        if not _fits_budget(amount, min_price, max_price):
            continue
        start = max(0, m.start() - _CARD_LEAD_CHARS)
        end = min(len(content), m.end() + _CARD_TAIL_CHARS)
        if spans and start <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])
    if not spans:
        return None
    pieces: List[str] = []
    total = 0
    for start, end in spans:
        piece = content[start:end]
        if total + len(piece) > LLM_INPUT_CHARS and pieces:
            break
        pieces.append(piece)
        total += len(piece) + 5
    return "\n...\n".join(pieces)


def _salvage_products_json(text: str) -> Optional[str]:
    """Recover the complete products from a truncated extraction response.

    Long product titles/URLs can exhaust the LLM's output budget mid-array,
    leaving JSON that does not parse. Every product object that was fully
    written is still usable, so decode them one by one and drop the cut-off
    tail. Returns a ``{"products": [...]}`` JSON string, or None if no
    complete product was found.
    """
    array = re.search(r'"products"\s*:\s*\[', text)
    if not array:
        return None
    decoder = json.JSONDecoder()
    products: List[Any] = []
    pos = array.end()
    while True:
        brace = text.find("{", pos)
        if brace == -1:
            break
        try:
            obj, pos = decoder.raw_decode(text, brace)
        except json.JSONDecodeError:
            break  # The truncated last object.
        if isinstance(obj, dict):
            products.append(obj)
    return json.dumps({"products": products}) if products else None


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
        self,
        query: str,
        store: StoreConfig,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
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

        content = _focus_on_budget(content, min_price, max_price) or (
            _focus_on_listings(content)
        )

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
        self,
        query: str,
        store: StoreConfig,
        max_price: Optional[float] = None,
        min_price: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Search a single store and return its top matches (may be empty).

        The price filter is applied before picking the top matches, so a store
        whose best match is outside the budget can still contribute items
        that fit it.
        """
        async with _search_semaphore:
            try:
                extracted = await self._extract_search_results(
                    query, store, min_price=min_price, max_price=max_price
                )
                if not extracted or not extracted.products:
                    return []

                candidates = [
                    p
                    for p in extracted.products
                    if p.title and p.url
                    # Featured/suggested items the LLM marked off-topic.
                    and getattr(p, "relevant", True) is not False
                    and _fits_budget(p.price, min_price, max_price)
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
        self,
        query: str,
        max_price: Optional[float] = None,
        min_price: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Search for products across all stores.

        Args:
            query: Product search query
            max_price: Optional maximum price filter
            min_price: Optional minimum price filter

        Returns:
            List of search result dicts, ranked by relevance
        """
        # Fire concurrent searches across stores (bounded by semaphore), and
        # keep whatever has finished when the deadline expires.
        tasks = [
            asyncio.ensure_future(
                self._search_one_store(query, store, max_price, min_price)
            )
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
            min_price = llm_intent.get("min_price")
            language = llm_intent["language"]
            display_query = message  # Show the user's original text.
        else:
            # Fallback to regex/dictionary parsing.
            intent = parse_intent(message)
            query = intent["search_query"]
            max_price = intent["max_price"]
            min_price = intent.get("min_price")
            language = intent["language"]
            display_query = intent["display_query"]

        if not query:
            return {
                "query": "",
                "search_query": "",
                "display_query": display_query,
                "min_price": min_price,
                "max_price": max_price,
                "results": [],
                "language": language,
            }

        results = await self.search(query, max_price, min_price)

        return {
            "query": query,
            "search_query": query,
            "display_query": display_query,
            "min_price": min_price,
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
7. "relevant": true only if the product IS the kind of product the user
   searched for. A search for "laptop" matches laptops/notebooks only, not
   CPUs, monitors, SSDs, bags or other accessories; a search for "2K
   monitor" matches monitors, not graphics cards.

Store pages often show "featured", "best seller" or "you may also like"
products, and when nothing matches the search they show only those. Such
products are not search results: mark them "relevant": false, or leave them
out. If the page has no product that matches the search, return an empty
"products" array.

Also extract pagination info if visible:
- Total results count
- Current page number
- Whether there's a next page

Return ONLY a compact JSON object with a "products" array and pagination
fields. Include at most {MAX_PRODUCTS_PER_STORE} products: the ones most
relevant to the user's search, skipping ads and unrelated items.
"""
