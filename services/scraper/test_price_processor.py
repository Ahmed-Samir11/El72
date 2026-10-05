"""Expanded tests for price processor."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.scraper.price_processor import PriceProcessor
from services.scraper.store_scrapers import ScrapeResult


@pytest.fixture
def mock_db_pool():
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    pool.acquire.return_value.__aexit__.return_value = False
    return pool, conn


@pytest.fixture
def mock_timescale_pool():
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    pool.acquire.return_value.__aexit__.return_value = False
    return pool, conn


def test_convert_unknown_currency_defaults_rate():
    assert PriceProcessor.convert_to_usd(10, "XYZ") == 10.0
    assert PriceProcessor.convert_to_usd(100, "sar") == 27.0


@pytest.mark.asyncio
async def test_detect_stock_change_paths(mock_db_pool, mock_timescale_pool):
    pool, conn = mock_db_pool
    processor = PriceProcessor(pool, mock_timescale_pool[0])

    conn.fetchrow.return_value = None
    assert await processor._detect_stock_change(conn, 1, "a", True) is False

    conn.fetchrow.return_value = {"in_stock": True}
    assert await processor._detect_stock_change(conn, 1, "a", False) is True
    assert await processor._detect_stock_change(conn, 1, "a", True) is False


@pytest.mark.asyncio
async def test_insert_price_history_egp_and_other(mock_db_pool, mock_timescale_pool):
    pool, conn = mock_db_pool
    processor = PriceProcessor(pool, mock_timescale_pool[0])

    await processor._insert_price_history(
        conn, 1, "amazon_eg", "SKU", 3.2, 100.0, "EGP", True
    )
    args = conn.execute.await_args[0]
    assert args[3] == 3.2
    assert args[4] == 100.0
    assert args[5] == "EGP"
    assert args[6] is True

    conn.execute.reset_mock()
    await processor._insert_price_history(
        conn, 1, "amazon_eg", "SKU", 10.0, 10.0, "USD", True
    )
    args = conn.execute.await_args[0]
    assert args[3] == 10.0
    assert args[4] == 10.0
    assert args[5] == "USD"


@pytest.mark.asyncio
async def test_insert_price_history_passes_image_url(mock_db_pool, mock_timescale_pool):
    pool, conn = mock_db_pool
    processor = PriceProcessor(pool, mock_timescale_pool[0])

    # conn.execute receives normalized USD/local prices, currency, stock, and
    # the optional image URL after the SQL statement.
    await processor._insert_price_history(
        conn, 1, "amazon_eg", "SKU", 3.2, 100.0, "EGP", True
    )
    assert conn.execute.await_args[0][7] is None

    # Explicit: a populated image_url is passed through to the SQL execute call.
    conn.execute.reset_mock()
    await processor._insert_price_history(
        conn,
        1,
        "amazon_eg",
        "SKU",
        3.2,
        100.0,
        "EGP",
        True,
        image_url="https://img.com/a.jpg",
    )
    assert conn.execute.await_args[0][7] == "https://img.com/a.jpg"


@pytest.mark.asyncio
async def test_update_lowest_price_none_and_match(mock_db_pool, mock_timescale_pool):
    pool, conn = mock_db_pool
    processor = PriceProcessor(pool, mock_timescale_pool[0])

    conn.fetchrow.return_value = None
    assert await processor._update_lowest_price(conn, 1, "https://x") is False
    conn.execute.assert_awaited()

    conn.fetchrow.return_value = {
        "store_id": "amazon_eg",
        "price_usd": Decimal("1"),
        "price_local": Decimal("30"),
        "currency": "EGP",
        "url": "https://x",
    }
    assert await processor._update_lowest_price(conn, 1, "https://x") is True
    assert await processor._update_lowest_price(conn, 1, "https://other") is False


@pytest.mark.asyncio
async def test_get_lowest_price_none(mock_db_pool, mock_timescale_pool):
    pool, conn = mock_db_pool
    conn.fetchrow.return_value = None
    processor = PriceProcessor(pool, mock_timescale_pool[0])
    assert await processor.get_lowest_price_for_item(1) is None


@pytest.mark.asyncio
async def test_get_all_current_prices(mock_db_pool, mock_timescale_pool):
    pool, conn = mock_db_pool
    conn.fetch.return_value = [
        {
            "store_id": "amazon_eg",
            "price_usd": Decimal("1"),
            "price_local": Decimal("30"),
            "currency": "EGP",
            "in_stock": True,
            "last_updated": "t",
            "store_url": "https://x",
        }
    ]
    processor = PriceProcessor(pool, mock_timescale_pool[0])
    prices = await processor.get_all_current_prices(1)
    assert len(prices) == 1
    assert prices[0]["url"] == "https://x"


@pytest.mark.asyncio
async def test_process_scrape_result_inserts_history_on_change(
    mock_db_pool, mock_timescale_pool
):
    pool, conn = mock_db_pool
    timescale_pool, history_conn = mock_timescale_pool
    processor = PriceProcessor(pool, timescale_pool)

    conn.fetchrow.side_effect = [
        {"price_usd": Decimal("5.0")},  # price change detect
        {"in_stock": False},  # stock change
        {
            "store_id": "amazon_eg",
            "price_usd": Decimal("3.2"),
            "price_local": Decimal("100"),
            "currency": "EGP",
            "url": "https://test.com",
        },
    ]

    result = ScrapeResult(
        store="amazon_eg",
        canonical_product_id="test",
        price=100.0,
        currency="EGP",
        in_stock=True,
        url="https://test.com",
    )
    out = await processor.process_scrape_result(result, 1)
    assert out["price_changed"] is True
    assert out["stock_changed"] is True
    assert out["is_lowest"] is True
    assert conn.execute.await_count == 2
    assert history_conn.execute.await_count == 1
    assert "INSERT INTO price_history" in history_conn.execute.await_args.args[0]
    assert all(
        "INSERT INTO price_history" not in call.args[0]
        for call in conn.execute.await_args_list
    )
