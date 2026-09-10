from datetime import datetime, timedelta, timezone

import pytest

from services.analyzer.b2b_analytics import (
    category_trends,
    competitor_position,
    opportunity_signals,
    store_movements,
)


def test_competitor_position_for_retailer():
    result = competitor_position(
        "amazon_eg",
        {"amazon_eg": 28500, "noon": 30200, "jumia_eg": 29100},
    )
    assert result["market_average"] == pytest.approx(29266.67, abs=0.01)
    assert result["market_rank"] == 1
    assert result["is_market_minimum"] is True
    assert result["price_gap_vs_average"] < 0


def _observations():
    first = datetime(2025, 9, 1, tzinfo=timezone.utc)
    return [
        {"product_id": "p1", "category": "phones", "store_id": "amazon_eg", "timestamp": first, "price": 10000, "discount_percent": 0},
        {"product_id": "p1", "category": "phones", "store_id": "amazon_eg", "timestamp": first + timedelta(days=1), "price": 8500, "discount_percent": 15},
        {"product_id": "p2", "category": "phones", "store_id": "noon", "timestamp": first, "price": 12000, "discount_percent": 0},
        {"product_id": "p2", "category": "phones", "store_id": "noon", "timestamp": first + timedelta(days=1), "price": 13000, "discount_percent": 0},
        {"product_id": "p3", "category": "laptops", "store_id": "jumia_eg", "timestamp": first, "price": 50000, "discount_percent": 0},
    ]


def test_category_trends_aggregate_movement_and_deal_density():
    results = category_trends(_observations())
    phones = next(item for item in results if item["category"] == "phones")
    assert phones["product_count"] == 2
    assert phones["products_dropping"] == 1
    assert phones["products_increasing"] == 1
    assert phones["deal_density"] == pytest.approx(0.25)


def test_store_movements_identify_direction():
    results = store_movements(_observations())
    p1 = next(item for item in results if item["product_id"] == "p1")
    p2 = next(item for item in results if item["product_id"] == "p2")
    assert p1["direction"] == "down"
    assert p1["change_percent"] == pytest.approx(-0.15)
    assert p2["direction"] == "up"


def test_opportunity_signals_are_real_counts():
    positions = [
        {"price_gap_vs_average": 0.12},
        {"price_gap_vs_average": 0.02},
        {"price_gap_vs_average": 0.15},
    ]
    assert opportunity_signals(positions, historical_low_count=4, volatile_product_count=2) == {
        "products_above_market_10_percent": 2,
        "products_at_historical_lows": 4,
        "products_with_high_volatility": 2,
        "total_products": 3,
    }


def test_invalid_b2b_inputs_are_rejected():
    with pytest.raises(ValueError):
        competitor_position("missing", {"amazon_eg": 100})
    with pytest.raises(ValueError):
        category_trends([{"category": "phones", "price": 0, "timestamp": datetime.now(timezone.utc)}])
    with pytest.raises(ValueError):
        store_movements([{"store_id": "amazon_eg", "price": 100, "timestamp": datetime.now(timezone.utc)}])
    with pytest.raises(ValueError):
        category_trends([{"category": "phones", "price": 100, "timestamp": "not-a-date"}])
    with pytest.raises(ValueError):
        category_trends([{"price": 100, "timestamp": datetime.now(timezone.utc)}])
