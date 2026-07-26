"""Tests for BrowserPool with mocked Playwright."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.scraper.browser_pool import BrowserPool


@pytest.mark.asyncio
async def test_browser_pool_lifecycle():
    browser1 = AsyncMock()
    browser2 = AsyncMock()
    launcher = AsyncMock()
    launcher.launch.side_effect = [browser1, browser2]
    playwright = MagicMock()
    playwright.chromium = launcher

    pool = BrowserPool(playwright, max_browsers=2)
    with pytest.raises(RuntimeError):
        await pool.acquire()

    await pool.start()
    b = await pool.acquire()
    assert b in (browser1, browser2)
    await pool.release(b)
    await pool.close()
    browser1.close.assert_awaited()
    browser2.close.assert_awaited()
    assert pool._queue is None


@pytest.mark.asyncio
async def test_release_before_start_noop():
    pool = BrowserPool(MagicMock(), max_browsers=1)
    await pool.release(AsyncMock())
