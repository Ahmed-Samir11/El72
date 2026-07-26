import asyncio
import hashlib
import json
import logging
import os
import random
import re
import time
from typing import Any, Dict, List, Optional

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright
import asyncpg

from services.common.redis_client import RedisStreamClient
from services.scraper.browser_pool import BrowserPool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scraper")


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://elhaq:elhaq_pass@postgres:5432/elhaq")
STREAM = os.getenv("STREAM_PRICE_INGEST", "stream:price_ingest")
CONFIRMED_DEALS_STREAM = os.getenv("STREAM_CONFIRMED_DEALS", "stream:confirmed_deals")
FAILED_QUEUE = os.getenv("FAILED_QUEUE", "queue:failed_scrapes")
MAX_RETRIES = int(os.getenv("SCRAPER_MAX_RETRIES", "5"))
CONCURRENCY = int(os.getenv("SCRAPER_CONCURRENCY", "4"))

# Scraper targets source: 'file' (default), 'redis_stream', 'redis_list'
TARGETS_SOURCE = os.getenv("SCRAPER_TARGETS_SOURCE", "file")
TARGETS_STREAM = os.getenv("SCRAPER_TARGETS_STREAM", "stream:targets")
TARGETS_LIST = os.getenv("SCRAPER_TARGETS_LIST", "queue:targets")

# Proxy pool file (JSON array of proxies like host:port or dicts)
PROXIES_FILE = os.getenv("PROXIES_FILE", "proxies.json")


# Price extraction patterns - ordered by specificity
# Supports both English (EGP) and Arabic (جنيه) currency
PRICE_REGEXES = [
    # Amazon-specific patterns with Arabic currency
    r'class="[^"]*price[^"]*"[^>]*>.*?جنيه\s*([\d,]+(?:\.\d{1,2})?)',
    r'class="[^"]*price[^"]*"[^>]*>.*?([\d,]+(?:\.\d{1,2})?)\s*جنيه',
    # English EGP patterns
    r'class="[^"]*price[^"]*"[^>]*>.*?EGP\s*([\d,]+(?:\.\d{1,2})?)',
    r'class="[^"]*price[^"]*"[^>]*>.*?([\d,]+(?:\.\d{1,2})?)\s*EGP',
    # Generic patterns with both currencies
    r"جنيه[:\s]*([\d,]+(?:\.\d{1,2})?)",
    r"([\d,]+(?:\.\d{1,2})?)\s*جنيه",
    r"EGP[:\s]*([\d,]+(?:\.\d{1,2})?)",
    r"([\d,]+(?:\.\d{1,2})?)\s*EGP",
]
PRICE_PATTERNS = [re.compile(r, flags=re.IGNORECASE | re.DOTALL) for r in PRICE_REGEXES]
OUT_OF_STOCK_KEYWORDS = ["out of stock", "unavailable", "sold out", "غير متوفر", "نفد"]


async def check_alerts_for_sku(sku: str, scraped_price: float) -> List[Dict]:
    """Check if any user alerts should trigger for this SKU and price.
    
    Args:
        sku: Product SKU
        scraped_price: Current scraped price
        
    Returns:
        List of alert dictionaries that should trigger notifications
    """
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Find alerts where:
        # 1. target_url contains the SKU
        # 2. scraped_price <= target_price
        # 3. alert is active
        query = """
            SELECT a.id, a.user_id, a.target_url, a.target_price, u.phone
            FROM alerts a
            JOIN users u ON a.user_id = u.id
            WHERE a.active_status = TRUE
            AND a.target_url LIKE $1
            AND a.target_price >= $2
        """
        
        rows = await conn.fetch(query, f'%{sku}%', scraped_price)
        await conn.close()
        
        alerts = []
        for row in rows:
            alerts.append({
                'alert_id': row['id'],
                'user_id': row['user_id'],
                'phone': row['phone'],
                'target_url': row['target_url'],
                'target_price': float(row['target_price']),
                'scraped_price': scraped_price
            })
        
        if alerts:
            logger.info(f"🔔 Found {len(alerts)} alerts triggered for SKU {sku} at price {scraped_price}")
        
        return alerts
    except Exception as e:
        logger.error(f"❌ Failed to check alerts: {e}")
        return []


async def extract_product_title(page) -> str:
    """Extract product title using Playwright selectors.
    
    Returns the product title or empty string if not found.
    """
    # Amazon-specific title selectors
    selectors = [
        '#productTitle',
        'h1.product-title',
        '[data-feature-name="title"]',
        'h1[id*="title"]',
    ]
    
    for selector in selectors:
        try:
            element = await page.query_selector(selector)
            if element:
                title = await element.inner_text()
                return title.strip() if title else ""
        except Exception:
            continue
    
    return ""


async def extract_price_from_page(page) -> float:
    """Extract price using Playwright selectors (more accurate than regex).
    
    This is the preferred method for Amazon and similar sites.
    Falls back to regex extraction if selectors fail.
    """
    # Amazon-specific selectors
    selectors = [
        '.a-price-whole',
        '.a-offscreen',
        '#priceblock_ourprice',
        '#priceblock_dealprice',
        '.a-price .a-offscreen',
    ]
    
    for selector in selectors:
        try:
            elements = await page.query_selector_all(selector)
            for elem in elements:
                text = await elem.inner_text()
                if not text:
                    continue
                
                # Extract numbers from text (handles both "50,000.00" and "جنيه‎50,000.00‎")
                numbers = re.findall(r'([\d,]+(?:\.\d{1,2})?)', text)
                for num_str in numbers:
                    try:
                        price = float(num_str.replace(',', '').strip())
                        if price >= 10:  # Valid price threshold
                            return price
                    except (ValueError, TypeError):
                        continue
        except Exception:
            continue
    
    return 0.0


async def extract_price(html: str) -> float:
    """Extract a price value from raw HTML using regex patterns.

    Returns the parsed float price or `0.0` if no price could be extracted.
    Uses multiple patterns and filters out small numbers (likely ratings/reviews).
    """
    candidates = []
    
    for rx in PRICE_PATTERNS:
        matches = rx.findall(html)
        for match in matches:
            # Extract the number from the match (could be a string or tuple)
            price_str = match if isinstance(match, str) else match[0] if match else ""
            price_str = price_str.replace(",", "").strip()
            try:
                price = float(price_str)
                # Filter out small numbers (ratings, counts, etc.)
                # Real prices are typically > 10 EGP
                if price >= 10:
                    candidates.append(price)
            except (ValueError, TypeError):
                continue
    
    # Return the most common price if multiple found, or the first valid one
    if candidates:
        return candidates[0]
    
    return 0.0


async def check_in_stock_from_page(page) -> bool:
    """Check if product is in stock using Playwright selectors (more accurate).
    
    Checks for positive indicators like Add to Cart button.
    Returns True if in stock, False otherwise.
    """
    try:
        # Check for Add to Cart or Buy Now buttons (strong indicator of availability)
        add_to_cart = await page.query_selector('#add-to-cart-button')
        buy_now = await page.query_selector('#buy-now-button')
        
        if add_to_cart or buy_now:
            return True
        
        # Check availability section for positive messages
        availability = await page.query_selector('#availability')
        if availability:
            text = await availability.inner_text()
            text_lower = text.lower()
            
            # Positive indicators (in stock)
            positive_keywords = ['in stock', 'متوفر', 'تبقى', 'اطلبه']
            for keyword in positive_keywords:
                if keyword in text_lower:
                    return True
            
            # Negative indicators (out of stock)
            negative_keywords = ['currently unavailable', 'out of stock', 'sold out', 'غير متوفر', 'نفد']
            for keyword in negative_keywords:
                if keyword in text_lower:
                    return False
        
        # Default: assume in stock if no clear negative indicator
        return True
    except Exception:
        # Fallback to HTML-based check
        return True


async def check_in_stock(html: str) -> bool:
    """Fallback HTML-based stock check (less accurate).
    
    Only checks for explicit out-of-stock messages in main content.
    Returns False if out-of-stock keywords found, True otherwise.
    """
    low = html.lower()
    
    # Only check for very specific out-of-stock phrases in main content areas
    # Avoid false positives from variant selectors
    specific_out_of_stock = [
        'currently unavailable',
        'out of stock',
        'this item is out of stock',
        'sold out',
        'المنتج غير متوفر',  # Product not available
        'نفذت الكمية',  # Quantity exhausted
    ]
    
    for kw in specific_out_of_stock:
        if kw in low:
            return False
    
    return True


class ProxyPool:
    def __init__(self, proxies: List[Any]):
        """Simple in-memory proxy pool with temporary blacklist/backoff.

        Parameters
        - `proxies`: list of proxy descriptors (strings or dicts)
        """
        self.proxies = proxies
        # blacklist: proxy -> timestamp when it becomes available
        self.blacklist: Dict[str, float] = {}

    def _key(self, p: Any) -> str:
        """Normalize a proxy descriptor into a stable string key."""
        return p if isinstance(p, str) else json.dumps(p, sort_keys=True)

    def mark_failed(self, proxy: Any, backoff: int = 60):
        """Mark a proxy as failed and blackout for `backoff` seconds."""
        k = self._key(proxy)
        self.blacklist[k] = time.time() + backoff

    def get(self) -> Optional[Any]:
        """Return a random available proxy or `None` if none are available."""
        now = time.time()
        candidates = [
            p for p in self.proxies if self.blacklist.get(self._key(p), 0) <= now
        ]
        if not candidates:
            return None
        return random.choice(candidates)


async def fetch_target(  # noqa: C901
    target: Dict[str, Any],
    redis_client: RedisStreamClient,
    browser_pool: BrowserPool,
    proxy_pool: Optional[ProxyPool] = None,
):
    """Fetch a single target page using Playwright, extract price and publish
    to Redis.

    Retries are performed with exponential backoff. If all attempts fail the
    failed target is pushed to `FAILED_QUEUE` for later inspection.

    Parameters
    - `playwright`: the `async_playwright()` instance/context
    - `target`: mapping containing at least `url`, `sku`, and `store`
    - `redis_client`: `RedisStreamClient` used to publish results
    - `proxy_pool`: optional `ProxyPool` for rotating proxies

    Returns
    - `True` on success, `False` if all retries failed.
    """
    url = target.get("url")
    sku = target.get("sku")
    store = target.get("store")

    proxy = None
    if proxy_pool:
        p = proxy_pool.get()
        if p:
            if isinstance(p, str):
                proxy = {"server": p}
            elif isinstance(p, dict):
                proxy = p.copy()

    attempt = 0
    backoff = 1
    while attempt < MAX_RETRIES:
        attempt += 1
        browser = None
        context = None
        page = None
        try:
            # Acquire a browser from the pool
            browser = await browser_pool.acquire()
            context = (
                await browser.new_context(proxy=proxy)
                if proxy
                else await browser.new_context()
            )
            page = await context.new_page()
            # navigation timeout in ms (configurable)
            nav_timeout = int(os.getenv("SCRAPER_NAV_TIMEOUT_MS", "20000"))
            await page.goto(url, timeout=nav_timeout)
            
            # Extract product information
            product_title = await extract_product_title(page)
            
            # Try to extract price using Playwright selectors first (more accurate)
            price = await extract_price_from_page(page)
            
            # Check stock status using selectors (more accurate)
            in_stock = await check_in_stock_from_page(page)
            
            # Fallback to HTML regex if selector method fails
            if price == 0.0:
                html = await page.content()
                price = await extract_price(html)
            else:
                # Still get HTML for hash
                html = await page.content()
            
            # Offload CPU-heavy hash to threadpool
            html_hash = await asyncio.to_thread(
                lambda s=html: hashlib.sha256(s.encode("utf-8")).hexdigest()
            )

            # Map store ID to display name
            store_display_name = {
                "amazon_eg": "Amazon Egypt",
                "amazon_com": "Amazon",
                "jumia_eg": "Jumia Egypt",
                "noon_eg": "Noon",
            }.get(store, store)

            payload = {
                "sku": sku,
                "store": store,
                "store_name": store_display_name,
                "product_title": product_title,
                "url": url,
                "price": price,
                "timestamp": int(time.time()),
                "html_hash": html_hash,
                "in_stock": in_stock,
            }

            # Publish to price_ingest stream for analysis
            await redis_client.xadd(STREAM, {"payload": payload})
            logger.info("Pushed %s from %s (price=%s) to %s", sku, store, price, STREAM)
            
            # Check if any user alerts should trigger for this price
            triggered_alerts = await check_alerts_for_sku(sku, price)
            
            if triggered_alerts:
                # Publish to confirmed_deals for WhatsApp notifications
                store_display_name = {
                    "amazon_eg": "Amazon Egypt",
                    "amazon_com": "Amazon",
                    "jumia_eg": "Jumia Egypt",
                    "noon_eg": "Noon",
                }.get(store, store)
                
                for alert in triggered_alerts:
                    whatsapp_payload = {
                        "sku": sku,
                        "store": store_display_name,
                        "product_title": product_title,
                        "price": str(price),
                        "in_stock": str(in_stock).lower(),
                        "url": url,
                        "user_phone": alert['phone'],
                        "target_price": str(alert['target_price']),
                        "timestamp": int(time.time()),
                    }
                    await redis_client.xadd(CONFIRMED_DEALS_STREAM, whatsapp_payload)
                    logger.info(f"🔔 Pushed alert to WhatsApp for user {alert['phone']}: {sku} @ {price} EGP (target: {alert['target_price']})")
            else:
                logger.info(f"ℹ️ No alerts triggered for SKU {sku} at price {price}")

            # clean up page/context
            try:
                if page:
                    await page.close()
            except Exception:
                pass
            try:
                if context:
                    await context.close()
            except Exception:
                pass

            # release browser back to pool and return success
            await browser_pool.release(browser)
            return True
        except PlaywrightError as e:
            msg = str(e)
            logger.warning(
                "Playwright error fetching %s (attempt %d): %s", url, attempt, msg
            )
            if proxy and proxy_pool:
                proxy_pool.mark_failed(proxy, backoff=60)
            # release browser if acquired
            try:
                if browser:
                    await browser_pool.release(browser)
            except Exception:
                pass
            if attempt >= MAX_RETRIES:
                break
        except Exception as e:
            logger.exception("Error fetching %s (attempt %d): %s", url, attempt, e)
            try:
                if browser:
                    await browser_pool.release(browser)
            except Exception:
                pass
            if attempt >= MAX_RETRIES:
                break

        # exponential backoff with jitter
        jitter = random.uniform(0, 0.5 * backoff)
        await asyncio.sleep(backoff + jitter)
        backoff = min(backoff * 2, 30)

    # if we reached here, all retries failed; push to failed queue
    failure = {
        "sku": sku,
        "store": store,
        "url": url,
        "last_attempt_ts": int(time.time()),
        "attempts": attempt,
    }
    dumped = await asyncio.to_thread(json.dumps, failure)
    raw_redis = redis_client.redis
    try:
        await raw_redis.rpush(FAILED_QUEUE, dumped)
    except Exception:
        logger.exception("Failed to push failure to queue for %s", url)
    logger.error(
        "Failed to fetch %s after %d attempts; pushed to %s", url, attempt, FAILED_QUEUE
    )
    return False


async def run_from_file(path: str):
    """Load targets from `path` and run them with `run_targets`.

    Returns a list of results.
    """
    targets = load_targets(path)
    return await run_targets(targets)


async def run_targets(
    targets: List[Dict[str, Any]], proxy_pool: Optional[ProxyPool] = None
):
    """Run a collection of `targets` concurrently using Playwright.

    Parameters
    - `targets`: list of target dicts
    - `proxy_pool`: optional `ProxyPool`

    Returns a list of boolean results for each target.
    """
    redis_client = await RedisStreamClient.create(REDIS_URL)

    sem = asyncio.Semaphore(CONCURRENCY)

    async with async_playwright() as playwright:
        # create a browser pool sized by env or concurrency
        pool_size = int(
            os.getenv("BROWSER_POOL_SIZE", str(max(1, min(CONCURRENCY, 2))))
        )
        browser_pool = BrowserPool(playwright, max_browsers=pool_size)
        await browser_pool.start()

        async def sem_task(t):
            async with sem:
                return await fetch_target(t, redis_client, browser_pool, proxy_pool)

        tasks = [asyncio.create_task(sem_task(t)) for t in targets]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        await browser_pool.close()
        return results


async def run_from_redis_stream(
    consumer_name: str = "scraper-1", proxy_pool: Optional[ProxyPool] = None
):
    """Continuously read targets from a Redis stream and process them."""
    redis_client = await RedisStreamClient.create(REDIS_URL)
    await redis_client.ensure_group(TARGETS_STREAM, "cg_scraper", mkstream=True)

    async with async_playwright() as playwright:
        pool_size = int(
            os.getenv("BROWSER_POOL_SIZE", str(max(1, min(CONCURRENCY, 2))))
        )
        browser_pool = BrowserPool(playwright, max_browsers=pool_size)
        await browser_pool.start()
        while True:
            res = await redis_client.xreadgroup(
                "cg_scraper", consumer_name, {TARGETS_STREAM: ">"}, count=1, block=5000
            )
            if not res:
                await asyncio.sleep(0.1)
                continue
            for _stream, messages in res:
                for msg_id, fields in messages:
                    payload_b = fields.get(b"payload") or fields.get("payload")
                    try:
                        target = (
                            json.loads(payload_b)
                            if isinstance(payload_b, (bytes, bytearray))
                            else payload_b
                        )
                    except Exception:
                        target = payload_b
                    try:
                        await fetch_target(
                            target, redis_client, browser_pool, proxy_pool
                        )
                        await redis_client.xack(TARGETS_STREAM, "cg_scraper", msg_id)
                    except Exception:
                        # on failure, leave message pending for retry
                        logger.exception(
                            "Failed processing target from stream: %s", msg_id
                        )

        await browser_pool.close()


async def run_from_redis_list(proxy_pool: Optional[ProxyPool] = None):
    """Continuously consume targets from a Redis list (blocking left pop)."""
    redis_client = await RedisStreamClient.create(REDIS_URL)
    raw = redis_client.redis
    async with async_playwright() as playwright:
        pool_size = int(
            os.getenv("BROWSER_POOL_SIZE", str(max(1, min(CONCURRENCY, 2))))
        )
        browser_pool = BrowserPool(playwright, max_browsers=pool_size)
        await browser_pool.start()
        while True:
            item = await raw.blpop(TARGETS_LIST, timeout=5)
            if not item:
                await asyncio.sleep(0.1)
                continue
            # item is (listname, payload)
            payload = item[1]
            try:
                target = json.loads(payload)
            except Exception:
                target = payload
            try:
                await fetch_target(target, redis_client, browser_pool, proxy_pool)
            except Exception:
                logger.exception("Failed processing target from list")

        await browser_pool.close()


def load_targets(path: str) -> List[Dict[str, Any]]:
    """Load targets JSON from `path` and return list of target dicts."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--targets", default="services/scraper/targets_example.json", help="path to targets JSON file"
    )
    args = parser.parse_args()

    if TARGETS_SOURCE == "file":
        tg = load_targets(args.targets)
        asyncio.run(run_targets(tg))
    elif TARGETS_SOURCE == "redis_stream":
        asyncio.run(run_from_redis_stream())
    elif TARGETS_SOURCE == "redis_list":
        asyncio.run(run_from_redis_list())
    elif TARGETS_SOURCE == "both":
        # Run both file and stream
        tg = load_targets(args.targets)
        asyncio.run(asyncio.gather(run_targets(tg), run_from_redis_stream()))
    else:
        print(f"Unknown TARGETS_SOURCE: {TARGETS_SOURCE}")
        exit(1)
