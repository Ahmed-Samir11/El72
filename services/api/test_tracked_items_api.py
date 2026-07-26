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
