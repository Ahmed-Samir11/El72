"""Tests for run_scrapers_for_item helpers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.scraper.run_scrapers_for_item import RunResult, main, run_for_store
from services.scraper.store_scrapers import ScrapeResult


@pytest.mark.asyncio
async def test_run_for_store_unsupported():
    pw = MagicMock()
    with patch(
        "services.scraper.run_scrapers_for_item.ScraperFactory.get_scraper",
        return_value=None,
    ):
        result = await run_for_store(pw, "nope", "q", "cid", None)
    assert result.ok is False
    assert "Unsupported" in result.error


@pytest.mark.asyncio
async def test_run_for_store_success_and_failures(tmp_path):
    pw = MagicMock()
    browser = AsyncMock()
    context = AsyncMock()
    page = AsyncMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    browser.new_context = AsyncMock(return_value=context)
    context.new_page = AsyncMock(return_value=page)

    scrape_result = ScrapeResult(
        store="amazon_eg",
        canonical_product_id="cid",
        price=12,
        currency="EGP",
        in_stock=True,
        url="https://x",
        title="T",
    )
    scraper = AsyncMock()
    scraper.scrape = AsyncMock(return_value=scrape_result)

    with patch(
        "services.scraper.run_scrapers_for_item.ScraperFactory.get_scraper",
        return_value=scraper,
    ):
        ok = await run_for_store(pw, "amazon_eg", "https://x", "cid", None)
    assert ok.ok is True
    assert ok.payload["price"] == 12

    scraper.scrape = AsyncMock(return_value=None)
    with patch(
        "services.scraper.run_scrapers_for_item.ScraperFactory.get_scraper",
        return_value=scraper,
    ):
        fail = await run_for_store(pw, "amazon_eg", "q", "cid", str(tmp_path))
    assert fail.ok is False

    scraper.scrape = AsyncMock(side_effect=RuntimeError("boom"))
    with patch(
        "services.scraper.run_scrapers_for_item.ScraperFactory.get_scraper",
        return_value=scraper,
    ):
        err = await run_for_store(pw, "amazon_eg", "q", "cid", str(tmp_path))
    assert err.ok is False
    assert "boom" in err.error


@pytest.mark.asyncio
async def test_main_search_mode_and_validation():
    with patch(
        "services.scraper.run_scrapers_for_item.asyncio.gather",
        new=AsyncMock(
            return_value=[
                RunResult("amazon_eg", True, None, {"price": 1, "currency": "EGP", "in_stock": True, "title": "t", "url": "u", "timestamp": "now"}, None)
            ]
        ),
    ), patch(
        "services.scraper.run_scrapers_for_item.async_playwright"
    ) as ap, patch(
        "sys.argv",
        ["prog", "--product", "GPU Card", "--store", "amazon_eg"],
    ):
        pw_cm = AsyncMock()
        pw_cm.__aenter__.return_value = MagicMock()
        pw_cm.__aexit__.return_value = False
        ap.return_value = pw_cm
        await main()

    with patch("sys.argv", ["prog", "--product", "GPU", "--store", "amazon_eg=https://x"]):
        with pytest.raises(SystemExit):
            await main()

    with patch("sys.argv", ["prog"]):
        with pytest.raises(SystemExit):
            await main()


@pytest.mark.asyncio
async def test_main_direct_url_mode():
    with patch(
        "services.scraper.run_scrapers_for_item.asyncio.gather",
        new=AsyncMock(
            return_value=[RunResult("amazon_eg", False, "fail", None, None)]
        ),
    ), patch(
        "services.scraper.run_scrapers_for_item.async_playwright"
    ) as ap, patch(
        "sys.argv",
        ["prog", "--canonical-id", "cid", "--store", "amazon_eg=https://amazon.eg/dp/X"],
    ):
        pw_cm = AsyncMock()
        pw_cm.__aenter__.return_value = MagicMock()
        pw_cm.__aexit__.return_value = False
        ap.return_value = pw_cm
        with pytest.raises(SystemExit):
            await main()
