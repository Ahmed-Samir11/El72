import pytest

from services.analyzer.cross_store import compare_store_prices


def test_cross_store_comparison_returns_market_position_and_ranking():
    result = compare_store_prices(
        "demo-el72-cross-store-tv",
        {"amazon_eg": 80000, "noon": 76500, "jumia_eg": 82000},
    )
    assert result["cheapest_store"] == "noon"
    assert result["most_expensive_store"] == "jumia_eg"
    assert result["market_average"] == 79500
    assert result["spread"] == 5500
    assert result["spread_percent"] == pytest.approx(0.0692, abs=0.0001)
    assert result["market_position"] == "meaningful_spread"
    assert [row["store_id"] for row in result["ranking"]] == ["noon", "amazon_eg", "jumia_eg"]
    assert result["ranking"][0]["rank"] == 1
    assert result["ranking"][0]["is_cheapest"] is True


def test_historical_low_is_evaluated_across_store_and_per_store():
    result = compare_store_prices(
        "product-1",
        {"amazon_eg": 100, "noon": 120},
        {
            "amazon_eg": [100, 110, 115],
            "noon": [90, 120, 125],
        },
    )
    assert result["is_historical_low"] is False
    assert result["historical_minimum"] == 90
    assert result["store_historical_lows"] == {"amazon_eg": True, "noon": False}


def test_ties_are_ranked_deterministically_by_store_id():
    result = compare_store_prices("product-1", {"noon": 100, "amazon_eg": 100})
    assert [row["store_id"] for row in result["ranking"]] == ["amazon_eg", "noon"]
    assert result["cheapest_store"] == "amazon_eg"
    assert result["most_expensive_store"] == "amazon_eg"


def test_without_history_returns_market_statistics_only():
    result = compare_store_prices("product-1", {"amazon_eg": 100})
    assert result["market_position"] == "no_spread"
    assert result["historical_minimum"] is None
    assert result["store_historical_lows"] == {}


def test_tight_and_no_spread_market_positions():
    tight = compare_store_prices("product-1", {"amazon_eg": 100, "noon": 101})
    identical = compare_store_prices("product-2", {"amazon_eg": 100, "noon": 100})
    assert tight["market_position"] == "tight_spread"
    assert identical["market_position"] == "no_spread"


@pytest.mark.parametrize(
    "product_id, store_prices",
    [
        ("", {"amazon_eg": 100}),
        ("product-1", {}),
        ("product-1", {"amazon_eg": 0}),
        ("product-1", {"": 100}),
    ],
)
def test_invalid_comparison_inputs_are_rejected(product_id, store_prices):
    with pytest.raises(ValueError):
        compare_store_prices(product_id, store_prices)


def test_invalid_historical_price_is_rejected():
    with pytest.raises(ValueError):
        compare_store_prices("product-1", {"amazon_eg": 100}, {"amazon_eg": [0]})
