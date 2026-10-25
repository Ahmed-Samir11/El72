"""Deterministic product extraction for chatbot search.

The chatbot used to pay one local-LLM round-trip per store, on a server with a
single request slot, which is what made a search take ~60s. Egyptian store
front-ends (Magento, WooCommerce, Shopify-style themes) ship machine-readable
product data in the HTML they send, so the LLM is demoted to a fallback that
only runs when these two parsers find nothing usable:

1. ``extract_jsonld_products`` — ``application/ld+json`` blocks (schema.org
   ``Product`` / ``Offer``), the most reliable source.
2. ``extract_card_products`` — anchor + price proximity on the raw HTML, for
   stores that render cards without JSON-LD.

Everything here is pure string work: no network, no LLM, no browser.
"""

import json
import logging
import re
from collections import deque
from html import unescape
from typing import Any, Deque, Dict, List, Optional
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON-LD
# ---------------------------------------------------------------------------

_JSONLD_TAG = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)

_PRODUCT_TYPES = {"product", "item", "schema.org/product"}

# schema.org availability values that mean "you cannot buy this now".
_OUT_OF_STOCK = {
    "outofstock",
    "soldout",
    "limitedavailability",
    "preorder",
    "backorder",
}

# How deep to walk a JSON-LD graph before giving up on a branch.
_MAX_GRAPH_DEPTH = 6


def _iter_jsonld_nodes(raw: str) -> List[dict]:
    """Flatten one ``application/ld+json`` block into its object nodes.

    Handles a bare object, an array, and ``{"@graph": [...]}`` nesting. Malformed
    JSON is skipped (store pages frequently ship broken blocks) rather than
    failing the whole page.
    """
    try:
        data = json.loads(raw.strip())
    except (json.JSONDecodeError, ValueError):
        return []

    nodes: List[dict] = []
    # FIFO, so products keep the order the page declares them in.
    queue: Deque[Any] = deque([data])
    while queue:
        node = queue.popleft()
        if isinstance(node, list):
            queue.extend(node)
        elif isinstance(node, dict):
            nodes.append(node)
            for key in ("@graph", "item", "items", "offers", "relatedProducts"):
                child = node.get(key)
                if isinstance(child, (list, dict)):
                    queue.append(child)
    return nodes


def _offer_list(node: dict) -> List[dict]:
    """Normalise a node's ``offers`` (object, array or absent) to a list."""
    offers = node.get("offers")
    if isinstance(offers, dict):
        return [offers]
    if isinstance(offers, list):
        return [o for o in offers if isinstance(o, dict)]
    return []


def _first_text(node: dict, *keys: str) -> str:
    """First non-empty string found under [keys] in [node]."""
    for key in keys:
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for sub in ("@value", "url", "@id"):
                nested = value.get(sub)
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
    return ""


def _price_from_offers(node: dict) -> Optional[float]:
    """The price a JSON-LD product advertises.

    Prefers a concrete ``offers.priceAmount`` and falls back to
    ``aggregateOffer.lowestPrice`` (the "from" price of a variant group).
    """
    for offer in _offer_list(node):
        raw = offer.get("priceAmount", offer.get("price"))
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str):
            match = re.search(r"\d[\d,]*(?:\.\d+)?", raw.replace(",", ""))
            if match:
                return float(match.group())

    aggregate = node.get("aggregateOffer")
    if isinstance(aggregate, dict):
        raw = aggregate.get("lowestPrice")
        if isinstance(raw, (int, float)):
            return float(raw)
    return None


def _availability_values(node: dict) -> List[str]:
    """Every stock state the product's offers declare.

    Stores spell availability in three shapes: a bare string ("OutOfStock"),
    a schema.org URL object ({"@id": "https://schema.org/OutOfStock"}) or a
    list of offers. Some ship a boolean ``isAvailable`` instead.
    """
    values: List[str] = []
    for offer in _offer_list(node):
        availability = offer.get("availability", offer.get("isAvailable"))
        if isinstance(availability, str):
            values.append(availability)
        elif isinstance(availability, dict):
            for key in ("@id", "url", "@value"):
                nested = availability.get(key)
                if isinstance(nested, str) and nested.strip():
                    values.append(nested)
                    break
        elif isinstance(availability, list):
            values.extend(v for v in availability if isinstance(v, str))
        elif isinstance(availability, bool):
            values.append("OutOfStock" if not availability else "InStock")
    return values


def _normalized_availability(value: str) -> str:
    """Reduce an availability string to its schema.org enum name."""
    return value.lower().replace("_", "").replace("-", "").split("/")[-1]


def _in_stock(node: dict) -> bool:
    """Whether the JSON-LD offers say the product can be bought now.

    A variant group lists several offers; the product is buyable when ANY
    offer is not explicitly out of stock, so one unavailable size cannot
    hide a purchasable product.
    """
    values = _availability_values(node)
    if not values:
        return True
    return any(_normalized_availability(value) not in _OUT_OF_STOCK for value in values)


def _image_from(node: dict) -> str:
    """The product image (string, list or ``{@id: ...}`` object)."""
    image = node.get("image")
    if isinstance(image, str):
        return image.strip()
    if isinstance(image, list):
        for entry in image:
            if isinstance(entry, str) and entry.strip():
                return entry.strip()
            if isinstance(entry, dict):
                for key in ("url", "@id", "imageUri"):
                    value = entry.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
    elif isinstance(image, dict):
        for key in ("url", "@id", "imageUri"):
            value = image.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _absolute(url: str, base_url: Optional[str]) -> str:
    """Resolve [url] against [base_url] when it is relative."""
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    if not base_url:
        return url
    return urljoin(base_url, url)


def extract_jsonld_products(
    html: str, base_url: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Products advertised in a page's ``application/ld+json`` blocks.

    Args:
        html: Raw HTML (not the crawler's markdown rendering — JSON-LD is
            stripped from markdown).
        base_url: Used to make relative product links absolute.

    Returns:
        ``[{title, url, price, currency, image_url, in_stock, relevant}]``
        with ``relevant`` always true: JSON-LD on a *search results* page
        describes the listed products, not the page chrome.
    """
    products: List[Dict[str, Any]] = []
    for raw in _JSONLD_TAG.findall(html or ""):
        for node in _iter_jsonld_nodes(raw):
            node_type = node.get("@type")
            types = (
                {node_type.lower()}
                if isinstance(node_type, str)
                else (
                    {str(t).lower() for t in node_type}
                    if isinstance(node_type, list)
                    else set()
                )
            )
            is_product = bool(types & _PRODUCT_TYPES) or "offers" in node
            if not is_product:
                continue
            title = _first_text(node, "name", "item", "title")
            url = _absolute(_first_text(node, "@id", "url", "loc", "link"), base_url)
            if not title or not url:
                continue
            products.append(
                {
                    "title": title,
                    "url": url,
                    "price": _price_from_offers(node),
                    "currency": "EGP",
                    "image_url": _image_from(node),
                    "in_stock": _in_stock(node),
                    "relevant": True,
                }
            )
    return products


# ---------------------------------------------------------------------------
# Card fallback (no JSON-LD)
# ---------------------------------------------------------------------------

# Prices as they appear on Egyptian store pages: "EGP 1,299", "1,299 ج.م",
# "LE 1299". Kept in sync with search_service._PRICE_MARKER.
_PRICE_MARKER = re.compile(
    r"(?:EGP|LE|ج\.?\s?م|جنيه)\s?[\d,]{3,}|[\d,]{3,}(?:\.\d+)?\s?(?:EGP|LE|ج\.?\s?م|جنيه)",
    re.IGNORECASE,
)
# A product card puts the link, image and title before the price.
_CARD_LOOKBEHIND = 900
_CARD_LOOKAHEAD = 200
# Product links on these stores carry the price in a query parameter too
# (e.g. "?price=1299"); that is not a listing price and must not double count.
_HREF = re.compile(r"<a[^>]+href=[\"']([^\"']+)[\"']", re.IGNORECASE)
_ALT = re.compile(r"alt=[\"']([^\"']{6,200})[\"']", re.IGNORECASE)
_TITLE_ATTR = re.compile(r"title=[\"']([^\"']{6,200})[\"']", re.IGNORECASE)
_IMG = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)
_ANCHOR_TEXT = re.compile(
    r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.{6,200}?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_TAG = re.compile(r"<[^>]+>")
# Links that are never product cards (search forms, assets, anchors).
_NON_PRODUCT_HREF = re.compile(
    r"^(?:#|javascript:|data:|mailto:|/(?:en/)?(?:search|catalogsearch|s)\b|[?&])",
    re.IGNORECASE,
)
# Static assets that can sit next to a price and confuse the card scan.
_ASSET_SUFFIX = re.compile(
    r"\.(?:js|css|png|jpe?g|webp|svg|ico|woff2?)(?:\?|$)", re.IGNORECASE
)


def _clean_text(value: str) -> str:
    """Strip tags/entities from [value] and collapse whitespace."""
    text = unescape(_TAG.sub(" ", value))
    return re.sub(r"\s+", " ", text).strip()


def _marker_price(marker: str) -> Optional[float]:
    """The number inside a price marker, e.g. ``"EGP 55,799"`` -> 55799."""
    match = re.search(r"\d[\d,]*(?:\.\d+)?", marker)
    if not match:
        return None
    try:
        return float(match.group().replace(",", ""))
    except ValueError:
        return None


def _nearest_before(pattern: re.Pattern, window: str, price_offset: int):
    """Last match of [pattern] that starts before the price in [window].

    A card's own title/image sits between its link and its price; taking the
    first match on the page instead would label every card with the previous
    card's title.
    """
    found = None
    for match in pattern.finditer(window):
        if match.start() > price_offset:
            break
        found = match
    return found


def _title_from_window(window: str, price_offset: int) -> str:
    """Best product title inside a product card's HTML window.

    Prefers the ``alt``/``title`` attribute nearest the price (product cards put
    the product name there) and falls back to the anchor text of the nearest
    link that closes before the price.
    """
    for pattern in (_ALT, _TITLE_ATTR):
        match = _nearest_before(pattern, window, price_offset)
        if match is not None:
            title = _clean_text(match.group(1))
            if len(title) >= 6:
                return title

    anchor = None
    for match in _ANCHOR_TEXT.finditer(window):
        if match.end() > price_offset:
            break
        anchor = match
    if anchor is not None:
        title = _clean_text(anchor.group(2))
        if len(title) >= 6:
            return title
    return ""


def extract_card_products(
    html: str, base_url: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Products implied by "link + title + price" cards in raw HTML.

    Scans every price marker on the page and looks back for the nearest
    product link and title, which is how these stores order their card markup.
    Returns the same dict shape as [_extract_jsonld_products], deduplicated by
    URL, with prices already coerced to floats.
    """
    content = html or ""
    products: List[Dict[str, Any]] = []
    seen: set = set()

    for marker in _PRICE_MARKER.finditer(content):
        start = max(0, marker.start() - _CARD_LOOKBEHIND)
        window = content[start : marker.end() + _CARD_LOOKAHEAD]
        # Offset of the price inside the window: everything belonging to this
        # card sits before it.
        price_offset = marker.start() - start

        href_match = _nearest_before(_HREF, window, price_offset)
        url = ""
        if href_match is not None:
            candidate = href_match.group(1).strip()
            if not _NON_PRODUCT_HREF.match(candidate) and not _ASSET_SUFFIX.search(
                candidate
            ):
                url = _absolute(candidate, base_url)
        if not url:
            continue

        title = _title_from_window(window, price_offset)
        if not title:
            continue

        price = _marker_price(marker.group())
        if price is None or price <= 0:
            continue

        image_match = _nearest_before(_IMG, window, price_offset)
        image = image_match.group(1) if image_match else ""

        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        products.append(
            {
                "title": title,
                "url": url,
                "price": price,
                "currency": "EGP",
                "image_url": image,
                "in_stock": True,
                "relevant": True,
            }
        )

    return products


# ---------------------------------------------------------------------------
# Post-processing shared by both parsers
# ---------------------------------------------------------------------------

# Words that carry no product meaning when scoring a title against a query.
_STOPWORDS = {
    "the",
    "for",
    "with",
    "and",
    "new",
    "official",
    "product",
    "buy",
    "shop",
    "store",
    "price",
    "egp",
    "le",
    "inch",
}


def query_tokens(query: str) -> set:
    """Meaningful lowercase tokens of a search query."""
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (query or "").lower())
        if len(token) > 1 and token not in _STOPWORDS
    }


def drop_off_topic(products: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    """Drop products whose title shares no token with the query.

    Store search pages replace an empty result set with "featured" or "best
    seller" products; those are not what the user asked for. When *nothing*
    shares a token (a translation miss, an unusual brand spelling) the input is
    returned unchanged rather than silently producing an empty search.
    """
    tokens = query_tokens(query)
    if not tokens or not products:
        return products

    matched = [
        product
        for product in products
        if tokens & query_tokens(product.get("title", ""))
    ]
    return matched or products


def dedupe_products(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop duplicate cards, keeping the first (highest on the page) copy."""
    unique: List[Dict[str, Any]] = []
    seen: set = set()
    for product in products:
        url = (product.get("url") or "").lower()
        title = (product.get("title") or "").lower()
        key = url or f"title:{title}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(product)
    return unique


def extract_products(
    html: str,
    query: str,
    base_url: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Best deterministic product list for a page: JSON-LD, then cards.

    Args:
        html: Raw page HTML.
        query: The user's search query, used to drop off-topic cards.
        base_url: Store base URL for resolving relative links.

    Returns:
        Deduplicated, on-topic product dicts (may be empty, in which case the
        caller should fall back to the LLM extractor).
    """
    products = extract_jsonld_products(html, base_url) or extract_card_products(
        html, base_url
    )
    if not products:
        return []
    return dedupe_products(drop_off_topic(products, query))
