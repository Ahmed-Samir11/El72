from datetime import date, datetime, timedelta, timezone

from services.analyzer.platform_metrics import platform_metrics


def test_platform_metrics_are_data_backed_and_time_aware():
    start = datetime(2025, 9, 1, tzinfo=timezone.utc)
    products = [
        {"product_id": "p1", "category": "phones"},
        {"product_id": "p2", "category": "laptops"},
    ]
    observations = [
        {"product_id": "p1", "store_id": "amazon_eg", "category": "phones", "price": 100, "timestamp": start, "change_percent": -0.05},
        {"product_id": "p1", "store_id": "noon", "category": "phones", "price": 110, "timestamp": start + timedelta(days=1), "change_percent": 0.02},
        {"product_id": "p2", "store_id": "amazon_eg", "category": "laptops", "price": 1000, "timestamp": start + timedelta(days=6), "change_percent": 0.01},
    ]
    deals = [
        {"timestamp": start + timedelta(days=6), "is_historical_low": True},
        {"timestamp": start, "is_historical_low": False},
    ]
    suspicious = [
        {"timestamp": start + timedelta(days=6), "is_suspicious": True},
        {"timestamp": start, "is_suspicious": False},
    ]
    result = platform_metrics(products, observations, deals, suspicious, as_of=date(2025, 9, 7))
    assert result["products_tracked"] == 2
    assert result["stores_tracked"] == 2
    assert result["price_observations"] == 3
    assert result["days_of_historical_coverage"] == 7
    assert result["categories_tracked"] == 2
    assert result["deals_detected"] == 2
    assert result["historical_lows_detected"] == 1
    assert result["suspicious_discounts_detected"] == 1
    assert result["weekly"] == {
        "price_observations": 3,
        "deals_detected": 2,
        "suspicious_discounts_detected": 2,
    }
    assert result["average_price_change"] == -0.0067


def test_empty_platform_metrics_are_zeroed():
    result = platform_metrics([], [], [], [], as_of=date(2025, 9, 7))
    assert result == {
        "products_tracked": 0,
        "stores_tracked": 0,
        "price_observations": 0,
        "days_of_historical_coverage": 0,
        "categories_tracked": 0,
        "deals_detected": 0,
        "historical_lows_detected": 0,
        "suspicious_discounts_detected": 0,
        "average_price_change": 0.0,
        "average_observed_price": 0.0,
        "weekly": {
            "price_observations": 0,
            "deals_detected": 0,
            "suspicious_discounts_detected": 0,
        },
    }
