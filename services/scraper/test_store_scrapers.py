"""Expanded tests for store scrapers."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from playwright.async_api import Error as PlaywrightError

from services.scraper.store_scrapers import (
    AmazonEgyptScraper,
    BaseScraper,
    ElBadrGroupScraper,
    JumiaScraper,
    NoonScraper,
    ScrapeResult,
    ScraperFactory,
)


@pytest.fixture
def page():
    return AsyncMock()


@pytest.mark.asyncio
async def test_amazon_title_image_search_and_price_miss(page):
    scraper = AmazonEgyptScraper()

    page.query_selector.return_value = None
    assert await scraper.extract_price(page) is None
    assert await scraper.extract_title(page) is None
    assert await scraper.extract_image_url(page) is None

    title_el = AsyncMock()
    title_el.inner_text.return_value = " Amazon Title "
    page.query_selector.return_value = title_el
    assert await scraper.extract_title(page) == "Amazon Title"

    img = AsyncMock()
    img.get_attribute.return_value = "https://img"
    page.query_selector.return_value = img
    assert await scraper.extract_image_url(page) == "https://img"

    link = AsyncMock()
    link.get_attribute.return_value = "/dp/B0ABC?x=1"
    page.query_selector.return_value = link
    url = await scraper.search_product(page, "gaming laptop")
    assert url == "https://www.amazon.eg/dp/B0ABC"

    page.goto.side_effect = Exception("fail")
    assert await scraper.search_product(page, "x") is None
    assert scraper.get_default_currency() == "EGP"


@pytest.mark.asyncio
async def test_noon_and_jumia_extractors(page):
    noon = NoonScraper()
    jumia = JumiaScraper()

    price_el = AsyncMock()
    price_el.inner_text.return_value = "EGP 999"
    page.query_selector.return_value = price_el
    assert await noon.extract_price(page) == 999.0
    assert await jumia.extract_price(page) == 999.0

    page.query_selector.return_value = None
    assert await noon.extract_price(page) is None

    # Noon stock: out of stock text
    page.query_selector.side_effect = [AsyncMock(), None]
    assert await noon.extract_stock_status(page) is False
    page.query_selector.side_effect = [None, AsyncMock()]
    assert await noon.extract_stock_status(page) is True
    page.query_selector.side_effect = Exception("e")
    assert await noon.extract_stock_status(page) is True

    page.query_selector.side_effect = [AsyncMock(), None]
    assert await jumia.extract_stock_status(page) is False
    page.query_selector.side_effect = [None, AsyncMock()]
    assert await jumia.extract_stock_status(page) is True

    title_el = AsyncMock()
    title_el.inner_text.return_value = "Noon Title"
    page.query_selector.side_effect = None
    page.query_selector.return_value = title_el
    assert await noon.extract_title(page) == "Noon Title"
    assert await jumia.extract_title(page) == "Noon Title"

    link = AsyncMock()
    link.get_attribute.return_value = "/egypt-en/p/N1"
    page.query_selector.return_value = link
    assert "noon.com" in await noon.search_product(page, "gpu")
    link.get_attribute.return_value = "/p/J1"
    assert "jumia.com.eg" in await jumia.search_product(page, "gpu")

    page.goto.side_effect = Exception("search fail")
    assert await noon.search_product(page, "x") is None
    assert await jumia.search_product(page, "x") is None


@pytest.mark.asyncio
async def test_elbadr_extractors_and_search(page):
    scraper = ElBadrGroupScraper()

    meta = AsyncMock()
    meta.get_attribute.return_value = "1234.5"
    page.query_selector.return_value = meta
    assert await scraper.extract_price(page) == 1234.5

    page.query_selector.return_value = None
    assert await scraper.extract_price(page) is None

    oos = AsyncMock()
    page.query_selector.return_value = oos
    assert await scraper.extract_stock_status(page) is False

    btn = AsyncMock()
    btn.get_attribute.return_value = "disabled"
    btn.inner_text.return_value = "Add"
    page.query_selector.side_effect = [None, btn]
    assert await scraper.extract_stock_status(page) is False

    btn2 = AsyncMock()
    btn2.get_attribute.return_value = None
    btn2.inner_text.return_value = "Sold Out"
    page.query_selector.side_effect = [None, btn2]
    assert await scraper.extract_stock_status(page) is False

    page.query_selector.side_effect = [None, None]
    assert await scraper.extract_stock_status(page) is True

    title = AsyncMock()
    title.inner_text.return_value = "GPU"
    page.query_selector.side_effect = None
    page.query_selector.return_value = title
    assert await scraper.extract_title(page) == "GPU"

    link1 = AsyncMock()
    link1.inner_text.return_value = "Other Card"
    link1.get_attribute.return_value = "/other"
    link2 = AsyncMock()
    link2.inner_text.return_value = "ASUS PRIME RTX 5070"
    link2.get_attribute.return_value = "/asus-prime-rtx-5070"
    page.query_selector_all.return_value = [link1, link2]
    page.goto = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    url = await scraper.search_product(page, "ASUS PRIME RTX 5070")
    assert "asus-prime-rtx-5070" in url


@pytest.mark.asyncio
async def test_base_scrape_success_search_and_failures(page):
    scraper = AmazonEgyptScraper()
    scraper.rate_limit_delay = 0

    page.goto = AsyncMock()
    with pytest.MonkeyPatch.context() as mp:
        pass

    scraper.extract_price = AsyncMock(return_value=10.0)
    scraper.extract_stock_status = AsyncMock(return_value=True)
    scraper.extract_title = AsyncMock(return_value="T")
    scraper.extract_image_url = AsyncMock(return_value="I")

    result = await scraper.scrape(page, "https://amazon.eg/dp/X", "cid")
    assert isinstance(result, ScrapeResult)
    assert result.price == 10.0

    scraper.search_product = AsyncMock(return_value="https://amazon.eg/dp/Y")
    result2 = await scraper.scrape(page, "gaming laptop", "cid")
    assert result2.url.endswith("/dp/Y")

    scraper.search_product = AsyncMock(return_value=None)
    assert await scraper.scrape(page, "missing product", "cid") is None

    scraper.extract_price = AsyncMock(return_value=None)
    assert await scraper.scrape(page, "https://amazon.eg/dp/X", "cid") is None

    page.goto.side_effect = PlaywrightError("timeout")
    scraper.extract_price = AsyncMock(return_value=10.0)
    assert await scraper.scrape(page, "https://amazon.eg/dp/X", "cid") is None

    page.goto.side_effect = RuntimeError("boom")
    assert await scraper.scrape(page, "https://amazon.eg/dp/X", "cid") is None


def test_scraper_factory_register_invalid():
    class NotAScraper:
        pass

    with pytest.raises(ValueError):
        ScraperFactory.register_scraper("bad", NotAScraper)

    assert ScraperFactory.get_scraper("nope") is None


def test_scrape_result_defaults():
    r = ScrapeResult(
        store="s",
        canonical_product_id="c",
        price=1.0,
        currency="EGP",
        in_stock=True,
        url="u",
    )
    d = r.to_dict()
    assert d["metadata"] == {}
    assert d["title"] is None
