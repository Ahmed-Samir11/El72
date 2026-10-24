"""Unit tests for the chatbot search service."""

import json
from unittest.mock import MagicMock

import pytest

from services.chatbot.search_service import (
    STORES,
    ChatbotSearchService,
    SearchResultItem,
    SearchResultsSchema,
    parse_intent,
)


@pytest.fixture
def search_service():
    """Create a search service instance."""
    return ChatbotSearchService()


def test_parse_intent_with_price_filter():
    """Test intent parsing extracts price filter correctly."""
    result = parse_intent("gaming laptop under 50000 EGP")
    assert result["query"] == "gaming laptop"
    assert result["max_price"] == 50000.0


def test_parse_intent_without_price():
    """Test intent parsing without price filter."""
    result = parse_intent("iPhone 15 Pro Max")
    assert result["query"] == "iPhone 15 Pro Max"
    assert result["max_price"] is None


def test_parse_intent_below_price():
    """Test intent parsing with 'below' keyword."""
    result = parse_intent("Samsung TV below 30000")
    assert result["query"] == "Samsung TV"
    assert result["max_price"] == 30000.0


def test_parse_intent_max_price():
    """Test intent parsing with 'max' keyword."""
    result = parse_intent("laptop max 40000")
    assert result["query"] == "laptop"
    assert result["max_price"] == 40000.0


def test_parse_intent_standalone_number():
    """Test intent parsing with standalone number at end."""
    result = parse_intent("laptop 50000 EGP")
    assert result["query"] == "laptop"
    assert result["max_price"] == 50000.0


def test_parse_intent_empty_query():
    """Test intent parsing with only a price filter."""
    result = parse_intent("under 50000 EGP")
    assert result["query"] == ""
    assert result["max_price"] == 50000.0


def test_parse_arabic_intent():
    """Test Arabic intent includes translated and display queries."""
    result = parse_intent("عايز شاشات 2k بسعر أقل من 12 ألف")
    assert result["query"] == "monitors 2k"
    assert result["display_query"] == "شاشات 2k"
    assert result["max_price"] == 12000.0
    assert result["language"] == "ar"


@pytest.mark.asyncio
async def test_search_service_init(search_service):
    """Test that the search service initializes correctly."""
    assert search_service.stores == STORES
    assert len(search_service.stores) > 0
    await search_service.close()


@pytest.mark.asyncio
async def test_search_with_mocked_extract(search_service):
    """Test full search flow with mocked extraction."""

    # Mock _extract_search_results to return results
    async def mock_extract(query, store, **_):
        if store.store_id == "amazon_eg":
            return MagicMock(
                products=[
                    MagicMock(
                        title="Gaming Laptop",
                        url="/product/123",
                        price=55000.0,
                        currency="EGP",
                        image_url="https://example.com/image.jpg",
                        in_stock=True,
                    )
                ]
            )
        return MagicMock(products=[])

    search_service._extract_search_results = mock_extract

    results = await search_service.search("gaming laptop", max_price=60000)

    assert len(results) == 1
    assert results[0]["title"] == "Gaming Laptop"
    assert results[0]["price"] == 55000.0
    assert results[0]["store_id"] == "amazon_eg"

    await search_service.close()


@pytest.mark.asyncio
async def test_search_price_filter(search_service):
    """Test that price filter is applied in search."""

    async def mock_extract(query, store, **_):
        if store.store_id == "amazon_eg":
            return MagicMock(
                products=[
                    MagicMock(
                        title="Laptop A",
                        url="/product/a",
                        price=50000.0,
                        currency="EGP",
                        image_url=None,
                        in_stock=True,
                    ),
                    MagicMock(
                        title="Laptop B",
                        url="/product/b",
                        price=80000.0,
                        currency="EGP",
                        image_url=None,
                        in_stock=True,
                    ),
                ]
            )
        return MagicMock(products=[])

    search_service._extract_search_results = mock_extract

    results = await search_service.search("laptop", max_price=60000)

    # Only Laptop A (50000) should pass the filter, not Laptop B (80000)
    assert len(results) == 1
    assert results[0]["title"] == "Laptop A"
    assert results[0]["price"] == 50000.0

    await search_service.close()


@pytest.mark.asyncio
async def test_search_no_results(search_service):
    """Test search when no results are found."""

    async def mock_extract(query, store, **_):
        return MagicMock(products=[])

    search_service._extract_search_results = mock_extract

    results = await search_service.search("nonexistent product xyz123")

    assert results == []

    await search_service.close()


@pytest.mark.asyncio
async def test_search_with_intent(search_service):
    """Test search_with_intent parses and searches."""

    async def mock_extract(query, store, **_):
        if store.store_id == "amazon_eg":
            return MagicMock(
                products=[
                    MagicMock(
                        title="Gaming Laptop",
                        url="/product/123",
                        price=45000.0,
                        currency="EGP",
                        image_url=None,
                        in_stock=True,
                    )
                ]
            )
        return MagicMock(products=[])

    search_service._extract_search_results = mock_extract

    result = await search_service.search_with_intent("gaming laptop under 50000 EGP")

    assert result["query"] == "gaming laptop"
    assert result["max_price"] == 50000.0
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Gaming Laptop"

    await search_service.close()


def test_search_result_item_validation():
    """Test SearchResultItem validation."""
    item = SearchResultItem(
        title="Test Product",
        url="/product/123",
        price=100.0,
        currency="EGP",
        image_url="https://example.com/image.jpg",
        in_stock=True,
    )
    assert item.title == "Test Product"
    assert item.price == 100.0


def test_search_results_schema_validation():
    """Test SearchResultsSchema validation."""
    schema = SearchResultsSchema(
        products=[
            SearchResultItem(
                title="Test Product",
                url="/product/123",
                price=100.0,
                currency="EGP",
            )
        ],
        total_results=1,
    )
    assert len(schema.products) == 1
    assert schema.total_results == 1


@pytest.mark.parametrize(
    "message, query, min_price, max_price",
    [
        ("I want laptops in the range 40k egp to 70k egp", "laptops", 40000, 70000),
        ("laptops from 40k to 70k", "laptops", 40000, 70000),
        ("gaming laptop between 40,000 and 70,000 EGP", "gaming laptop", 40000, 70000),
        # Reversed bounds are put in order.
        ("laptop 70k-40k", "laptop", 40000, 70000),
        ("monitor over 10k", "monitor", 10000, None),
        ("rtx 4060 laptop under 55k", "rtx 4060 laptop", None, 55000),
    ],
)
def test_parse_intent_price_ranges(message, query, min_price, max_price):
    result = parse_intent(message)
    assert result["query"] == query
    assert result["min_price"] == min_price
    assert result["max_price"] == max_price


def _product(title, price, relevant=True):
    return SearchResultItem(
        title=title, url=f"/p/{title.replace(' ', '-')}", price=price,
        relevant=relevant,
    )


@pytest.mark.asyncio
async def test_search_applies_min_and_max_price(search_service):
    async def mock_extract(query, store, **_):
        if store.store_id == "amazon_eg":
            return SearchResultsSchema(
                products=[
                    _product("Laptop Cheap", 30000),
                    _product("Laptop Mid", 55000),
                    _product("Laptop Pricey", 90000),
                ]
            )
        return SearchResultsSchema(products=[])

    search_service._extract_search_results = mock_extract

    results = await search_service.search("laptop", max_price=70000, min_price=40000)

    assert [r["title"] for r in results] == ["Laptop Mid"]
    await search_service.close()


@pytest.mark.asyncio
async def test_search_drops_products_marked_irrelevant(search_service):
    """Featured items on a no-results page (a CPU for a laptop search) are
    dropped even though they fit the budget."""

    async def mock_extract(query, store, **_):
        if store.store_id == "elbadrgroup":
            return SearchResultsSchema(
                products=[
                    _product("AMD Ryzen 5 5600 MPK", 5999, relevant=False),
                    _product("Acer VG270 Monitor", 6799, relevant=False),
                    _product("Lenovo IdeaPad Slim 3", 45000),
                ]
            )
        return SearchResultsSchema(products=[])

    search_service._extract_search_results = mock_extract

    results = await search_service.search("laptop")

    assert [r["title"] for r in results] == ["Lenovo IdeaPad Slim 3"]
    await search_service.close()


def test_salvage_products_from_truncated_json():
    from services.chatbot.search_service import _salvage_products_json

    truncated = (
        '{"products": [{"title": "ASUS TUF A16", "url": "/a", "price": 86500},'
        ' {"title": "Lenovo LOQ", "url": "/b", "price": 64999},'
        ' {"title": "HP Victus", "url": "/c", "pri'
    )
    salvaged = json.loads(_salvage_products_json(truncated))
    assert [p["title"] for p in salvaged["products"]] == ["ASUS TUF A16", "Lenovo LOQ"]
    assert _salvage_products_json('{"products": [{"title": "cut') is None


def test_focus_on_listings_skips_menu_prices_to_densest_block():
    from services.chatbot.search_service import LLM_INPUT_CHARS, _focus_on_listings

    menu = "Menu " + "x" * 3000 + " Featured CPU EGP 5,999 " + "y" * 12000
    grid = " ".join(f"Laptop {i} EGP {40000 + i:,}" for i in range(40))
    focused = _focus_on_listings(menu + grid)
    # The window lands on the grid, not the lone menu price.
    assert "Laptop 0 EGP" in focused[:LLM_INPUT_CHARS]
    assert "Featured CPU" not in focused


def test_focus_on_budget_keeps_only_in_budget_cards():
    from services.chatbot.search_service import _focus_on_budget

    cards = [("Omen Pricey", 139899), ("Lenovo LOQ", 64999), ("MacBook", 92999),
             ("Acer Nitro V", 55799)]
    page = "".join(
        f"[![img](https://s/{t}.jpg)](https://s/{t}) [{t}](https://s/{t}) "
        f"EGP {p:,} " + "z" * 900
        for t, p in cards
    )
    focused = _focus_on_budget(page, 40000, 70000)
    assert "Lenovo LOQ" in focused and "Acer Nitro V" in focused
    assert "Omen Pricey" not in focused and "MacBook" not in focused
    # No budget, or nothing in budget: caller falls back to the whole listing.
    assert _focus_on_budget(page, None, None) is None
    assert _focus_on_budget(page, 1, 10) is None
