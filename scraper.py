"""
Simple Playwright scraper that extracts product title and price from a live Amazon.eg
and publishes a structured payload to Redis Streams `stream:price_ingest`.

This is the producer in the Golden Path integration test.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Optional

import redis
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

STREAM = "stream:price_ingest"
REDIS_URL = "redis://localhost:6379/0"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("scraper")


def parse_price(text: str) -> Optional[float]:
    """Convert price text like 'EGP 1,200.00' or '1,200.00 EGP' to float (1200.0).

    Returns None if parsing fails.
    """
    if not text:
        return None
    # Strip currency letters and non-numeric except dot and comma
    cleaned = re.sub(r"[^0-9,\.]+", "", text)
    if not cleaned:
        return None
    # Replace comma thousands separator then convert
    cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_product_info(page) -> dict:
    """Attempt a few selectors known to work on Amazon product pages.

    Returns dict with `title` and `price` (float) or raises RuntimeError.
    """
    # Title selectors
    title_selectors = ["#productTitle", "#title", "span#productTitle"]
    title = None
    for sel in title_selectors:
        el = page.query_selector(sel)
        if el:
            title = el.inner_text().strip()
            break

    # Price selectors (try common ones)
    price_selectors = [
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        "span.a-price > span.a-offscreen",
        "span.a-color-price",
    ]
    price_text = None
    for sel in price_selectors:
        el = page.query_selector(sel)
        if el:
            price_text = el.inner_text().strip()
            break

    # Last-resort: search for elements with currency text
    if not price_text:
        candidates = page.query_selector_all("span")
        for c in candidates:
            txt = (c.inner_text() or "").strip()
            if "EGP" in txt or "ر.س" in txt:
                # crude filter
                if re.search(r"\d", txt):
                    price_text = txt
                    break

    price = parse_price(price_text) if price_text else None

    if not title:
        raise RuntimeError(
            "Could not extract product title; page structure may have changed"
        )
    if price is None:
        raise RuntimeError(f"Could not extract price (raw='{price_text}')")

    return {"title": title, "price": price}


def publish_to_redis(client: redis.Redis, payload: dict) -> str:
    try:
        msgid = client.xadd(STREAM, {"payload": json.dumps(payload)})
        logger.info("Published message %s -> %s", msgid, payload)
        return msgid
    except Exception:
        logger.exception("Failed to XADD payload to Redis")
        raise


def run(url: str):
    r = redis.from_url(REDIS_URL)
    # Test connection
    try:
        r.ping()
    except Exception:
        logger.exception("Cannot connect to Redis at %s", REDIS_URL)
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            logger.info("Navigating to %s", url)
            page.goto(url, timeout=30000)
            info = extract_product_info(page)
            payload = {
                "sku": url.split("/dp/")[-1] if "/dp/" in url else url,
                "store": "amazon.eg",
                "title": info["title"],
                "price": info["price"],
                "timestamp": int(page.evaluate("Date.now()") / 1000),
            }
            publish_to_redis(r, payload)
        except PWTimeout:
            logger.exception("Playwright timeout when loading page")
        except RuntimeError:
            logger.exception("Extraction failed; selectors may be outdated")
        except Exception:
            logger.exception("Unexpected error in scraper")
        finally:
            browser.close()


if __name__ == "__main__":
    # Example product; replace if Amazon changes URL
    target = "https://www.amazon.eg/-/en/Logitech-Wireless-Mouse-Battery-Charcoal/dp/B0746NKVBN/"
    run(target)
