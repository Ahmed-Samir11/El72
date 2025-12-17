import pytest
from services.scraper.scraper import extract_price, check_in_stock, ProxyPool


@pytest.mark.asyncio
async def test_extract_price_valid():
    html = "<div>Price: EGP 123.45</div>"
    price = await extract_price(html)
    assert price == 123.45


@pytest.mark.asyncio
async def test_extract_price_no_match():
    html = "<div>No price here</div>"
    price = await extract_price(html)
    assert price == 0.0


@pytest.mark.asyncio
async def test_check_in_stock_available():
    html = "<div>In stock now</div>"
    result = await check_in_stock(html)
    assert result == True


@pytest.mark.asyncio
async def test_check_in_stock_out():
    html = "<div>Out of stock</div>"
    result = await check_in_stock(html)
    assert result == False


def test_proxy_pool_get():
    proxies = ["proxy1", "proxy2"]
    pool = ProxyPool(proxies)
    proxy = pool.get()
    assert proxy in proxies