"""Unit tests for tracked items API endpoints."""

import os
from datetime import datetime
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.dependencies import get_current_user, get_db
from services.api.models import Base as ApiBase, User
from services.api.tracked_items_api import (
    StoreMapping,
    TrackedItemCreate,
    TrackedItemWithStores,
    router,
)
from services.api.tracked_items_models import (
    CurrentPrice,
    LowestPrice,
    TrackedItem,
    TrackedItemStore,
)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ApiBase.metadata.create_all(bind=engine)
    for table in (
        TrackedItem.__table__,
        TrackedItemStore.__table__,
        CurrentPrice.__table__,
        LowestPrice.__table__,
    ):
        table.create(bind=engine, checkfirst=True)

    Session = sessionmaker(bind=engine)
    session = Session()

    user = User(phone="+201000000001", password_hash="x", salt="y", tier="free")
    session.add(user)
    session.commit()
    session.refresh(user)

    yield session, user
    session.close()
    engine.dispose()


@pytest.fixture
def client(db_session):
    session, user = db_session

    app = FastAPI()
    app.include_router(router)

    def _get_db():
        try:
            yield session
        finally:
            pass

    def _get_user():
        return user

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_user
    return TestClient(app), session, user


def test_tracked_item_create_validators():
    with pytest.raises(ValidationError):
        TrackedItemCreate(canonical_product_id="ab")
    with pytest.raises(ValidationError):
        TrackedItemCreate(canonical_product_id="valid-id", target_price=-1)
    item = TrackedItemCreate(canonical_product_id="valid-id", target_price=10)
    assert item.canonical_product_id == "valid-id"


def test_store_mapping_and_with_stores_validators():
    with pytest.raises(ValidationError):
        StoreMapping(store_id="a", store_sku="s", store_url="ftp://bad")
    with pytest.raises(ValidationError):
        TrackedItemWithStores(canonical_product_id="prod-123", stores=[])
    ok = TrackedItemWithStores(
        canonical_product_id="prod-123",
        stores=[
            StoreMapping(
                store_id="amazon_eg",
                store_sku="B1",
                store_url="https://amazon.eg/dp/B1",
            )
        ],
    )
    assert len(ok.stores) == 1


def test_create_tracked_item(client):
    api, session, user = client
    payload = {
        "canonical_product_id": "lenovo-legion-5",
        "specs": {"gpu": "RTX 4060"},
        "target_price": 45000,
        "stores": [
            {
                "store_id": "amazon_eg",
                "store_sku": "B0C9",
                "store_url": "https://amazon.eg/dp/B0C9",
            }
        ],
    }
    resp = api.post("/tracked-items/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["canonical_product_id"] == "lenovo-legion-5"
    assert data["store_count"] == 1
    assert session.query(TrackedItem).count() == 1
    assert session.query(TrackedItemStore).count() == 1


def test_list_tracked_items_with_and_without_lowest(client):
    api, session, user = client
    item = TrackedItem(
        user_id=user.id,
        canonical_product_id="item-a",
        target_price=Decimal("100.00"),
        is_active=True,
    )
    session.add(item)
    session.flush()
    session.add(
        TrackedItemStore(
            tracked_item_id=item.id,
            store_id="amazon_eg",
            store_sku="S1",
            store_url="https://amazon.eg/dp/S1",
            is_active=True,
        )
    )
    session.add(
        LowestPrice(
            tracked_item_id=item.id,
            store_id="amazon_eg",
            price_usd=Decimal("3.2"),
            price_local=Decimal("100"),
            currency="EGP",
            url="https://amazon.eg/dp/S1",
            last_updated=datetime.utcnow(),
        )
    )
    inactive = TrackedItem(
        user_id=user.id,
        canonical_product_id="item-b",
        is_active=False,
    )
    session.add(inactive)
    session.commit()

    active = api.get("/tracked-items/")
    assert active.status_code == 200
    assert len(active.json()) == 1
    assert active.json()[0]["lowest_price"]["store_id"] == "amazon_eg"

    all_items = api.get("/tracked-items/?include_inactive=true")
    assert len(all_items.json()) == 2


def test_get_tracked_item_not_found(client):
    api, _, _ = client
    resp = api.get("/tracked-items/999")
    assert resp.status_code == 404


def test_get_tracked_item_detail(client):
    api, session, user = client
    item = TrackedItem(
        user_id=user.id,
        canonical_product_id="detail-item",
        specs={"brand": "X"},
        target_price=Decimal("200"),
        is_active=True,
    )
    session.add(item)
    session.flush()
    session.add(
        TrackedItemStore(
            tracked_item_id=item.id,
            store_id="noon",
            store_sku="N1",
            store_url="https://noon.com/p/N1",
            is_active=True,
        )
    )
    session.add(
        CurrentPrice(
            tracked_item_id=item.id,
            store_id="noon",
            price_usd=Decimal("6.4"),
            price_local=Decimal("200"),
            currency="EGP",
            in_stock=True,
            last_updated=datetime.utcnow(),
        )
    )
    session.add(
        LowestPrice(
            tracked_item_id=item.id,
            store_id="noon",
            price_usd=Decimal("6.4"),
            price_local=Decimal("200"),
            currency="EGP",
            url="https://noon.com/p/N1",
            last_updated=datetime.utcnow(),
        )
    )
    session.commit()

    resp = api.get(f"/tracked-items/{item.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["canonical_product_id"] == "detail-item"
    assert body["lowest_price"]["currency"] == "EGP"
    assert len(body["all_prices"]) == 1


def test_update_target_price_success_and_errors(client):
    api, session, user = client
    item = TrackedItem(
        user_id=user.id, canonical_product_id="price-item", is_active=True
    )
    session.add(item)
    session.commit()

    assert api.patch(f"/tracked-items/{item.id}/target-price?target_price=50").status_code == 200
    assert api.patch(f"/tracked-items/{item.id}/target-price?target_price=0").status_code == 400
    assert api.patch("/tracked-items/999/target-price?target_price=10").status_code == 404


def test_toggle_and_delete_tracked_item(client):
    api, session, user = client
    item = TrackedItem(
        user_id=user.id, canonical_product_id="toggle-item", is_active=True
    )
    session.add(item)
    session.commit()

    toggle = api.patch(f"/tracked-items/{item.id}/toggle")
    assert toggle.status_code == 200
    assert toggle.json()["is_active"] is False

    assert api.patch("/tracked-items/999/toggle").status_code == 404

    deleted = api.delete(f"/tracked-items/{item.id}")
    assert deleted.status_code == 200
    assert session.query(TrackedItem).filter_by(id=item.id).first() is None
    assert api.delete("/tracked-items/999").status_code == 404


def test_add_store_mapping_success_and_duplicate(client):
    api, session, user = client
    item = TrackedItem(
        user_id=user.id, canonical_product_id="store-item", is_active=True
    )
    session.add(item)
    session.commit()

    payload = {
        "store_id": "jumia",
        "store_sku": "J1",
        "store_url": "https://jumia.com.eg/p/J1",
    }
    first = api.post(f"/tracked-items/{item.id}/stores", json=payload)
    assert first.status_code == 200

    dup = api.post(f"/tracked-items/{item.id}/stores", json=payload)
    assert dup.status_code == 400

    assert api.post("/tracked-items/999/stores", json=payload).status_code == 404


def test_create_tracked_item_from_url(client, monkeypatch):
    api, session, user = client
    # Mock fetch_price_sync to simulate a successful price fetch
    from services.api.price_fetcher import FetchedPrice
    monkeypatch.setattr(
        "services.api.tracked_items_api.fetch_price_sync",
        lambda url: FetchedPrice(price_local=1500.0, currency="EGP", title="Sample Item", image_url="http://img.com/a.jpg"),
    )

    resp = api.post(
        "/tracked-items/from-url",
        json={"url": "https://www.amazon.eg/dp/B0C9L8XYZ", "target_price": 1400.0},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["price_status"] == "fetching"
    assert "id" in data


def test_persist_fetched_price_retry_logic(db_session, monkeypatch):
    session, user = db_session
    item = TrackedItem(user_id=user.id, canonical_product_id="retry-test-item", is_active=True)
    session.add(item)
    session.commit()

    attempts = 0
    from services.api.price_fetcher import FetchedPrice

    def mock_fetch(url):
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            return None  # Fail first attempt
        return FetchedPrice(price_local=250.0, currency="EGP", title="Test Item", image_url="https://img.com/b.jpg")

    monkeypatch.setattr("services.api.tracked_items_api.fetch_price_sync", mock_fetch)
    monkeypatch.setattr("services.api.tracked_items_api._FETCH_MAX_RETRIES", 3)
    monkeypatch.setattr("time.sleep", lambda secs: None)  # Skip sleep delay in test
    # The background task opens its own SessionLocal; point it at the fixture
    # DB so persistence is observable in-test.
    monkeypatch.setattr("services.api.tracked_items_api.SessionLocal", lambda: session)

    from services.api.tracked_items_api import _persist_fetched_price
    item_id = item.id  # persist closes the session; use the scalar afterwards
    _persist_fetched_price(item_id, "amazon_eg", "https://amazon.eg/dp/123", "retry-test-item")

    assert attempts == 2

    # Successful fetch must persist to the price tables.
    price = session.query(CurrentPrice).filter(
        CurrentPrice.tracked_item_id == item_id,
        CurrentPrice.store_id == "amazon_eg",
    ).first()
    assert price is not None
    assert float(price.price_local) == 250.0
    lowest = session.query(LowestPrice).filter(
        LowestPrice.tracked_item_id == item_id
    ).first()
    assert lowest is not None
    assert lowest.store_id == "amazon_eg"


def test_persist_fetched_price_retry_exhaustion(db_session, monkeypatch):
    """When every fetch attempt fails, no price rows are written."""
    session, user = db_session
    item = TrackedItem(user_id=user.id, canonical_product_id="exhaust-test-item", is_active=True)
    session.add(item)
    session.commit()

    monkeypatch.setattr(
        "services.api.tracked_items_api.fetch_price_sync",
        lambda url: None,
    )
    monkeypatch.setattr("services.api.tracked_items_api._FETCH_MAX_RETRIES", 3)
    monkeypatch.setattr("time.sleep", lambda secs: None)
    monkeypatch.setattr("services.api.tracked_items_api.SessionLocal", lambda: session)

    from services.api.tracked_items_api import _persist_fetched_price
    item_id = item.id
    _persist_fetched_price(item_id, "amazon_eg", "https://amazon.eg/dp/456", "exhaust-test-item")

    assert session.query(CurrentPrice).filter(
        CurrentPrice.tracked_item_id == item_id
    ).count() == 0
    assert session.query(LowestPrice).filter(
        LowestPrice.tracked_item_id == item_id
    ).count() == 0


def test_persist_fetched_price_handles_fetch_exception(db_session, monkeypatch):
    """A raising fetcher must not crash the background task or write rows."""
    session, user = db_session
    item = TrackedItem(user_id=user.id, canonical_product_id="exc-test-item", is_active=True)
    session.add(item)
    session.commit()

    def boom(url):
        raise RuntimeError("network down")

    monkeypatch.setattr("services.api.tracked_items_api.fetch_price_sync", boom)
    monkeypatch.setattr("services.api.tracked_items_api._FETCH_MAX_RETRIES", 3)
    monkeypatch.setattr("time.sleep", lambda secs: None)
    monkeypatch.setattr("services.api.tracked_items_api.SessionLocal", lambda: session)

    from services.api.tracked_items_api import _persist_fetched_price
    item_id = item.id
    _persist_fetched_price(item_id, "amazon_eg", "https://amazon.eg/dp/789", "exc-test-item")

    assert session.query(CurrentPrice).filter(
        CurrentPrice.tracked_item_id == item_id
    ).count() == 0


def test_create_access_token_default_expiry_is_7_days():
    """MVP has no refresh flow, so the default access token must outlive a session."""
    from jose import jwt
    from services.api.dependencies import ALGORITHM, SECRET_KEY, create_access_token

    import time

    token = create_access_token({"sub": "user-1"})
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    lifetime = payload["exp"] - time.time()
    assert 7 * 24 * 3600 - 5 <= lifetime <= 7 * 24 * 3600 + 5





def test_invalid_item_id_returns_422_on_all_routes(client):
    """Route accepts str ids (SQLite int / Postgres UUID); garbage is 422 on
    every item-scoped route, before any DB access."""
    api, _, _ = client
    bad = "not-a-valid-id"
    assert api.get(f"/tracked-items/{bad}").status_code == 422
    assert api.patch(f"/tracked-items/{bad}/toggle").status_code == 422
    assert api.patch(f"/tracked-items/{bad}/target-price?target_price=10").status_code == 422
    assert api.post(
        f"/tracked-items/{bad}/stores",
        json={"store_id": "amazon_eg", "store_url": "https://amazon.eg/x"},
    ).status_code == 422
    assert api.delete(f"/tracked-items/{bad}").status_code == 422
    assert api.post(f"/tracked-items/{bad}/refresh").status_code == 422


def test_refresh_tracked_item_price(client, db_session, monkeypatch):
    """Refresh triggers a background fetch and throttles rapid re-runs even
    when no price has ever been persisted (the fetch-failure spam path)."""
    # TestClient executes background tasks inline; keep them off the network.
    monkeypatch.setattr("services.api.tracked_items_api.fetch_price_sync", lambda url: None)
    monkeypatch.setattr("services.api.tracked_items_api._refresh_attempts", {})
    api, session, user = client
    item = TrackedItem(user_id=user.id, canonical_product_id="refresh-item", is_active=True)
    session.add(item)
    session.commit()  # item.id is populated only after the insert
    store = TrackedItemStore(tracked_item_id=item.id, store_id="amazon_eg",
                             store_sku="SKU1",
                             store_url="https://amazon.eg/p/1")
    session.add(store)
    session.commit()

    # No price rows at all -> first refresh is accepted.
    resp = api.post(f"/tracked-items/{item.id}/refresh")
    assert resp.status_code == 200
    assert resp.json()["price_status"] == "fetching"

    # Second attempt within a minute is throttled (no price was written).
    resp = api.post(f"/tracked-items/{item.id}/refresh")
    assert resp.status_code == 429


def test_refresh_tracked_item_price_404_and_400(client, db_session):
    """Refresh on a missing item is 404; an item without active stores is 400."""
    api, session, user = client
    assert api.post("/tracked-items/999/refresh").status_code == 404

    item = TrackedItem(user_id=user.id, canonical_product_id="no-stores-item", is_active=True)
    session.add(item)
    session.commit()
    assert api.post(f"/tracked-items/{item.id}/refresh").status_code == 400
