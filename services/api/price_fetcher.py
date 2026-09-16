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


def _jsonld_product(html: str) -> Optional[dict]:
    """Return the schema.org ``Product`` JSON-LD object, if present."""
    for obj in _parse_jsonld(html):
        t = obj.get("@type")
        types = t if isinstance(t, list) else [t]
        if any(str(x).lower() == "product" for x in types if x):
            return obj
    return None


def _extract_price_from_html(html: str) -> Optional[tuple[float, str]]:
    """Best-effort price extraction from raw HTML.

    Tries, in order:
    1. The schema.org ``Product``/``Offer`` JSON-LD price (authoritative).
    2. OpenGraph / product meta tags.
    3. A regex over visible text for an EGP/USD amount.

    Returns ``(price, currency)`` or ``None``.
    """
    # 1. schema.org Product/Offer JSON-LD.
    prod = _jsonld_product(html)
    if prod is not None:
        price = prod.get("price")
        currency = prod.get("priceCurrency")
        offers = prod.get("offers")
        if isinstance(offers, dict):
            offers = [offers]
        elif not isinstance(offers, list):
            offers = []
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            if price is None and offer.get("price") is not None:
                price = offer.get("price")
            if currency is None and offer.get("priceCurrency"):
                currency = offer.get("priceCurrency")
        if price is not None:
            try:
                val = float(str(price).replace(",", ""))
            except ValueError:
                val = None
            if val is not None and val > 0:
                return val, (currency or "EGP")

    # 2. Meta tags.
    meta = re.search(
        r'<meta[^>]+(?:property|name)=["\'](?:og:price:amount|product:price:amount|price)["\'][^>]+content=["\']([\d,]+(?:\.\d+)?)',
        html,
        re.IGNORECASE,
    )
    if meta:
        try:
            return float(meta.group(1).replace(",", "")), "EGP"
        except ValueError:
            pass

    # 3. Visible-text fallback: a number followed by an EGP marker.
    text = re.sub(r"<[^>]+>", " ", html)
    m = re.search(r"([\d][\d,]{2,}(?:\.\d{1,2})?)\s*(?:EGP|ج\.م|جنيه|£|pound)", text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1).replace(",", "")), "EGP"
        except ValueError:
            pass

    return None


def _jsonld_title(html: str) -> Optional[str]:
    prod = _jsonld_product(html)
    if prod and isinstance(prod.get("name"), str):
        return prod["name"]
    return None


def _jsonld_image(html: str) -> Optional[str]:
    prod = _jsonld_product(html)
    if not prod:
        return None
    image = prod.get("image")
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
        return None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(user_agent=_HEADERS["User-Agent"])
                page = context.new_page()
                page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                try:
                    page.wait_for_timeout(1500)
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
    html = _fetch_html_requests(url)
    if html is None:
        html = _fetch_html_playwright(url)
    if not html:
        logger.warning("Could not fetch HTML for %s", url)
        return None

    found = _extract_price_from_html(html)
    if not found:
        logger.warning("No price found for %s", url)
        return None

    price, currency = found
    return FetchedPrice(
        price_local=price,
        currency=currency,
        title=_jsonld_title(html) or _extract_meta(html, "og:title"),
        image_url=_jsonld_image(html) or _extract_meta(html, "og:image"),
    )


def fetch_price_sync(url: str) -> Optional[FetchedPrice]:
    """Blocking fetch for use in FastAPI background tasks."""
    try:
        return fetch_price(url)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Price fetch failed for %s: %s", url, exc)
        return None
