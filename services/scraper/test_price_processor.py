"""Tests for price processor."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from decimal import Decimal

from services.scraper.price_processor import PriceProcessor
from services.scraper.store_scrapers import ScrapeResult


@pytest.fixture
def mock_db_pool():
    """Create mock database pool."""
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    return pool, conn


def test_convert_to_usd():
    """Test currency conversion."""
    assert PriceProcessor.convert_to_usd(100, "USD") == 100.0
    assert PriceProcessor.convert_to_usd(1000, "EGP") == 32.0  # 1000 * 0.032
    assert PriceProcessor.convert_to_usd(100, "AED") == 27.0


@pytest.mark.asyncio
async def test_detect_price_change_first_time(mock_db_pool):
    """Test price change detection for first scrape."""
    pool, conn = mock_db_pool
    conn.fetchrow.return_value = None  # No existing price
    
    processor = PriceProcessor(pool)
    changed, old_price = await processor._detect_price_change(conn, 1, "amazon_eg", 100.0)
    
    assert changed is True
    assert old_price is None


@pytest.mark.asyncio
async def test_detect_price_change_no_change(mock_db_pool):
    """Test price unchanged."""
    pool, conn = mock_db_pool
    conn.fetchrow.return_value = {"price_usd": Decimal("100.0")}
    
    processor = PriceProcessor(pool)
    changed, old_price = await processor._detect_price_change(conn, 1, "amazon_eg", 100.0)
    
    assert changed is False
    assert old_price is None


@pytest.mark.asyncio
async def test_detect_price_change_changed(mock_db_pool):
    """Test price change detected."""
    pool, conn = mock_db_pool
    conn.fetchrow.return_value = {"price_usd": Decimal("100.0")}
    
    processor = PriceProcessor(pool)
    changed, old_price = await processor._detect_price_change(conn, 1, "amazon_eg", 90.0)
    
    assert changed is True
    assert old_price == 100.0


@pytest.mark.asyncio
async def test_update_current_price(mock_db_pool):
    """Test current price upsert."""
    pool, conn = mock_db_pool
    processor = PriceProcessor(pool)
    
    await processor._update_current_price(
        conn, 1, "amazon_eg", 100.0, 3125.0, "EGP", True
    )
    
    # Verify execute was called with correct query
    conn.execute.assert_called_once()
    call_args = conn.execute.call_args
    assert "INSERT INTO current_prices" in call_args[0][0]
    assert "ON CONFLICT" in call_args[0][0]


@pytest.mark.asyncio
async def test_process_scrape_result(mock_db_pool):
    """Test full scrape result processing."""
    pool, conn = mock_db_pool
    processor = PriceProcessor(pool)
    
    # Mock responses
    conn.fetchrow.side_effect = [
        {"price_usd": Decimal("100.0")},  # detect_price_change
        {"in_stock": True},                # detect_stock_change
        None                                # update_lowest_price
    ]
    
    result = ScrapeResult(
        store="amazon_eg",
        canonical_product_id="test",
        price=3125.0,
        currency="EGP",
        in_stock=True,
        url="https://test.com"
    )
    
    processing_result = await processor.process_scrape_result(result, 1)
    
    assert "price_changed" in processing_result
    assert "new_price_usd" in processing_result
    assert processing_result["new_price_usd"] == 100.0  # 3125 * 0.032


@pytest.mark.asyncio
async def test_get_lowest_price_for_item(mock_db_pool):
    """Test retrieving lowest price."""
    pool, conn = mock_db_pool
    conn.fetchrow.return_value = {
        "store_id": "amazon_eg",
        "price_usd": Decimal("100.0"),
        "price_local": Decimal("3125.0"),
        "currency": "EGP",
        "url": "https://test.com",
        "last_updated": "2025-12-19 14:30:00"
    }
    
    processor = PriceProcessor(pool)
    lowest = await processor.get_lowest_price_for_item(1)
    
    assert lowest["store_id"] == "amazon_eg"
    assert lowest["price_usd"] == 100.0
    assert lowest["currency"] == "EGP"
