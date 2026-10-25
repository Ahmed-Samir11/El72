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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
from openai import AsyncOpenAI
from pydantic import BaseModel, field_validator

try:
    from services.chatbot.arabic_nlp import (
        detect_language,
        parse_arabic_intent,
        translate_query_for_search,
    )
    from services.chatbot.cache import SearchResultCache, make_cache_key
    from services.chatbot.extractors import extract_products
    from services.chatbot.store_health import (
        STATE_BLOCKED,
        STATE_CACHED,
        STATE_EMPTY,
        STATE_OK,
        STATE_ROBOTS_DENIED,
        STATE_TIMEOUT,
        StoreHealth,
        StoreStatus,
    )
    from services.common.robots import get_robots_handler
except ImportError:
    from arabic_nlp import (
        detect_language,
        parse_arabic_intent,
        translate_query_for_search,
    )
    from cache import SearchResultCache, make_cache_key
    from common.robots import get_robots_handler
    from extractors import extract_products
    from store_health import (
        STATE_BLOCKED,
        STATE_CACHED,
        STATE_EMPTY,
        STATE_OK,
        STATE_ROBOTS_DENIED,
        STATE_TIMEOUT,
        StoreHealth,
        StoreStatus,
    )

logger = logging.getLogger(__name__)

# Concurrency limit for multi-store search. Crawls are browser tabs, not LLM
# slots, so every store can be in flight at once; the LLM fallback stays behind
# its own single-slot semaphore.
MAX_CONCURRENT_STORES = int(os.getenv("MAX_CONCURRENT_STORES", "8"))
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
    {"chat_template_kwargs": {"enable_thinking": False}} if LLM_DISABLE_THINKING else {}
)

# Crawl4AI Configuration
CRAWL_TIMEOUT = int(os.getenv("CRAWL_TIMEOUT", "25"))
# "networkidle" never fires on stores with long-polling chat/analytics widgets;
# the crawl then burns the whole timeout. The product grid is in the DOM long
# before the network goes quiet, so the DOM-ready event is both faster and
# enough for the deterministic extractors below.
CRAWL_WAIT_UNTIL = os.getenv("CRAWL_WAIT_UNTIL", "domcontentloaded")
# A realistic UA + Accept-Language keeps English storefronts from serving a
# bot challenge or a localised (non-English) page.
CRAWL_USER_AGENT = os.getenv(
    "CHATBOT_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0, x86_64) AppleWebKit/537.36 "
    "(Version 5.25.4) Safari/537.36",
)
CRAWL_ACCEPT_LANGUAGE = os.getenv("CHATBOT_ACCEPT_LANGUAGE", "en-EG,en;q=0.9")
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
# A site that declares a Crawl-Delay asked for it; cap the wait so one greedy
# directive cannot eat the whole search budget.
MAX_CRAWL_DELAY = float(os.getenv("MAX_CRAWL_DELAY", "5"))


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


def _ordered_range(min_price: Optional[float], max_price: Optional[float]) -> tuple:
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


@dataclass
class CrawlOutcome:
    """What one crawl produced: the page body, its HTTP status, any error.

    Keeping the failure reason next to the body is what lets the chatbot tell
    "this store has nothing for your query" from "this store never answered".
    """

    html: str = ""
    status_code: Optional[int] = None
    error: str = ""


def _browser_config():
    """Browser settings for on-demand search: fast, light, and not a bot.

    ``text_mode`` blocks images/fonts/media (the product grid is HTML; the
    client fetches thumbnails itself later) and ``light_mode`` trims the
    browser's own footprint, while stealth patches keep storefronts from serving
    a bot challenge. Older Crawl4AI releases reject unknown keywords, so the
    fallback keeps a version drift from crashing the service at startup.
    """
    kwargs = {
        "headless": True,
        "verbose": False,
        "light_mode": True,
        "text_mode": True,
        "enable_stealth": True,
        "user_agent": CRAWL_USER_AGENT,
        "headers": {"Accept-Language": CRAWL_ACCEPT_LANGUAGE},
    }
    try:
        return BrowserConfig(**kwargs)
    except TypeError as exc:
        logger.info("BrowserConfig rejected these keywords (%s); using defaults", exc)
        return BrowserConfig(headless=True, verbose=False)


def _run_config():
    """Run settings for one store search page: bounded, no link crawling.

    Returns ``None`` when the installed Crawl4AI does not understand the
    keywords, in which case [_crawl_page] falls back to ``arun`` defaults.
    """
    kwargs = {
        "wait_until": CRAWL_WAIT_UNTIL,
        "page_timeout": CRAWL_TIMEOUT * 1000,
        "delay_before_return_html": 0,
        "scan_for_links": False,
        "wait_for_images": False,
        "word_count_threshold": 1,
        "max_retries": 0,
    }
    try:
        return CrawlerRunConfig(**kwargs)
    except TypeError as exc:
        logger.info("CrawlerRunConfig rejected these keywords (%s)", exc)
        return None


class ChatbotSearchService:
    """Searches for products across all supported stores using Crawl4AI.

    A store search is one crawl plus deterministic extraction from the HTML
    that comes back. The local LLM is consulted only for pages those parsers
    cannot read, results are cached per (store, query, price bounds), and each
    store's reachability is tracked so a blocked store costs one status line
    instead of a crawl on every message.
    """

    def __init__(self, db_session_factory=None):
        self.stores = STORES
        self._crawler: Optional[AsyncWebCrawler] = None
        self._run_config = None
        # Warm results survive a restart when a database session factory is
        # given (the chatbot's own PostgreSQL tables); without one the cache
        # is process-local, which is what the tests use.
        self.cache = SearchResultCache(db_session_factory)
        self.store_health = StoreHealth()
        # Shared robots.txt contract (services/common), same modes as the
        # scraper: the chatbot may not crawl paths a store disallows.
        self.robots = get_robots_handler()
        # Last crawl outcome per store (bounded by the store list), so a failed
        # extraction can be reported with its real cause.
        self._last_crawl: Dict[str, CrawlOutcome] = {}

    async def _get_crawler(self) -> AsyncWebCrawler:
        """Get or create the async web crawler instance."""
        if self._crawler is None:
            self._crawler = AsyncWebCrawler(config=_browser_config(), verbose=False)
            self._run_config = _run_config()
            await self._crawler.__aenter__()
        return self._crawler

    async def close(self):
        """Close the crawler and release resources."""
        if self._crawler:
            await self._crawler.__aexit__(None, None, None)
            self._crawler = None
            self._run_config = None

    async def _crawl_page(self, url: str) -> CrawlOutcome:
        """Fetch one page, bounded by [CRAWL_TIMEOUT], and say what happened.

        Args:
            url: Page to fetch.

        Returns:
            [CrawlOutcome]: ``html`` when the page came back, plus
            ``status_code``/``error`` describing a failure.
        """
        try:
            crawler = await self._get_crawler()
            if self._run_config is not None:
                result = await asyncio.wait_for(
                    crawler.arun(url=url, config=self._run_config),
                    timeout=CRAWL_TIMEOUT + 5,
                )
            else:
                result = await asyncio.wait_for(
                    crawler.arun(url=url), timeout=CRAWL_TIMEOUT + 5
                )
        except asyncio.TimeoutError:
            logger.warning("Crawl timed out after %ss: %s", CRAWL_TIMEOUT, url)
            return CrawlOutcome(error=f"timeout after {CRAWL_TIMEOUT}s")
        except Exception as exc:
            logger.error("Exception crawling %s: %s", url, exc)
            return CrawlOutcome(error=f"{type(exc).__name__}: {exc}")

        html = ""
        if result is not None:
            html = result.html or result.cleaned_html or result.markdown or ""
        outcome = CrawlOutcome(
            html=html,
            status_code=getattr(result, "status_code", None),
            error=(
                ""
                if (result is not None and result.success)
                else (getattr(result, "error_message", "") or "crawl failed")
            ),
        )
        return outcome

    async def _extract_search_results(
        self,
        query: str,
        store: StoreConfig,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
    ) -> Optional[SearchResultsSchema]:
        """Products listed on one store's search page.

        Tries the deterministic extractors on the fetched HTML first (JSON-LD,
        then link+price card markup). Only when those find nothing — a
        storefront that renders its grid with JavaScript — does it pay for an
        LLM extraction, which is the slow path this service used to take for
        every store.

        Args:
            query: Product search query (English, as typed into a store).
            store: Store configuration.
            min_price: Optional price floor (EGP).
            max_price: Optional price ceiling (EGP).

        Returns:
            [SearchResultsSchema], which may hold no products, or None when
            the page could not be fetched at all.
        """
        search_url = store.get_search_url(query)
        outcome = await self._crawl_page(search_url)
        # Remembered so a failed extraction is reported with its real cause
        # (blocked, timeout, HTTP status) instead of as "no results".
        self._last_crawl[store.store_id] = outcome
        if not outcome.html:
            return None

        products = extract_products(outcome.html, query, base_url=store.base_url)
        if products:
            return SearchResultsSchema(
                products=[SearchResultItem(**product) for product in products]
            )

        try:
            content = _focus_on_budget(
                outcome.html, min_price, max_price
            ) or _focus_on_listings(outcome.html)

            strategy = LMStudioExtractionStrategy(
                schema=SearchResultsSchema.model_json_schema(),
                extraction_prompt=SEARCH_RESULTS_EXTRACTION_PROMPT,
            )
            result_json = await strategy.extract(content, search_url, query=query)
            return SearchResultsSchema.model_validate(json.loads(result_json))

        except Exception as exc:
            logger.error(
                "LLM extraction failed for %s on %s: %s",
                query,
                store.store_id,
                exc,
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

    def _classify_failure(self, store_id: str) -> Tuple[str, str]:
        """Turn a failed store search into a reportable state.

        "This store has nothing matching" and "this store never answered" used
        to be the same empty list to the user; they are different answers, and
        only the second one justifies putting a store on cooldown.
        """
        outcome = self._last_crawl.get(store_id)
        if outcome is None:
            return STATE_BLOCKED, "store unreachable"
        if "timeout" in (outcome.error or "").lower():
            return STATE_TIMEOUT, outcome.error
        status = outcome.status_code
        if status is not None and status >= 400:
            return STATE_BLOCKED, f"HTTP {status}"
        return STATE_BLOCKED, outcome.error or "store unreachable"

    async def _search_one_store(
        self,
        query: str,
        store: StoreConfig,
        max_price: Optional[float] = None,
        min_price: Optional[float] = None,
    ) -> Tuple[List[Dict[str, Any]], StoreStatus]:
        """One store's top matches plus its reachability status.

        The cache and the health tracker sit in front of the crawl: a repeat
        search costs microseconds, and a store that keeps failing is skipped
        for a cooldown instead of being crawled again on every message. The
        price filter is applied before picking the top matches, so a store
        whose best match is outside the budget can still contribute items that
        fit it.

        Returns:
            ``(results, [StoreStatus])`` — the status is what the client shows
            as "N stores answered, M unreachable".
        """
        cache_key = make_cache_key(store.store_id, query, min_price, max_price)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached, self.store_health.record(
                store.store_id, STATE_CACHED, products=len(cached)
            )

        if self.store_health.is_cooling(store.store_id):
            return [], self.store_health.mark_cooling(store.store_id)

        search_url = store.get_search_url(query)
        if not await self.robots.is_allowed(search_url):
            return [], self.store_health.record(
                store.store_id,
                STATE_ROBOTS_DENIED,
                detail="disallowed by robots.txt",
            )

        # Only a Crawl-Delay the site actually declared is honored, and only
        # up to [MAX_CRAWL_DELAY] so one greedy directive cannot eat the search
        # budget.
        declared_delay = await self.robots.get_declared_crawl_delay(search_url)
        if declared_delay:
            await asyncio.sleep(min(declared_delay, MAX_CRAWL_DELAY))

        async with _search_semaphore:
            try:
                extracted = await self._extract_search_results(
                    query, store, min_price=min_price, max_price=max_price
                )
                if extracted is None:
                    state, detail = self._classify_failure(store.store_id)
                    return [], self.store_health.record(
                        store.store_id, state, detail=detail
                    )

                candidates = [
                    p
                    for p in extracted.products
                    if p.title and p.url
                    # Featured/suggested items marked off-topic.
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

                state = STATE_OK if results else STATE_EMPTY
                self.cache.set(cache_key, store.store_id, results)
                return results, self.store_health.record(
                    store.store_id, state, products=len(results)
                )
            except Exception as exc:
                logger.error("Search failed for store %s: %s", store.store_id, exc)
                return [], self.store_health.record(
                    store.store_id, STATE_BLOCKED, detail=str(exc)
                )

    async def _search_all_stores(
        self,
        query: str,
        max_price: Optional[float] = None,
        min_price: Optional[float] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, object]]]:
        """Search every store concurrently within the overall deadline.

        Returns:
            ``(results, store_status)``. Partial results are normal: the
            status list names the stores that timed out, were blocked or were
            skipped, so the user can see that an answer is partial instead of
            silently getting a short list.
        """
        tasks = {
            store.store_id: asyncio.ensure_future(
                self._search_one_store(query, store, max_price, min_price)
            )
            for store in self.stores
        }
        done, pending = await asyncio.wait(
            list(tasks.values()), timeout=SEARCH_DEADLINE
        )
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
        statuses: List[Dict[str, object]] = []
        for store_id, task in tasks.items():
            if task not in done:
                statuses.append(
                    {
                        "store_id": store_id,
                        "state": STATE_TIMEOUT,
                        "products": 0,
                        "detail": f"search deadline ({int(SEARCH_DEADLINE)}s)",
                    }
                )
                continue
            if task.exception() is not None:
                logger.error("Store search raised exception: %s", task.exception())
                statuses.append(
                    {
                        "store_id": store_id,
                        "state": STATE_BLOCKED,
                        "products": 0,
                        "detail": str(task.exception()),
                    }
                )
                continue
            store_results, status = task.result()
            results.extend(store_results)
            statuses.append(status.as_dict())

        # Each store contributed its most relevant matches; sort them by
        # price (ascending) for budget-conscious users, unpriced (0) last.
        results.sort(key=lambda r: (r["price"] <= 0, r["price"]))
        return results, statuses

    async def search(
        self,
        query: str,
        max_price: Optional[float] = None,
        min_price: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Search for products across all stores, results only.

        Args:
            query: Product search query
            max_price: Optional maximum price filter
            min_price: Optional minimum price filter

        Returns:
            List of search result dicts, cheapest first.
        """
        results, _ = await self._search_all_stores(query, max_price, min_price)
        return results

    async def search_with_intent(self, message: str) -> Dict[str, Any]:
        """Parse intent from a message and search for products.

        Regex/dictionary parsing runs first: it is instant and already covers
        the Egyptian and English phrasings users actually type. The LLM is
        consulted only when that parser cannot produce a query at all, so a
        normal message costs zero LLM round-trips.

        Args:
            message: User message (e.g., "gaming laptop under 50000 EGP")

        Returns:
            Dict with "query", "min_price", "max_price", "results" and
            "store_status" keys.
        """
        intent = parse_intent(message)
        query = intent["search_query"]
        max_price = intent["max_price"]
        min_price = intent.get("min_price")
        language = intent["language"]
        display_query = intent["display_query"]

        if not query and message.strip():
            llm_intent = await llm_extract_intent(message)
            if llm_intent and llm_intent["query"]:
                query = llm_intent["query"]
                min_price, max_price = _ordered_range(
                    llm_intent.get("min_price"), llm_intent["max_price"]
                )
                language = llm_intent["language"]
                display_query = message

        if not query:
            return {
                "query": "",
                "search_query": "",
                "display_query": display_query,
                "min_price": min_price,
                "max_price": max_price,
                "results": [],
                "store_status": [],
                "language": language,
            }

        results, store_status = await self._search_all_stores(
            query, max_price, min_price
        )

        return {
            "query": query,
            "search_query": query,
            "display_query": display_query,
            "min_price": min_price,
            "max_price": max_price,
            "results": results,
            "store_status": store_status,
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
