"""Tests for extraction schemas (Pydantic v1)."""

import pytest
from pydantic import ValidationError

from services.scraper.extraction_schemas import (
    Currency,
    ProductPriceSchema,
    SearchResultsSchema,
    StockStatus,
    get_product_schema_json,
    get_search_schema_json,
    parse_product_response,
    parse_search_response,
)


def test_product_schema_parse_and_helpers():
    data = {
        "title": "GPU",
        "price": 1000.0,
        "currency": "EGP",
        "stock_status": "in_stock",
    }
    product = parse_product_response(data)
    assert product.title == "GPU"
    assert product.currency == Currency.EGP
    assert product.stock_status == StockStatus.IN_STOCK
    assert "title" in get_product_schema_json()


def test_product_schema_invalid():
    with pytest.raises(ValidationError):
        ProductPriceSchema(title="x")  # missing price


def test_search_schema_parse_and_helpers():
    data = {
        "products": [
            {"title": "A", "url": "/a", "price": 10, "currency": "EGP", "in_stock": True}
        ],
        "total_results": 1,
        "current_page": 1,
        "has_next_page": False,
    }
    parsed = parse_search_response(data)
    assert len(parsed.products) == 1
    assert isinstance(parsed, SearchResultsSchema)
    assert "products" in get_search_schema_json()
