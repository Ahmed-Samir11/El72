import os
import asyncio
import json
import logging
import time
import hashlib
import random
import re
from typing import Dict, Any, List, Optional

from playwright.async_api import async_playwright, Error as PlaywrightError

from services.common.redis_client import RedisStreamClient

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


# simple price regexes
PRICE_REGEXES = [r"EGP\s*([\d,]+(?:\.\d{1,2})?)", r"([\d,]+(?:\.\d{1,2})?)\s*EGP", r"([\d,]+(?:\.\d{1,2})?)"]
OUT_OF_STOCK_KEYWORDS = ["out of stock", "unavailable", "sold out", "غير متوفر", "نفد"]


async def extract_price(html: str) -> float:
    """Extract a price value (EGP) from raw `html` using configured regexes.

    Returns the parsed float price or `0.0` if no price could be extracted.
    """
    for rx in PRICE_REGEXES:
        m = re.search(rx, html, flags=re.IGNORECASE)
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
        candidates = [p for p in self.proxies if self.blacklist.get(self._key(p), 0) <= now]
        if not candidates:
            return None
        return random.choice(candidates)


async def fetch_target(playwright, target: Dict[str, Any], redis_client: RedisStreamClient, proxy_pool: Optional[ProxyPool] = None):
    """Fetch a single target page using Playwright, extract price and publish to Redis.

    Retries are performed with exponential backoff. If all attempts fail the failed target is
    pushed to `FAILED_QUEUE` for later inspection.

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

    browser = None
    attempt = 0
    backoff = 1
    while attempt < MAX_RETRIES:
        attempt += 1
        try:
            browser = await playwright.chromium.launch(headless=True, proxy=proxy)
            context = await browser.new_context()
            page = await context.new_page()
            response = await page.goto(url, timeout=60000)
            status = response.status if response else None
            html = await page.content()
            html_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()

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

            await page.close()
            await context.close()
            if browser:
                await browser.close()
            return True
        except PlaywrightError as e:
            msg = str(e)
            logger.warning("Playwright error fetching %s (attempt %d): %s", url, attempt, msg)
            # retry on common transient errors
            # mark proxy as failed if present
            if proxy and proxy_pool:
                proxy_pool.mark_failed(proxy, backoff=60)
            if attempt >= MAX_RETRIES:
                break
        except Exception as e:
            logger.exception("Error fetching %s (attempt %d): %s", url, attempt, e)
            if attempt >= MAX_RETRIES:
                break
        finally:
            try:
                if browser:
                    await browser.close()
            except Exception:
                pass

        # exponential backoff with jitter
        jitter = random.uniform(0, 0.5 * backoff)
        await asyncio.sleep(backoff + jitter)
        backoff = min(backoff * 2, 30)

    # if we reached here, all retries failed; push to failed queue
    failure = {"sku": sku, "store": store, "url": url, "last_attempt_ts": int(time.time()), "attempts": attempt}
    # Use raw aioredis to rpush to queue
    raw_redis = redis_client.redis
    await raw_redis.rpush(FAILED_QUEUE, json.dumps(failure))
    logger.error("Failed to fetch %s after %d attempts; pushed to %s", url, attempt, FAILED_QUEUE)
    return False


async def run_from_file(path: str):
    """Load targets from `path` and run them with `run_targets`. Returns list of results."""
    targets = load_targets(path)
    return await run_targets(targets)


async def run_targets(targets: List[Dict[str, Any]], proxy_pool: Optional[ProxyPool] = None):
    """Run a collection of `targets` concurrently using Playwright.

    Parameters
    - `targets`: list of target dicts
    - `proxy_pool`: optional `ProxyPool`

    Returns a list of boolean results for each target.
    """
    redis_client = await RedisStreamClient.create(REDIS_URL)

    sem = asyncio.Semaphore(CONCURRENCY)

    async with async_playwright() as playwright:
        async def sem_task(t):
            async with sem:
                return await fetch_target(playwright, t, redis_client, proxy_pool)

        tasks = [asyncio.create_task(sem_task(t)) for t in targets]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return results


async def run_from_redis_stream(consumer_name: str = "scraper-1", proxy_pool: Optional[ProxyPool] = None):
    """Continuously read targets from a Redis stream and process them."""
    redis_client = await RedisStreamClient.create(REDIS_URL)
    await redis_client.ensure_group(TARGETS_STREAM, "cg_scraper", mkstream=True)

    async with async_playwright() as playwright:
        while True:
            res = await redis_client.xreadgroup("cg_scraper", consumer_name, {TARGETS_STREAM: ">"}, count=1, block=5000)
            if not res:
                await asyncio.sleep(0.1)
                continue
            for stream, messages in res:
                for msg_id, fields in messages:
                    payload_b = fields.get(b"payload") or fields.get("payload")
                    try:
                        target = json.loads(payload_b) if isinstance(payload_b, (bytes, bytearray)) else payload_b
                    except Exception:
                        target = payload_b
                    try:
                        await fetch_target(playwright, target, redis_client, proxy_pool)
                        await redis_client.xack(TARGETS_STREAM, "cg_scraper", msg_id)
                    except Exception:
                        # on failure, leave message pending for retry
                        logger.exception("Failed processing target from stream: %s", msg_id)


async def run_from_redis_list(proxy_pool: Optional[ProxyPool] = None):
    """Continuously consume targets from a Redis list (blocking left pop)."""
    redis_client = await RedisStreamClient.create(REDIS_URL)
    raw = redis_client.redis
    async with async_playwright() as playwright:
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
                await fetch_target(playwright, target, redis_client, proxy_pool)
            except Exception:
                logger.exception("Failed processing target from list")


def load_targets(path: str) -> List[Dict[str, Any]]:
    """Load targets JSON from `path` and return list of target dicts."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--targets", default="targets_example.json", help="path to targets JSON file")
    args = parser.parse_args()

    tg = load_targets(args.targets)
    asyncio.run(run_targets(tg))
