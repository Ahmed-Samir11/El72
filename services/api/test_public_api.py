"""Tests for the public demo API endpoints.

Covers ``/stats``, ``/deals/live``, ``/price-history/{sku}`` and ``/pricing``
in ``services/api/routers/public_api.py``. Uses an in-memory SQLite database
seeded with a small, deterministic price history so the assertions are exact.
"""

import os
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.dependencies import get_db
from services.api.routers import public_api
from services.api.seed_demo_data import _PRICE_HISTORY_DDL


def _make_client(seed: bool = True):
    """Build a TestClient with an in-memory SQLite price_history table."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text(_PRICE_HISTORY_DDL))

    if seed:
        now = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        rows = []
        # Two SKUs, each trending down over 30 days (a genuine "deal").
        for sku, start, end in [
            ("iphone-15-pro-max-256gb", 145000.0, 129999.0),
            ("nvidia-rtx-4060-8gb", 16000.0, 14999.0),
        ]:
            for i in range(30):
                t = now - timedelta(days=30 - 1 - i)
                progress = i / 29
                price = start + (end - start) * progress
                rows.append(
                    {
                        "time": t,
                        "sku": sku,
                        "store_id": "amazon_eg",
                        "price_usd": round(price / 48.0, 4),
                        "price_local": round(price, 2),
                        "currency": "EGP",
                        "in_stock": True,
                        "source_url": f"https://amazon.eg/dp/{sku}",
                    }
                )
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO price_history "
                    "(time, sku, store_id, price_usd, price_local, currency, "
                    " in_stock, source_url) "
                    "VALUES (:time, :sku, :store_id, :price_usd, :price_local, "
                    " :currency, :in_stock, :source_url)"
                ),
                rows,
            )

    session = sessionmaker(bind=engine)()

    app = FastAPI()
    app.include_router(public_api.router)

    def _get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app), session, engine


def test_price_history_returns_series():
    client, session, engine = _make_client()
    try:
        res = client.get("/price-history/iphone-15-pro-max-256gb")
        assert res.status_code == 200
        points = res.json()
        assert len(points) == 30
        # Downward trend: first day pricier than last day.
        assert points[0]["price_local"] > points[-1]["price_local"]
        for p in points:
            assert "time" in p and "price_usd" in p and "in_stock" in p
    finally:
        session.close()
        engine.dispose()


def test_price_history_unknown_sku_empty():
    client, session, engine = _make_client()
    try:
        assert client.get("/price-history/does-not-exist").json() == []
    finally:
        session.close()
        engine.dispose()


def test_deals_live():
    client, session, engine = _make_client()
    try:
        res = client.get("/deals/live")
        assert res.status_code == 200
        deals = res.json()
        assert len(deals) == 2
        top = deals[0]
        assert top["price"] < top["original_price"]
        assert top["discount_percentage"] > 0
        assert top["store_name"] == "Amazon EG"
        assert top["url"].startswith("http://localhost:8000/affiliate/redirect?")
        # Ranked by discount depth (descending).
        discounts = [d["discount_percentage"] for d in deals]
        assert discounts == sorted(discounts, reverse=True)
    finally:
        session.close()
        engine.dispose()


def test_stats():
    client, session, engine = _make_client()
    try:
        res = client.get("/stats")
        assert res.status_code == 200
        s = res.json()
        assert s["total_trackers"] == 2
        assert s["stores_monitored"] == 1
        assert s["deals_today"] == 2
        assert s["total_savings"] > 0
        # Both consumer key sets present (Flutter + landing page).
        assert "deals_found_today" in s and "total_savings_egp" in s
        assert s["deals_found_today"] == s["deals_today"]
    finally:
        session.close()
        engine.dispose()


def test_pricing():
    client, session, engine = _make_client()
    try:
        res = client.get("/pricing")
        assert res.status_code == 200
        data = res.json()
        assert data["currency"] == "EGP"
        assert [t["id"] for t in data["tiers"]] == ["free", "standard", "premium"]
        assert data["tiers"][0]["price_egp"] == 0
        assert data["tiers"][1]["price_egp"] == 30
        assert data["tiers"][2]["price_egp"] == 90
    finally:
        session.close()
        engine.dispose()


def test_fail_soft_when_table_missing():
    # No price_history table at all -> endpoints return empty, not 500.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session = sessionmaker(bind=engine)()
    app = FastAPI()
    app.include_router(public_api.router)

    def _get_db():
        yield session

    app.dependency_overrides[get_db] = _get_db
    client = TestClient(app)
    try:
        assert client.get("/stats").json()["total_trackers"] == 0
        assert client.get("/deals/live").json() == []
        assert client.get("/price-history/anything").json() == []
    finally:
        session.close()
        engine.dispose()
