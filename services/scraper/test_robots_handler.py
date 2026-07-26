"""Tests for robots.txt handler with mocked parser dependency."""

import sys
from datetime import datetime, timedelta
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# Provide a stub module before importing robots_handler
class _FakeParser:
    def __init__(self):
        self._allowed = True
        self.content = ""

    def parse(self, content):
        self.content = content or ""

    def is_allowed(self, ua, url):
        return self._allowed


_stub = ModuleType("robotexclusionrulesparser")
_stub.RobotExclusionRulesParser = _FakeParser
sys.modules["robotexclusionrulesparser"] = _stub

from services.scraper.robots_handler import (  # noqa: E402
    RobotsTxtHandler,
    RobotsTxtMode,
    check_robots_allowed,
    get_crawl_delay,
    get_robots_handler,
)


@pytest.fixture
def handler():
    return RobotsTxtHandler(mode=RobotsTxtMode.SOFT, default_delay=1.5)


@pytest.mark.asyncio
async def test_fetch_robots_success_404_and_error(handler):
    mock_resp = MagicMock(status_code=200, text="User-agent: *\nDisallow: /admin\nCrawl-delay: 2\nSitemap: https://x/s.xml")
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False

    with patch("services.scraper.robots_handler.httpx.AsyncClient", return_value=mock_client):
        text = await handler._fetch_robots_txt("https://example.com")
        assert "Disallow" in text

    mock_resp.status_code = 404
    with patch("services.scraper.robots_handler.httpx.AsyncClient", return_value=mock_client):
        assert await handler._fetch_robots_txt("https://example.com") is None

    mock_resp.status_code = 500
    with patch("services.scraper.robots_handler.httpx.AsyncClient", return_value=mock_client):
        assert await handler._fetch_robots_txt("https://example.com") is None

    mock_client.get.side_effect = Exception("net")
    with patch("services.scraper.robots_handler.httpx.AsyncClient", return_value=mock_client):
        assert await handler._fetch_robots_txt("https://example.com") is None


def test_parse_robots_txt(handler):
    content = "User-agent: *\nCrawl-delay: 3.5\nSitemap: https://ex/sitemap.xml\n"
    cache = handler._parse_robots_txt(content)
    assert cache.crawl_delay == 3.5
    assert cache.sitemap_urls == ["https://ex/sitemap.xml"]


@pytest.mark.asyncio
async def test_is_allowed_modes(handler):
    cache = handler._parse_robots_txt("User-agent: *\nDisallow: /")
    cache.parser._allowed = False

    with patch.object(handler, "_get_cache", new=AsyncMock(return_value=cache)):
        handler.mode = RobotsTxtMode.STRICT
        assert await handler.is_allowed("https://ex/p") is False

        handler.mode = RobotsTxtMode.SOFT
        assert await handler.is_allowed("https://ex/p") is True

        handler.mode = RobotsTxtMode.LOG_ONLY
        assert await handler.is_allowed("https://ex/p") is True


@pytest.mark.asyncio
async def test_cache_reuse_and_helpers(handler):
    content = "User-agent: *\nCrawl-delay: 2\nSitemap: https://ex/s.xml\n"
    mock_resp = MagicMock(status_code=200, text=content)
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False

    with patch("services.scraper.robots_handler.httpx.AsyncClient", return_value=mock_client):
        delay1 = await handler.get_crawl_delay("https://ex.com/a")
        delay2 = await handler.get_crawl_delay("https://ex.com/b")
        sitemaps = await handler.get_sitemaps("https://ex.com/c")

    assert delay1 == 2.0
    assert delay2 == 2.0
    assert mock_client.get.await_count == 1
    assert sitemaps == ["https://ex/s.xml"]

    handler.clear_cache()
    assert handler._cache == {}


@pytest.mark.asyncio
async def test_get_cache_when_no_robots(handler):
    with patch.object(handler, "_fetch_robots_txt", new=AsyncMock(return_value=None)):
        cache = await handler._get_cache("https://none.example/x")
    assert cache.crawl_delay == handler.default_delay


@pytest.mark.asyncio
async def test_module_helpers(monkeypatch):
    import services.scraper.robots_handler as rh

    rh._handler = None
    h = get_robots_handler()
    assert isinstance(h, RobotsTxtHandler)

    with patch.object(h, "is_allowed", new=AsyncMock(return_value=True)), patch.object(
        h, "get_crawl_delay", new=AsyncMock(return_value=1.0)
    ):
        assert await check_robots_allowed("https://x") is True
        assert await get_crawl_delay("https://x") == 1.0
