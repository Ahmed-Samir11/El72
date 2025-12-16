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

from services.common.redis_client import RedisStreamClient
from services.scraper.browser_pool import BrowserPool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scraper")


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
STREAM = os.getenv("STREAM_PRICE_INGEST", "stream:price_ingest")
FAILED_QUEUE = os.getenv("FAILED_QUEUE", "queue:failed_scrapes")
MAX_RETRIES = int(os.getenv("SCRAPER_MAX_RETRIES", "5"))
CONCURRENCY = int(os.getenv("SCRAPER_CONCURRENCY", "4"))

# Scraper targets source: 'file' (default), 'redis_stream', 'redis_list'
TARGETS_SOURCE = os.getenv("SCRAPER_TARGETS_SOURCE", "file")
TARGETS_STREAM = os.getenv("SCRAPER_TARGETS_STREAM", "stream:targets")
TARGETS_LIST = os.getenv("SCRAPER_TARGETS_LIST", "queue:targets")

# Proxy pool file (JSON array of proxies like host:port or dicts)
PROXIES_FILE = os.getenv("PROXIES_FILE", "proxies.json")


# simple price regexes (precompiled for performance)
PRICE_REGEXES = [
    r"EGP\s*([\d,]+(?:\.\d{1,2})?)",
    r"([\d,]+(?:\.\d{1,2})?)\s*EGP",
    r"([\d,]+(?:\.\d{1,2})?)",
]
PRICE_PATTERNS = [re.compile(r, flags=re.IGNORECASE) for r in PRICE_REGEXES]
OUT_OF_STOCK_KEYWORDS = ["out of stock", "unavailable", "sold out", "غير متوفر", "نفد"]


async def extract_price(html: str) -> float:
    """Extract a price value (EGP) from raw `html` using configured regexes.

    Returns the parsed float price or `0.0` if no price could be extracted.
    """
    for rx in PRICE_PATTERNS:
        m = rx.search(html)
        if m:
            s = m.group(1).replace(",", "")
            try:
                return float(s)
            except Exception:
                continue
    return 0.0


async def check_in_stock(html: str) -> bool:
    """Check if `html` suggests the product is in stock.

    Returns `False` if any out-of-stock keywords are found, `True` otherwise.
    """
    low = html.lower()
    for kw in OUT_OF_STOCK_KEYWORDS:
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
            html = await page.content()
            # Offload CPU-heavy hash to threadpool
            html_hash = await asyncio.to_thread(
                lambda s=html: hashlib.sha256(s.encode("utf-8")).hexdigest()
            )

            price = await extract_price(html)
            in_stock = await check_in_stock(html)

            payload = {
                "sku": sku,
                "store": store,
                "url": url,
                "price": price,
                "timestamp": int(time.time()),
                "html_hash": html_hash,
                "in_stock": in_stock,
            }

            await redis_client.xadd(STREAM, {"payload": payload})
            logger.info("Pushed %s from %s (price=%s) to %s", sku, store, price, STREAM)

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
        "--targets", default="targets_example.json", help="path to targets JSON file"
    )
    args = parser.parse_args()

    tg = load_targets(args.targets)
    asyncio.run(run_targets(tg))
