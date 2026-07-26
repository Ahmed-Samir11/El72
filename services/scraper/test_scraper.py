"""Expanded tests for scraper core helpers and fetch_target."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import Error as PlaywrightError

from services.scraper import scraper as scraper_mod
from services.scraper.scraper import (
    ProxyPool,
    check_alerts_for_sku,
    check_in_stock,
    check_in_stock_from_page,
    extract_price,
    extract_price_from_page,
    extract_product_title,
    fetch_target,
    load_targets,
)


@pytest.mark.asyncio
async def test_extract_price_arabic_and_class_patterns():
    html = '<span class="price">جنيه 1,250.50</span>'
    assert await extract_price(html) == 1250.50


@pytest.mark.asyncio
async def test_check_in_stock_arabic_phrases():
    assert await check_in_stock("<div>المنتج غير متوفر</div>") is False
    assert await check_in_stock("<div>available now</div>") is True


@pytest.mark.asyncio
async def test_extract_product_title_success_and_fallback():
    page = AsyncMock()
    el = AsyncMock()
    el.inner_text.return_value = "  Cool Product  "
    page.query_selector.side_effect = [None, el]
    assert await extract_product_title(page) == "Cool Product"

    page.query_selector.side_effect = Exception("boom")
    # first selector raises, then all fail via continue... need always None/raise
    page.query_selector = AsyncMock(side_effect=Exception("boom"))
    assert await extract_product_title(page) == ""


@pytest.mark.asyncio
async def test_extract_price_from_page():
    page = AsyncMock()
    el = AsyncMock()
    el.inner_text.return_value = "EGP 2,500.00"
    page.query_selector_all.return_value = [el]
    assert await extract_price_from_page(page) == 2500.0

    page.query_selector_all.return_value = []
    assert await extract_price_from_page(page) == 0.0


@pytest.mark.asyncio
async def test_check_in_stock_from_page_paths():
    page = AsyncMock()
    page.query_selector.side_effect = [AsyncMock(), None]  # add-to-cart present
    assert await check_in_stock_from_page(page) is True

    avail = AsyncMock()
    avail.inner_text.return_value = "Currently unavailable"
    page.query_selector.side_effect = [None, None, avail]
    assert await check_in_stock_from_page(page) is False

    avail.inner_text.return_value = "In Stock"
    page.query_selector.side_effect = [None, None, avail]
    assert await check_in_stock_from_page(page) is True

    page.query_selector.side_effect = Exception("x")
    assert await check_in_stock_from_page(page) is True


@pytest.mark.asyncio
async def test_check_alerts_for_sku_success_and_error():
    conn = AsyncMock()
    conn.fetch.return_value = [
        {
            "id": 1,
            "user_id": 2,
            "phone": "+20111",
            "target_url": "https://x/SKU",
            "target_price": 100,
        }
    ]
    with patch("services.scraper.scraper.asyncpg.connect", new=AsyncMock(return_value=conn)):
        alerts = await check_alerts_for_sku("SKU", 90)
    assert len(alerts) == 1
    assert alerts[0]["phone"] == "+20111"

    with patch(
        "services.scraper.scraper.asyncpg.connect",
        new=AsyncMock(side_effect=Exception("db")),
    ):
        assert await check_alerts_for_sku("SKU", 90) == []


def test_proxy_pool_blacklist_and_empty():
    pool = ProxyPool(["p1", {"server": "p2"}])
    assert pool.get() in (["p1", {"server": "p2"}][0], {"server": "p2"}, "p1")
    pool.mark_failed("p1", backoff=9999)
    pool.mark_failed({"server": "p2"}, backoff=9999)
    assert pool.get() is None


def test_load_targets(tmp_path):
    path = tmp_path / "targets.json"
    path.write_text(json.dumps([{"url": "u", "sku": "s", "store": "a"}]))
    assert load_targets(str(path))[0]["sku"] == "s"


@pytest.mark.asyncio
async def test_fetch_target_success_with_alerts():
    redis = AsyncMock()
    redis.redis = AsyncMock()
    browser_pool = AsyncMock()
    browser = AsyncMock()
    context = AsyncMock()
    page = AsyncMock()
    browser_pool.acquire.return_value = browser
    browser.new_context.return_value = context
    context.new_page.return_value = page
    page.content.return_value = "<html>EGP 100</html>"

    proxy_pool = ProxyPool(["http://proxy:1"])

    with patch(
        "services.scraper.scraper.extract_product_title",
        new=AsyncMock(return_value="Title"),
    ), patch(
        "services.scraper.scraper.extract_price_from_page",
        new=AsyncMock(return_value=100.0),
    ), patch(
        "services.scraper.scraper.check_in_stock_from_page",
        new=AsyncMock(return_value=True),
    ), patch(
        "services.scraper.scraper.check_alerts_for_sku",
        new=AsyncMock(
            return_value=[
                {"phone": "+201", "target_price": 120, "alert_id": 1, "user_id": 1}
            ]
        ),
    ), patch.object(scraper_mod, "MAX_RETRIES", 1):
        ok = await fetch_target(
            {"url": "https://amazon.eg/dp/X", "sku": "X", "store": "amazon_eg"},
            redis,
            browser_pool,
            proxy_pool,
        )

    assert ok is True
    assert redis.xadd.await_count >= 2
    browser_pool.release.assert_awaited()


@pytest.mark.asyncio
async def test_fetch_target_playwright_failure_pushes_queue():
    redis = AsyncMock()
    redis.redis = AsyncMock()
    browser_pool = AsyncMock()
    browser = AsyncMock()
    browser_pool.acquire.return_value = browser
    browser.new_context.side_effect = PlaywrightError("nav fail")

    with patch.object(scraper_mod, "MAX_RETRIES", 1), patch(
        "services.scraper.scraper.asyncio.sleep", new=AsyncMock()
    ):
        ok = await fetch_target(
            {"url": "https://x", "sku": "S", "store": "store"},
            redis,
            browser_pool,
            None,
        )

    assert ok is False
    redis.redis.rpush.assert_awaited()


@pytest.mark.asyncio
async def test_fetch_target_generic_exception_retries_then_fails():
    redis = AsyncMock()
    redis.redis = AsyncMock()
    browser_pool = AsyncMock()
    browser = AsyncMock()
    browser_pool.acquire.return_value = browser
    browser.new_context.side_effect = RuntimeError("boom")

    with patch.object(scraper_mod, "MAX_RETRIES", 1), patch(
        "services.scraper.scraper.asyncio.sleep", new=AsyncMock()
    ):
        ok = await fetch_target(
            {"url": "https://x", "sku": "S", "store": "store"},
            redis,
            browser_pool,
        )

    assert ok is False


@pytest.mark.asyncio
async def test_run_targets_mocked():
    with patch(
        "services.scraper.scraper.RedisStreamClient.create",
        new=AsyncMock(return_value=AsyncMock()),
    ), patch(
        "services.scraper.scraper.async_playwright"
    ) as ap, patch(
        "services.scraper.scraper.BrowserPool"
    ) as BP, patch(
        "services.scraper.scraper.fetch_target",
        new=AsyncMock(return_value=True),
    ):
        pw_cm = AsyncMock()
        pw = MagicMock()
        pw_cm.__aenter__.return_value = pw
        pw_cm.__aexit__.return_value = False
        ap.return_value = pw_cm

        pool = AsyncMock()
        BP.return_value = pool

        results = await scraper_mod.run_targets(
            [{"url": "u", "sku": "s", "store": "a"}]
        )
        assert results == [True]
        pool.start.assert_awaited()
        pool.close.assert_awaited()


@pytest.mark.asyncio
async def test_run_from_file(tmp_path):
    path = tmp_path / "t.json"
    path.write_text(json.dumps([{"url": "u", "sku": "s", "store": "a"}]))
    with patch(
        "services.scraper.scraper.run_targets",
        new=AsyncMock(return_value=[True]),
    ) as run:
        assert await scraper_mod.run_from_file(str(path)) == [True]
        run.assert_awaited()
