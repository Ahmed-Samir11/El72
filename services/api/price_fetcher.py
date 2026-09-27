"""Lightweight on-demand price fetcher.

Visits a single product URL with headless Chromium and extracts the price,
currency, title and image. This is the local/dev path that lets a freshly
created tracker get a real price without the full Redis/Postgres monitor
pipeline.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# 1 EGP = 0.032 USD (approximate; matches services.scraper.price_processor).
EGP_TO_USD = 0.032


@dataclass
class FetchedPrice:
    price_local: float
    currency: str
    title: Optional[str] = None
    image_url: Optional[str] = None
    in_stock: bool = True


def _to_usd(price: float, currency: str) -> float:
    return round(price * EGP_TO_USD, 4) if currency.upper() == "EGP" else round(price, 4)


def _parse_jsonld(html: str) -> list:
    """Return the parsed JSON-LD objects embedded in the page."""
    blocks = re.findall(
        r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    objs: list = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, list):
            objs.extend(d for d in data if isinstance(d, dict))
        elif isinstance(data, dict):
            objs.append(data)
    return objs


def _type_is_product(types) -> bool:
    """True if any ``@type`` entry denotes a schema.org Product.

    Accepts plain names ("Product") and full URIs
    ("https://schema.org/Product"), case-insensitively.
    """
    for t in types:
        if not isinstance(t, str):
            continue
        tail = t.rsplit("/", 1)[-1].lower()
        if tail == "product":
            return True
    return False


def _jsonld_product(html: str, objs: Optional[list] = None) -> Optional[dict]:
    """Return the schema.org ``Product`` JSON-LD object, if present.

    Looks at top-level objects **and** entries nested in ``@graph`` (a
    common layout), matching ``@type`` as a plain name or URI. Pass
    pre-parsed ``objs`` to avoid re-parsing the page.
    """
    if objs is None:
        objs = _parse_jsonld(html)
    candidates: list = []
    for obj in objs:
        candidates.append(obj)
        graph = obj.get("@graph")
        if isinstance(graph, list):
            candidates.extend(g for g in graph if isinstance(g, dict))
    for obj in candidates:
        t = obj.get("@type")
        types = t if isinstance(t, list) else [t]
        if _type_is_product(types):
            return obj
    return None


def _parse_amount(raw) -> Optional[float]:
    """Parse a price value that may be numeric or a messy string.

    Handles ints/floats and strings containing currency symbols,
    prefixes, or comma grouping (e.g. ``"129,999 EGP"``,
    ``"EGP 1,299.50"``). Returns ``None`` for missing/non-positive values.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        m = re.search(r"(\d[\d,]*(?:\.\d+)?)", str(raw))
        if not m:
            return None
        try:
            value = float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return value if value > 0 else None


def _first_image_url(image) -> Optional[str]:
    """First usable URL from a JSON-LD ``image`` value (str, list, or dict)."""
    if isinstance(image, str):
        return image
    if isinstance(image, list) and image:
        first = image[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict) and isinstance(first.get("url"), str):
            return first["url"]
    if isinstance(image, dict) and isinstance(image.get("url"), str):
        return image["url"]
    return None


def _extract_from_html(html: str) -> Optional[tuple[float, str, Optional[str], Optional[str]]]:
    """Best-effort extraction of ``(price, currency, title, image_url)``.

    Parses the embedded JSON-LD **once** per page and tries, in order:
    1. The schema.org ``Product``/``Offer`` JSON-LD values (authoritative).
    2. OpenGraph / product meta tags.
    3. A regex over visible text for an EGP amount.

    Returns ``(price, currency, title, image_url)`` or ``None`` if no price
    could be determined.
    """
    objs = _parse_jsonld(html)
    prod = _jsonld_product(html, objs)

    price: Optional[float] = None
    currency: Optional[str] = None
    title: Optional[str] = None
    image_url: Optional[str] = None

    # 1. schema.org Product/Offer JSON-LD.
    if prod is not None:
        raw_price = prod.get("price")
        currency = prod.get("priceCurrency")
        if isinstance(prod.get("name"), str):
            title = prod["name"]
        image_url = _first_image_url(prod.get("image"))

        offers = prod.get("offers")
        if isinstance(offers, dict):
            offers = [offers]
        elif not isinstance(offers, list):
            offers = []
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            if raw_price is None and offer.get("price") is not None:
                raw_price = offer.get("price")
            if currency is None and offer.get("priceCurrency"):
                currency = offer.get("priceCurrency")

        price = _parse_amount(raw_price)

    if price is None:
        # 2. Meta tags.
        meta = re.search(
            r'<meta[^>]+(?:property|name)=["\'](?:og:price:amount|product:price:amount|price)["\'][^>]+content=["\']([\d,]+(?:\.\d+)?)',
            html,
            re.IGNORECASE,
        )
        if meta:
            price = _parse_amount(meta.group(1))

    if price is None:
        # 3. Visible-text fallback: a number followed by an EGP marker.
        text = re.sub(r"<[^>]+>", " ", html)
        m = re.search(r"([\d][\d,]{2,}(?:\.\d{1,2})?)\s*(?:EGP|ج\.م|جنيه|£|pound)", text, re.IGNORECASE)
        if m:
            price = _parse_amount(m.group(1))

    if price is None:
        return None

    # Title/image meta fallbacks (JSON-LD takes precedence).
    if title is None:
        title = _extract_meta(html, "og:title")
    if image_url is None:
        image_url = _extract_meta(html, "og:image")

    # The app targets the Egyptian market; pages that omit priceCurrency
    # are assumed to quote EGP.
    return price, (currency or "EGP"), title, image_url


def _extract_meta(html: str, prop: str) -> Optional[str]:
    m = re.search(
        r'<meta[^>]+(?:property|name)=["\']' + re.escape(prop) + r'["\'][^>]+content=["\']([^"\']*)',
        html,
        re.IGNORECASE,
    )
    return m.group(1) if m else None


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _fetch_html_requests(url: str, timeout: int = 30) -> Optional[str]:
    """Fetch page HTML with ``requests`` (no browser required)."""
    try:
        import requests
    except ImportError:
        return None
    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.text
        logger.warning("HTTP %s fetching %s", r.status_code, url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("requests fetch failed for %s: %s", url, exc)
    return None


def _fetch_html_playwright(url: str, timeout_ms: int = 25000) -> Optional[str]:
    """Fetch page HTML with headless Chromium (JS-rendered fallback)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright not installed; skipping browser fallback")
        return None
    try:
        logger.info("Launching Playwright browser for %s", url)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(user_agent=_HEADERS["User-Agent"])
                page = context.new_page()
                page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                try:
                    page.wait_for_timeout(3000)
                except Exception:
                    pass
                html = page.content()
                context.close()
            finally:
                browser.close()
        return html
    except Exception as exc:  # noqa: BLE001
        logger.warning("Playwright fetch failed for %s: %s", url, exc)
    return None


def fetch_price(url: str) -> Optional[FetchedPrice]:
    """Fetch ``url`` and extract a price. Returns ``None`` on failure.

    Tries a plain HTTP fetch first (fast, no browser); falls back to
    headless Chromium for JS-rendered pages.
    """
    logger.info("Starting price fetch for %s", url)
    html = _fetch_html_requests(url)
    found = _extract_from_html(html) if html else None

    if found is None:
        logger.info("Requests fetch yielded no price for %s; trying Playwright browser fallback", url)
        html_pw = _fetch_html_playwright(url)
        if html_pw:
            html = html_pw
            found = _extract_from_html(html)

    if not html:
        logger.warning("Could not fetch HTML for %s via requests or Playwright", url)
        return None

    if not found:
        logger.warning("No price found in HTML content for %s", url)
        return None

    price, currency, title, image_url = found

    logger.info("Price fetch succeeded for %s: price=%s %s, title=%s, image_url=%s", url, price, currency, title, image_url)
    return FetchedPrice(
        price_local=price,
        currency=currency,
        title=title,
        image_url=image_url,
    )


def fetch_price_sync(url: str) -> Optional[FetchedPrice]:
    """Blocking fetch for use in FastAPI background tasks."""
    try:
        return fetch_price(url)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Price fetch failed for %s: %s", url, exc)
        return None
