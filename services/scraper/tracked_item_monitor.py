"""Tracked Item Price Monitor - Main Orchestration Service.

This service:
1. Fetches active tracked items from the database every 30 seconds
2. Orchestrates scraping across multiple stores for each item
3. Processes prices and detects changes
4. Emits alert events when conditions are met
5. Handles failures gracefully with retries and error tracking
"""

import asyncio
import logging
import os
import signal
import time
from typing import Dict, List
from prometheus_client import Counter, Gauge, Histogram, start_http_server

import asyncpg
from playwright.async_api import Browser, async_playwright

from services.common.redis_client import RedisStreamClient
from services.scraper.alert_emitter import AlertEmitter
from services.scraper.browser_pool import BrowserPool
from services.scraper.price_processor import PriceProcessor
from services.scraper.store_scrapers import ScrapeResult, ScraperFactory

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


MONITOR_CYCLES = Counter(
    "el72_tracked_monitor_cycles_total",
    "Completed tracked-item monitor cycles",
)

MONITOR_CYCLE_ERRORS = Counter(
    "el72_tracked_monitor_cycle_errors_total",
    "Tracked-item monitor cycle errors",
)

MONITOR_CYCLE_DURATION = Histogram(
    "el72_tracked_monitor_cycle_duration_seconds",
    "Tracked-item monitor cycle duration in seconds",
)

MONITOR_ACTIVE_ITEMS = Gauge(
    "el72_tracked_monitor_active_items",
    "Active tracked items discovered in the latest cycle",
)

MONITOR_ITEM_ERRORS = Counter(
    "el72_tracked_monitor_item_errors_total",
    "Unexpected tracked-item processing errors",
)

MONITOR_STORE_SCRAPES = Counter(
    "el72_tracked_monitor_store_scrapes_total",
    "Store scraping outcomes",
    ["outcome"],
)

class TrackedItemMonitor:
    """Main orchestrator for tracked item price monitoring."""

    def __init__(
        self,
        db_pool: asyncpg.Pool,
        timescale_pool: asyncpg.Pool,
        redis_client: RedisStreamClient,
        browser_pool: BrowserPool,
        scrape_interval: int = 30,
        max_concurrent_scrapes: int = 10,
    ):
        """Initialize the monitor.

        Args:
            db_pool: Operational PostgreSQL connection pool
            timescale_pool: TimescaleDB connection pool for price history
            redis_client: Redis client for alert events
            browser_pool: Browser pool for Playwright scraping
            scrape_interval: Seconds between scrape cycles (default 30)
            max_concurrent_scrapes: Max concurrent scraping tasks
        """
        self.db_pool = db_pool
        self.timescale_pool = timescale_pool
        self.redis_client = redis_client
        self.browser_pool = browser_pool
        self.scrape_interval = scrape_interval
        self.max_concurrent_scrapes = max_concurrent_scrapes

        # Initialize processors
        self.price_processor = PriceProcessor(db_pool, timescale_pool)
        self.alert_emitter = AlertEmitter(redis_client)

        # Tracking state
        self.running = False
        self._shutdown_event = asyncio.Event()

    async def fetch_tracked_items(self) -> List[Dict]:
        """Fetch all active tracked items with their store mappings.

        Returns:
            List of tracked item dictionaries
        """
        async with self.db_pool.acquire() as conn:
            query = """
                SELECT
                    ti.id AS tracked_item_id,
                    ti.user_id,
                    ti.canonical_product_id,
                    ti.target_price,
                    tis.store_id,
                    tis.store_sku,
                    tis.store_url
                FROM tracked_items ti
                JOIN tracked_item_stores tis ON ti.id = tis.tracked_item_id
                WHERE ti.is_active = TRUE AND tis.is_active = TRUE
                ORDER BY ti.id
            """
            rows = await conn.fetch(query)

            # Group by tracked_item_id to get all store mappings per item
            items_dict = {}
            for row in rows:
                item_id = row["tracked_item_id"]
                if item_id not in items_dict:
                    items_dict[item_id] = {
                        "tracked_item_id": item_id,
                        "user_id": row["user_id"],
                        "canonical_product_id": row["canonical_product_id"],
                        "target_price": (
                            float(row["target_price"]) if row["target_price"] else None
                        ),
                        "stores": [],
                    }

                items_dict[item_id]["stores"].append(
                    {
                        "store_id": row["store_id"],
                        "store_sku": row["store_sku"],
                        "store_url": row["store_url"],
                    }
                )

            return list(items_dict.values())

    async def scrape_tracked_item(
        self, tracked_item: Dict, browser: Browser
    ) -> List[ScrapeResult]:
        """Scrape all stores for a tracked item and record outcomes."""
        results = []
        canonical_id = tracked_item["canonical_product_id"]

        for store_mapping in tracked_item["stores"]:
            store_id = store_mapping["store_id"]
            url = store_mapping["store_url"]

            try:
                scraper = ScraperFactory.get_scraper(store_id)
                if not scraper:
                    MONITOR_STORE_SCRAPES.labels(outcome="no_scraper").inc()
                    logger.warning("No scraper available for store: %s", store_id)
                    continue

                context = await browser.new_context()
                try:
                    page = await context.new_page()
                    try:
                        result = await scraper.scrape(page, url, canonical_id)
                    finally:
                        await page.close()
                finally:
                    await context.close()

                if result:
                    results.append(result)
                    MONITOR_STORE_SCRAPES.labels(outcome="success").inc()
                    logger.info(
                        "Successfully scraped %s for item %s: price=%s %s, in_stock=%s",
                        store_id,
                        canonical_id,
                        result.price,
                        result.currency,
                        result.in_stock,
                    )
                else:
                    MONITOR_STORE_SCRAPES.labels(outcome="failure").inc()
                    logger.warning("Scrape failed for %s at %s", store_id, url)
                    await self.alert_emitter.emit_scrape_failure(
                        tracked_item["tracked_item_id"],
                        tracked_item["user_id"],
                        store_id,
                        url,
                        "Scrape returned no result",
                    )

            except Exception as e:
                MONITOR_STORE_SCRAPES.labels(outcome="exception").inc()
                logger.exception(
                    "Error scraping %s for %s: %s",
                    store_id,
                    canonical_id,
                    e,
                )
                await self.alert_emitter.emit_scrape_failure(
                    tracked_item["tracked_item_id"],
                    tracked_item["user_id"],
                    store_id,
                    url,
                    str(e),
                )

        return results

    async def process_scrape_results(
        self, tracked_item: Dict, results: List[ScrapeResult]
    ):
        """Process scrape results: update prices, detect changes, emit alerts.

        Args:
            tracked_item: Tracked item dictionary
            results: List of scrape results from stores
        """
        tracked_item_id = tracked_item["tracked_item_id"]
        user_id = tracked_item["user_id"]
        target_price = tracked_item.get("target_price")

        # Convert target price to USD if it exists
        if target_price:
            target_price_usd = self.price_processor.convert_to_usd(target_price, "EGP")
        else:
            target_price_usd = None

        for result in results:
            try:
                # Process the price (convert, detect changes, update DB)
                processing_result = await self.price_processor.process_scrape_result(
                    result, tracked_item_id
                )

                # Check and emit alerts based on processing result
                await self.alert_emitter.check_and_emit_alerts(
                    tracked_item_id=tracked_item_id,
                    user_id=user_id,
                    store_id=result.store,
                    canonical_product_id=result.canonical_product_id,
                    url=result.url,
                    processing_result=processing_result,
                    target_price=target_price_usd,
                )

            except Exception as e:
                MONITOR_ITEM_ERRORS.inc()
                logger.exception(
                    f"Error processing result for item {tracked_item_id} "
                    f"from {result.store}: {e}"
                )

    async def scrape_cycle(self):
        """Execute one scraping cycle and record its metrics."""
        cycle_start = time.monotonic()
        logger.info("=== Starting scrape cycle ===")

        try:
            tracked_items = await self.fetch_tracked_items()
            MONITOR_ACTIVE_ITEMS.set(len(tracked_items))
            logger.info("Found %d active tracked items", len(tracked_items))

            if not tracked_items:
                logger.info("No tracked items to process")
                return

            semaphore = asyncio.Semaphore(self.max_concurrent_scrapes)

            async def process_item(item: Dict):
                async with semaphore:
                    browser = await self.browser_pool.acquire()
                    try:
                        results = await self.scrape_tracked_item(item, browser)

                        if results:
                            await self.process_scrape_results(item, results)
                        else:
                            logger.warning(
                                "No successful scrapes for tracked_item_id=%s",
                                item["tracked_item_id"],
                            )
                    finally:
                        await self.browser_pool.release(browser)

            tasks = [process_item(item) for item in tracked_items]
            task_results = await asyncio.gather(
                *tasks, return_exceptions=True
            )

            for item, result in zip(tracked_items, task_results):
                if isinstance(result, Exception):
                    MONITOR_ITEM_ERRORS.inc()
                    logger.error(
                        "Tracked-item task failed for item %s: %s",
                        item["tracked_item_id"],
                        result,
                        exc_info=(
                            type(result),
                            result,
                            result.__traceback__,
                        ),
                    )

        except Exception:
            MONITOR_CYCLE_ERRORS.inc()
            logger.exception("Error in scrape cycle")

        finally:
            duration = time.monotonic() - cycle_start
            MONITOR_CYCLES.inc()
            MONITOR_CYCLE_DURATION.observe(duration)
            logger.info("=== Scrape cycle completed in %.2fs ===", duration)

    async def run(self):
        """Main run loop - execute scraping cycles at regular intervals."""
        self.running = True
        logger.info(
            f"Starting tracked item monitor (interval: {self.scrape_interval}s, "
            f"max_concurrent: {self.max_concurrent_scrapes})"
        )

        try:
            while self.running:
                # Execute scrape cycle
                await self.scrape_cycle()

                # Wait for next cycle or shutdown signal
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(), timeout=self.scrape_interval
                    )
                    # If we get here, shutdown was signaled
                    break
                except asyncio.TimeoutError:
                    # Normal timeout, continue to next cycle
                    pass

        except Exception as e:
            logger.exception(f"Fatal error in monitor run loop: {e}")

        finally:
            logger.info("Tracked item monitor stopped")

    async def shutdown(self):
        """Gracefully shutdown the monitor."""
        logger.info("Shutting down tracked item monitor...")
        self.running = False
        self._shutdown_event.set()


async def main():
    """Main entry point for the tracked item monitor service."""
    # Configuration from environment
    DATABASE_URL = os.getenv(
        "DATABASE_URL", "postgresql://elhaq:elhaq_pass@localhost:5432/elhaq"
    )
    TIMESCALE_URL = os.getenv(
        "TIMESCALE_URL", "postgresql://elhaq:elhaq_pass@localhost:5433/elhaq_ts"
    )
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
    SCRAPE_INTERVAL = int(os.getenv("SCRAPE_INTERVAL", "30"))
    MAX_CONCURRENT_SCRAPES = int(os.getenv("MAX_CONCURRENT_SCRAPES", "10"))
    BROWSER_POOL_SIZE = int(os.getenv("BROWSER_POOL_SIZE", "5"))

    # Initialize database pool
    logger.info(f"Connecting to database: {DATABASE_URL}")
    db_pool = await asyncpg.create_pool(
        DATABASE_URL, min_size=2, max_size=10, command_timeout=60
    )
    timescale_pool = await asyncpg.create_pool(
        TIMESCALE_URL, min_size=2, max_size=10, command_timeout=60
    )

    # Initialize Redis client
    logger.info(f"Connecting to Redis: {REDIS_URL}")
    redis_client = await RedisStreamClient.create(REDIS_URL)

    # Initialize browser pool
    logger.info("Starting browser pool...")
    async with async_playwright() as playwright:
        browser_pool = BrowserPool(playwright, max_browsers=BROWSER_POOL_SIZE)
        await browser_pool.start()

        # Create monitor instance
        monitor = TrackedItemMonitor(
            db_pool=db_pool,
            timescale_pool=timescale_pool,
            redis_client=redis_client,
            browser_pool=browser_pool,
            scrape_interval=SCRAPE_INTERVAL,
            max_concurrent_scrapes=MAX_CONCURRENT_SCRAPES,
        )

        # Setup signal handlers for graceful shutdown
        loop = asyncio.get_event_loop()

        def signal_handler(sig):
            logger.info(f"Received signal {sig}, initiating shutdown...")
            asyncio.create_task(monitor.shutdown())

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))

        try:
            # Run the monitor
            await monitor.run()

        finally:
            # Cleanup
            logger.info("Cleaning up resources...")
            await browser_pool.close()
            await redis_client.close()
            await db_pool.close()
            await timescale_pool.close()
            logger.info("Shutdown complete")


if __name__ == "__main__":
    metrics_port = int(os.getenv("METRICS_PORT", "8000"))
    start_http_server(metrics_port, addr="0.0.0.0")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        exit(1)
