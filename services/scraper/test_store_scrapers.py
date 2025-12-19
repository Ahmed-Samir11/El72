"""Tests for store scrapers."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from services.scraper.store_scrapers import (
    AmazonEgyptScraper,
    NoonScraper,
    JumiaScraper,
    ScraperFactory,
    ScrapeResult,
    ElBadrGroupScraper,
)


@pytest.mark.asyncio
async def test_amazon_scraper_extract_price():
    """Test Amazon price extraction."""
    scraper = AmazonEgyptScraper()
    
    # Mock page
    page = AsyncMock()
    element = AsyncMock()
    element.inner_text.return_value = "EGP 1,250.99"
    page.query_selector.return_value = element
    
    price = await scraper.extract_price(page)
    assert price == 1250.99


@pytest.mark.asyncio
async def test_amazon_scraper_stock_status():
    """Test Amazon stock status detection."""
    scraper = AmazonEgyptScraper()
    
    # Mock in-stock
    page = AsyncMock()
    page.query_selector.return_value = None
    assert await scraper.extract_stock_status(page) is True
    
    # Mock out-of-stock
    element = AsyncMock()
    element.inner_text.return_value = "Currently unavailable"
    page.query_selector.return_value = element
    assert await scraper.extract_stock_status(page) is False


def test_scraper_factory_get_scraper():
    """Test scraper factory."""
    # Amazon
    scraper = ScraperFactory.get_scraper("amazon_eg")
    assert isinstance(scraper, AmazonEgyptScraper)
    
    # Noon
    scraper = ScraperFactory.get_scraper("noon")
    assert isinstance(scraper, NoonScraper)
    
    # Unknown store
    # El Badr Group
    scraper = ScraperFactory.get_scraper("elbadrgroup")
    assert isinstance(scraper, ElBadrGroupScraper)

    # Unknown store
    scraper = ScraperFactory.get_scraper("unknown_store")
    assert scraper is None


def test_scraper_factory_list_stores():
    """Test listing supported stores."""
    stores = ScraperFactory.list_supported_stores()
    assert "amazon_eg" in stores
    assert "noon" in stores
    assert "jumia" in stores
    assert "elbadrgroup" in stores


def test_scrape_result_to_dict():
    """Test ScrapeResult serialization."""
    result = ScrapeResult(
        store="amazon_eg",
        canonical_product_id="test-product",
        price=1250.99,
        currency="EGP",
        in_stock=True,
        url="https://example.com/product",
        title="Test Product"
    )
    
    data = result.to_dict()
    assert data["store"] == "amazon_eg"
    assert data["price"] == 1250.99
    assert data["in_stock"] is True
    assert "timestamp" in data


def test_parse_price_text():
    """Test generic price parsing."""
    scraper = AmazonEgyptScraper()
    
    assert scraper.parse_price_text("EGP 1,250.99") == 1250.99
    assert scraper.parse_price_text("1,250.99 EGP") == 1250.99
    assert scraper.parse_price_text("$99.99") == 99.99
    assert scraper.parse_price_text("99") == 99.0
    assert scraper.parse_price_text("invalid") is None
    assert scraper.parse_price_text("") is None


@pytest.mark.asyncio
async def test_rate_limiting():
    """Test rate limiting enforcement."""
    import time
    scraper = AmazonEgyptScraper()
    scraper.rate_limit_delay = 0.1
    
    start = time.time()
    await scraper._enforce_rate_limit()
    await scraper._enforce_rate_limit()
    elapsed = time.time() - start
    
    # Should have delayed at least once
    assert elapsed >= 0.1
