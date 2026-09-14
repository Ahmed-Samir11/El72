import os
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from fastapi.testclient import TestClient

from services.analyzer.app import app


client = TestClient(app)


def test_deal_score_endpoint():
    response = client.post(
        "/intelligence/deal-score",
        json={
            "current_price": 7500,
            "historical_prices": [9800, 10000, 10200],
            "competitor_prices": [8000, 8200],
            "discount_duration_days": 5,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["score"] >= 80
    assert body["grade"] == "Excellent"


def test_fake_discount_endpoint_rejects_invalid_price():
    response = client.post(
        "/intelligence/fake-discount",
        json={"current_price": 0, "historical_prices": [100, 110]},
    )
    assert response.status_code == 422


def test_fake_discount_and_store_movements_endpoints():
    fake = client.post(
        "/intelligence/fake-discount",
        json={
            "current_price": 9600,
            "historical_prices": [10000] * 5,
            "advertised_reference_price": 12000,
            "recent_prices": [10000, 12000, 9600],
        },
    )
    assert fake.status_code == 200
    assert fake.json()["is_suspicious"] is True

    movement = client.post(
        "/analytics/store-movements",
        json={
            "observations": [
                {"product_id": "p1", "store_id": "amazon_eg", "timestamp": "2025-09-01T00:00:00Z", "price": 100},
                {"product_id": "p1", "store_id": "amazon_eg", "timestamp": "2025-09-02T00:00:00Z", "price": 90},
            ]
        },
    )
    assert movement.status_code == 200
    assert movement.json()["movements"][0]["direction"] == "down"


def test_cross_store_endpoint():
    response = client.post(
        "/intelligence/cross-store/product-1",
        json={
            "store_prices": {"amazon_eg": 80000, "noon": 76500, "jumia_eg": 82000},
            "historical_prices_by_store": {},
        },
    )
    assert response.status_code == 200
    assert response.json()["cheapest_store"] == "noon"


def test_category_trends_and_platform_metrics_endpoints():
    timestamp = datetime(2025, 9, 1, tzinfo=timezone.utc).isoformat()
    later = datetime(2025, 9, 2, tzinfo=timezone.utc).isoformat()
    observations = [
        {"product_id": "p1", "category": "phones", "store_id": "amazon_eg", "timestamp": timestamp, "price": 10000},
        {"product_id": "p1", "category": "phones", "store_id": "amazon_eg", "timestamp": later, "price": 8500, "discount_percent": 15},
    ]
    trends = client.post("/analytics/category-trends", json={"observations": observations})
    assert trends.status_code == 200
    assert trends.json()["categories"][0]["products_dropping"] == 1

    metrics = client.post(
        "/metrics/platform",
        json={
            "products": [{"product_id": "p1", "category": "phones"}],
            "observations": observations,
            "deals": [{"product_id": "p1", "timestamp": later, "is_historical_low": True}],
            "suspicious_discounts": [],
            "as_of": "2025-09-02",
        },
    )
    assert metrics.status_code == 200
    assert metrics.json()["products_tracked"] == 1
    assert metrics.json()["historical_lows_detected"] == 1


def test_category_endpoint_requires_categories():
    response = client.post(
        "/analytics/category-trends",
        json={
            "observations": [
                {
                    "product_id": "p1",
                    "store_id": "amazon_eg",
                    "timestamp": "2025-09-01T00:00:00Z",
                    "price": 100,
                }
            ]
        },
    )
    assert response.status_code == 422


def test_cross_store_endpoint_rejects_empty_store_mapping():
    response = client.post(
        "/intelligence/cross-store/product-1",
        json={"store_prices": {}},
    )
    assert response.status_code == 422
