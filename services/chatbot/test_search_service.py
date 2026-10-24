"""Unit tests for the chatbot search service."""

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
    async def mock_extract(query, store):
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

    async def mock_extract(query, store):
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

    async def mock_extract(query, store):
        return MagicMock(products=[])

    search_service._extract_search_results = mock_extract

    results = await search_service.search("nonexistent product xyz123")

    assert results == []

    await search_service.close()


@pytest.mark.asyncio
async def test_search_with_intent(search_service):
    """Test search_with_intent parses and searches."""

    async def mock_extract(query, store):
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
