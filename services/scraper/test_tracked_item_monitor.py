"""Tests for tracked item monitor orchestration (mocked deps)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.scraper.store_scrapers import ScrapeResult
from services.scraper.tracked_item_monitor import TrackedItemMonitor
from services.scraper import tracked_item_monitor as monitor_module

@pytest.fixture
def monitor():
    db_pool = MagicMock()
    timescale_pool = MagicMock()
    redis = AsyncMock()
    browser_pool = AsyncMock()
    return TrackedItemMonitor(
        db_pool,
        timescale_pool,
        redis,
        browser_pool,
        scrape_interval=0,
        max_concurrent_scrapes=2,
    )


@pytest.mark.asyncio
async def test_fetch_tracked_items_groups_stores(monitor):
    conn = AsyncMock()
    conn.fetch.return_value = [
        {
            "tracked_item_id": 1,
            "user_id": 9,
            "canonical_product_id": "p1",
            "target_price": 100,
            "store_id": "amazon_eg",
            "store_sku": "A",
            "store_url": "https://a",
        },
        {
            "tracked_item_id": 1,
            "user_id": 9,
            "canonical_product_id": "p1",
            "target_price": 100,
            "store_id": "noon",
            "store_sku": "N",
            "store_url": "https://n",
        },
    ]
    monitor.db_pool.acquire.return_value.__aenter__.return_value = conn
    monitor.db_pool.acquire.return_value.__aexit__.return_value = False

    items = await monitor.fetch_tracked_items()
    assert len(items) == 1
    assert len(items[0]["stores"]) == 2


@pytest.mark.asyncio
async def test_scrape_tracked_item_success_failure_and_exception(monitor):
    browser = AsyncMock()
    context = AsyncMock()
    page = AsyncMock()
    browser.new_context.return_value = context
    context.new_page.return_value = page

    good = ScrapeResult(
        store="amazon_eg",
        canonical_product_id="p",
        price=10,
        currency="EGP",
        in_stock=True,
        url="https://a",
    )
    scraper_ok = AsyncMock()
    scraper_ok.scrape = AsyncMock(return_value=good)
    scraper_fail = AsyncMock()
    scraper_fail.scrape = AsyncMock(return_value=None)

    monitor.alert_emitter = AsyncMock()

    item = {
        "tracked_item_id": 1,
        "user_id": 2,
        "canonical_product_id": "p",
        "stores": [
            {"store_id": "amazon_eg", "store_sku": "A", "store_url": "https://a"},
            {"store_id": "noon", "store_sku": "N", "store_url": "https://n"},
            {"store_id": "unknown", "store_sku": "U", "store_url": "https://u"},
        ],
    }

    def get_scraper(store_id):
        if store_id == "amazon_eg":
            return scraper_ok
        if store_id == "noon":
            return scraper_fail
        return None

    with patch(
        "services.scraper.tracked_item_monitor.ScraperFactory.get_scraper",
        side_effect=get_scraper,
    ):
        results = await monitor.scrape_tracked_item(item, browser)

    assert len(results) == 1
    monitor.alert_emitter.emit_scrape_failure.assert_awaited()

    # Exception path
    boom_scraper = AsyncMock()
    boom_scraper.scrape = AsyncMock(side_effect=RuntimeError("boom"))
    item2 = {
        "tracked_item_id": 1,
        "user_id": 2,
        "canonical_product_id": "p",
        "stores": [
            {"store_id": "amazon_eg", "store_sku": "A", "store_url": "https://a"}
        ],
    }
    with patch(
        "services.scraper.tracked_item_monitor.ScraperFactory.get_scraper",
        return_value=boom_scraper,
    ):
        assert await monitor.scrape_tracked_item(item2, browser) == []


@pytest.mark.asyncio
async def test_process_scrape_results(monitor):
    monitor.price_processor = AsyncMock()
    monitor.price_processor.convert_to_usd.return_value = 3.2
    monitor.price_processor.process_scrape_result = AsyncMock(
        return_value={"price_changed": True}
    )
    monitor.alert_emitter = AsyncMock()

    result = ScrapeResult(
        store="amazon_eg",
        canonical_product_id="p",
        price=100,
        currency="EGP",
        in_stock=True,
        url="https://a",
    )
    await monitor.process_scrape_results(
        {"tracked_item_id": 1, "user_id": 2, "target_price": 100},
        [result],
    )
    monitor.alert_emitter.check_and_emit_alerts.assert_awaited()

    monitor.price_processor.process_scrape_result.side_effect = Exception("fail")
    await monitor.process_scrape_results(
        {"tracked_item_id": 1, "user_id": 2, "target_price": None},
        [result],
    )


@pytest.mark.asyncio
async def test_scrape_cycle_and_run_shutdown(monitor):
    monitor.fetch_tracked_items = AsyncMock(
        return_value=[
            {
                "tracked_item_id": 1,
                "user_id": 2,
                "canonical_product_id": "p",
                "target_price": None,
                "stores": [],
            }
        ]
    )
    monitor.scrape_tracked_item = AsyncMock(return_value=[])
    monitor.process_scrape_results = AsyncMock()
    monitor.browser_pool.acquire.return_value = AsyncMock()

    await monitor.scrape_cycle()
    monitor.browser_pool.release.assert_awaited()

    monitor.fetch_tracked_items = AsyncMock(return_value=[])
    await monitor.scrape_cycle()

    monitor.scrape_cycle = AsyncMock()
    monitor.scrape_interval = 0.01
    run_task = __import__("asyncio").create_task(monitor.run())
    await __import__("asyncio").sleep(0.03)
    await monitor.shutdown()
    await run_task
    assert monitor.running is False

@pytest.mark.asyncio
async def test_empty_cycle_updates_metrics(monitor, monkeypatch):
    cycles = MagicMock()
    errors = MagicMock()
    duration = MagicMock()
    active_items = MagicMock()

    monkeypatch.setattr(monitor_module, "MONITOR_CYCLES", cycles)
    monkeypatch.setattr(monitor_module, "MONITOR_CYCLE_ERRORS", errors)
    monkeypatch.setattr(monitor_module, "MONITOR_CYCLE_DURATION", duration)
    monkeypatch.setattr(monitor_module, "MONITOR_ACTIVE_ITEMS", active_items)

    monitor.fetch_tracked_items = AsyncMock(return_value=[])

    await monitor.scrape_cycle()

    cycles.inc.assert_called_once_with()
    errors.inc.assert_not_called()
    duration.observe.assert_called_once()
    assert duration.observe.call_args.args[0] >= 0
    active_items.set.assert_called_once_with(0)


@pytest.mark.asyncio
async def test_cycle_fetch_failure_updates_error_metrics(monitor, monkeypatch):
    cycles = MagicMock()
    errors = MagicMock()
    duration = MagicMock()

    monkeypatch.setattr(monitor_module, "MONITOR_CYCLES", cycles)
    monkeypatch.setattr(monitor_module, "MONITOR_CYCLE_ERRORS", errors)
    monkeypatch.setattr(monitor_module, "MONITOR_CYCLE_DURATION", duration)

    monitor.fetch_tracked_items = AsyncMock(
        side_effect=RuntimeError("database unavailable")
    )

    await monitor.scrape_cycle()

    cycles.inc.assert_called_once_with()
    errors.inc.assert_called_once_with()
    duration.observe.assert_called_once()


@pytest.mark.asyncio
async def test_item_task_exception_updates_item_error_metric(
    monitor, monkeypatch
):
    item_errors = MagicMock()
    monkeypatch.setattr(
        monitor_module, "MONITOR_ITEM_ERRORS", item_errors
    )

    monitor.fetch_tracked_items = AsyncMock(
        return_value=[
            {
                "tracked_item_id": 42,
                "user_id": 2,
                "canonical_product_id": "p",
                "target_price": None,
                "stores": [],
            }
        ]
    )
    monitor.browser_pool.acquire.side_effect = RuntimeError(
        "browser unavailable"
    )

    await monitor.scrape_cycle()

    item_errors.inc.assert_called_once_with()
