"""API endpoints for tracked items management.

Add these endpoints to services/api/main.py to enable frontend integration.
"""

import logging
import time
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from services.api.credits import deduct
from services.api.dependencies import SessionLocal, get_current_user, get_db
from services.api.models import User
from services.api.price_fetcher import (
    FETCH_BLOCKED,
    FETCH_FAILED,
    FETCH_NO_PRICE,
    FETCH_OK,
    FetchResult,
    _to_usd,
    fetch_price_sync,
)
from services.api.tracked_items_models import (
    CurrentPrice,
    LowestPrice,
    TrackedItem,
    TrackedItemStore,
)

logger = logging.getLogger(__name__)

_FETCH_MAX_RETRIES = 3

# Process-local refresh throttle. MVP runs a single API instance, so an
# in-memory map bounds the spawn rate of background fetch tasks per item
# (one attempt per minute) even when every fetch fails and no price row is
# ever written. A multi-worker deployment would need this moved to Redis.
_REFRESH_THROTTLE_SECONDS = 60
_refresh_attempts: dict[str, datetime] = {}


def _validate_item_id(db: Session, item_id: str) -> None:
    """Routes accept ``str`` ids so both dev (SQLite integer PKs) and prod
    (Postgres UUID PKs) work. Validation is dialect-aware so a foreign-format
    id (e.g. a UUID string on SQLite, an integer on Postgres) is rejected
    with 422 instead of causing a DB cast error."""
    dialect = db.bind.dialect.name if db.bind else "sqlite"
    if dialect == "postgresql":
        try:
            UUID(item_id)
            return
        except (ValueError, TypeError):
            pass
    elif item_id.isascii() and item_id.isdigit():
        return
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="item_id is not a valid identifier for this environment",
    )


# Pydantic request/response models


class TrackedItemCreate(BaseModel):
    """Request model for creating a tracked item."""

    canonical_product_id: str
    specs: Optional[dict] = None
    target_price: Optional[float] = None

    @validator("canonical_product_id")
    def validate_id(cls, v):
        if not v or len(v) < 3:
            raise ValueError("canonical_product_id must be at least 3 characters")
        return v

    @validator("target_price")
    def validate_price(cls, v):
        if v is not None and v <= 0:
            raise ValueError("target_price must be positive")
        return v


class StoreMapping(BaseModel):
    """Store URL mapping for a tracked item."""

    store_id: str
    store_sku: str
    store_url: str

    @validator("store_url")
    def validate_url(cls, v):
        if not v.startswith(("http://", "https://")):
            raise ValueError("store_url must be a valid HTTP/HTTPS URL")
        return v


class TrackedItemWithStores(BaseModel):
    """Request model for creating tracked item with store mappings."""

    canonical_product_id: str
    specs: Optional[dict] = None
    target_price: Optional[float] = None
    stores: List[StoreMapping]

    @validator("stores")
    def validate_stores(cls, v):
        if not v or len(v) == 0:
            raise ValueError("At least one store mapping is required")
        return v


class PriceInfo(BaseModel):
    """Price information for a store."""

    store_id: str
    price_usd: float
    price_local: float
    currency: str
    in_stock: bool
    last_updated: datetime
    url: str


class TrackedItemResponse(BaseModel):
    """Response model for tracked item."""

    id: UUID
    canonical_product_id: str
    specs: Optional[dict]
    target_price: Optional[float]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    store_count: int
    lowest_price: Optional[PriceInfo]
    all_prices: List[PriceInfo]

    class Config:
        orm_mode = True


# Router
router = APIRouter(prefix="/tracked-items", tags=["tracked-items"])


def _image_url_for_item(db: Session, sku: str, store_id: str) -> str:
    """Read the latest scraper image without breaking older databases."""
    try:
        image_url = db.execute(
            text(
                "SELECT image_url FROM price_history "
                "WHERE sku = :sku AND store_id = :store_id "
                "ORDER BY time DESC LIMIT 1"
            ),
            {"sku": sku, "store_id": store_id},
        ).scalar()
        return image_url if isinstance(image_url, str) else ""
    except SQLAlchemyError:
        db.rollback()
        return ""


# Ordering of fetch statuses by user actionability: the most informative
# status wins when aggregating several store mappings onto one item.
_STATUS_SEVERITY = {
    FETCH_OK: 0,
    FETCH_FAILED: 1,
    FETCH_BLOCKED: 2,
    FETCH_NO_PRICE: 3,
}


def _aggregate_fetch_status(stores) -> tuple:
    """(status, error) summary across an item's store mappings.

    The highest-severity non-OK status wins (a definitive "not a product
    page" beats a transient "blocked" beats "fetch failed"), so the UI can
    show the single most actionable message. All-OK (or no mappings) is
    reported as ('ok', None).
    """
    worst = None
    worst_status: Optional[str] = None
    for store in stores:
        status = getattr(store, "last_fetch_status", None)
        if not status or status == FETCH_OK:
            continue
        if worst is None or _STATUS_SEVERITY.get(status, 1) > _STATUS_SEVERITY.get(
            worst_status, 1
        ):
            worst = store
            worst_status = status
    if worst is None:
        return FETCH_OK, None
    return worst_status, worst.last_fetch_error


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_tracked_item(
    item: TrackedItemWithStores,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Create a new tracked item with store mappings.

    Example request:
    ```json
    {
        "canonical_product_id": "lenovo-legion-5-rtx4060",
        "specs": {"brand": "Lenovo", "gpu": "RTX 4060"},
        "target_price": 45000.00,
        "stores": [
            {
                "store_id": "amazon_eg",
                "store_sku": "B0C9L8XYZ",
                "store_url": "https://amazon.eg/dp/B0C9L8XYZ"
            },
            {
                "store_id": "noon",
                "store_sku": "N123456",
                "store_url": "https://noon.com/egypt-en/product/N123456"
            }
        ]
    }
    ```
    """
    # Create tracked item
    db_item = TrackedItem(
        user_id=current_user.id,
        canonical_product_id=item.canonical_product_id,
        specs=item.specs,
        target_price=item.target_price,
        is_active=True,
    )
    db.add(db_item)
    db.flush()

    deduct(db, current_user, amount=1, reason="tracker_created")

    # Add store mappings
    for store in item.stores:
        db_store = TrackedItemStore(
            tracked_item_id=db_item.id,
            store_id=store.store_id,
            store_sku=store.store_sku,
            store_url=store.store_url,
            is_active=True,
        )
        db.add(db_store)

    db.commit()
    db.refresh(db_item)

    return {
        "id": db_item.id,
        "message": "Tracked item created successfully. "
        "Monitoring will begin on next scrape cycle.",
        "canonical_product_id": db_item.canonical_product_id,
        "store_count": len(item.stores),
    }


@router.get("/", response_model=List[dict])
async def list_tracked_items(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    include_inactive: bool = False,
) -> List[dict]:
    """List all tracked items for the current user.

    Query params:
    - include_inactive: Include disabled items (default: false)
    """
    query = db.query(TrackedItem).filter(TrackedItem.user_id == current_user.id)

    if not include_inactive:
        query = query.filter(TrackedItem.is_active)

    items = query.all()

    result = []
    for item in items:
        # Get store count
        store_count = (
            db.query(TrackedItemStore)
            .filter(
                TrackedItemStore.tracked_item_id == item.id,
                TrackedItemStore.is_active,
            )
            .count()
        )

        # Get lowest price
        lowest = (
            db.query(LowestPrice).filter(LowestPrice.tracked_item_id == item.id).first()
        )

        stores = (
            db.query(TrackedItemStore)
            .filter(
                TrackedItemStore.tracked_item_id == item.id,
                TrackedItemStore.is_active,
            )
            .all()
        )
        fetch_status, fetch_error = _aggregate_fetch_status(stores)

        result.append(
            {
                "id": item.id,
                "canonical_product_id": item.canonical_product_id,
                "target_price": float(item.target_price) if item.target_price else None,
                "is_active": item.is_active,
                "store_count": store_count,
                # Actionable state for the UI: distinguishes "fetching" (no
                # status yet) from failed fetches and non-product links.
                "fetch_status": fetch_status,
                "fetch_error": fetch_error,
                "lowest_price": (
                    {
                        "store_id": lowest.store_id,
                        "price_local": float(lowest.price_local),
                        "currency": lowest.currency,
                        "url": lowest.url,
                        # Prefer the image persisted with the price row;
                        # fall back to the best-effort history lookup for
                        # older rows written before the column existed.
                        "image_url": (
                            getattr(lowest, "image_url", None)
                            or _image_url_for_item(
                                db, item.canonical_product_id, lowest.store_id
                            )
                        ),
                    }
                    if lowest
                    else None
                ),
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
        )

    return result


@router.get("/{item_id}", response_model=dict)
async def get_tracked_item(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Get detailed information about a tracked item including all prices."""
    _validate_item_id(db, item_id)
    # Verify ownership
    item = (
        db.query(TrackedItem)
        .filter(TrackedItem.id == item_id, TrackedItem.user_id == current_user.id)
        .first()
    )

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tracked item not found"
        )

    # Get all current prices
    prices = (
        db.query(CurrentPrice, TrackedItemStore.store_url)
        .join(
            TrackedItemStore,
            (CurrentPrice.tracked_item_id == TrackedItemStore.tracked_item_id)
            & (CurrentPrice.store_id == TrackedItemStore.store_id),
        )
        .filter(CurrentPrice.tracked_item_id == item_id)
        .all()
    )

    # Get lowest price
    lowest = (
        db.query(LowestPrice).filter(LowestPrice.tracked_item_id == item_id).first()
    )

    # Aggregate fetch status across the item's store mappings so the UI can
    # show "couldn't fetch" vs "not a product page" vs "fetching".
    stores = (
        db.query(TrackedItemStore)
        .filter(
            TrackedItemStore.tracked_item_id == item_id,
            TrackedItemStore.is_active,
        )
        .all()
    )
    fetch_status, fetch_error = _aggregate_fetch_status(stores)

    return {
        "id": item.id,
        "canonical_product_id": item.canonical_product_id,
        "specs": item.specs,
        "target_price": float(item.target_price) if item.target_price else None,
        "is_active": item.is_active,
        "fetch_status": fetch_status,
        "fetch_error": fetch_error,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "lowest_price": (
            {
                "store_id": lowest.store_id,
                "price_usd": float(lowest.price_usd),
                "price_local": float(lowest.price_local),
                "currency": lowest.currency,
                "url": lowest.url,
                "image_url": (
                    getattr(lowest, "image_url", None)
                    or _image_url_for_item(
                        db, item.canonical_product_id, lowest.store_id
                    )
                ),
                "last_updated": lowest.last_updated,
            }
            if lowest
            else None
        ),
        "all_prices": [
            {
                "store_id": price.CurrentPrice.store_id,
                "price_usd": float(price.CurrentPrice.price_usd),
                "price_local": float(price.CurrentPrice.price_local),
                "currency": price.CurrentPrice.currency,
                "in_stock": price.CurrentPrice.in_stock,
                "last_updated": price.CurrentPrice.last_updated,
                "url": price.store_url,
            }
            for price in prices
        ],
    }


@router.patch("/{item_id}/target-price")
async def update_target_price(
    item_id: str,
    target_price: float,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Update the target price for a tracked item."""
    _validate_item_id(db, item_id)
    item = (
        db.query(TrackedItem)
        .filter(TrackedItem.id == item_id, TrackedItem.user_id == current_user.id)
        .first()
    )

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tracked item not found"
        )

    if target_price <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target price must be positive",
        )

    item.target_price = target_price
    item.updated_at = datetime.utcnow()
    db.commit()

    return {
        "message": "Target price updated successfully",
        "new_target_price": float(target_price),
    }


@router.patch("/{item_id}/toggle")
async def toggle_tracked_item(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Enable or disable tracking for an item."""
    _validate_item_id(db, item_id)
    item = (
        db.query(TrackedItem)
        .filter(TrackedItem.id == item_id, TrackedItem.user_id == current_user.id)
        .first()
    )

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tracked item not found"
        )

    item.is_active = not item.is_active
    item.updated_at = datetime.utcnow()
    db.commit()

    return {
        "message": f"Tracking {'enabled' if item.is_active else 'disabled'}",
        "is_active": item.is_active,
    }


@router.delete("/{item_id}")
async def delete_tracked_item(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Delete a tracked item (cascades to stores, prices)."""
    _validate_item_id(db, item_id)
    item = (
        db.query(TrackedItem)
        .filter(TrackedItem.id == item_id, TrackedItem.user_id == current_user.id)
        .first()
    )

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tracked item not found"
        )

    canonical_id = item.canonical_product_id
    db.delete(item)
    db.commit()

    return {
        "message": "Tracked item deleted successfully",
        "canonical_product_id": canonical_id,
    }


@router.post("/{item_id}/stores")
async def add_store_mapping(
    item_id: str,
    store: StoreMapping,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Add a new store mapping to an existing tracked item."""
    _validate_item_id(db, item_id)
    # Verify ownership
    item = (
        db.query(TrackedItem)
        .filter(TrackedItem.id == item_id, TrackedItem.user_id == current_user.id)
        .first()
    )

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tracked item not found"
        )

    # Check for duplicate
    existing = (
        db.query(TrackedItemStore)
        .filter(
            TrackedItemStore.tracked_item_id == item_id,
            TrackedItemStore.store_id == store.store_id,
            TrackedItemStore.store_sku == store.store_sku,
        )
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Store mapping already exists",
        )

    # Add mapping
    db_store = TrackedItemStore(
        tracked_item_id=item_id,
        store_id=store.store_id,
        store_sku=store.store_sku,
        store_url=store.store_url,
        is_active=True,
    )
    db.add(db_store)
    db.commit()

    return {"message": "Store mapping added successfully", "store_id": store.store_id}


class TrackedItemByUrl(BaseModel):
    """Create a tracked item from a single product URL (any supported store)."""

    url: str
    target_price: Optional[float] = None

    @validator("url")
    def validate_url(cls, v):
        if not v or not v.startswith(("http://", "https://")):
            raise ValueError("url must be a valid HTTP/HTTPS URL")
        return v


def _persist_fetched_price(tracked_item_id, store_id: str, url: str, canonical_id: str):
    """Visit ``url``, extract the price, and write it to the price tables.

    Runs as a FastAPI background task so the create request returns quickly.
    Uses its own DB session (the request session is closed by then).
    Retries up to ``_FETCH_MAX_RETRIES`` times with exponential backoff —
    except for a definitive ``no_price_found`` (the page loaded fine but has
    no price; a retry cannot change that, so it fails fast).

    The classified outcome (ok / no_price_found / blocked / fetch_failed)
    is always persisted to ``tracked_item_stores.last_fetch_status`` so the
    UI can show an actionable state instead of "fetching" forever.
    """
    result: Optional[FetchResult] = None
    for attempt in range(1, _FETCH_MAX_RETRIES + 1):
        logger.info(
            "Fetching price for %s (attempt %d/%d, item=%s)",
            url,
            attempt,
            _FETCH_MAX_RETRIES,
            tracked_item_id,
        )
        try:
            result = fetch_price_sync(url)
        except Exception as exc:  # noqa: BLE001 — fetch_price_sync already
            logger.warning(
                "Fetch attempt %d raised for %s: %s",
                attempt,
                url,
                exc,
            )
            result = FetchResult(
                FETCH_FAILED, f"unexpected error: {type(exc).__name__}"
            )
        if result.status == FETCH_OK:
            logger.info(
                "Price fetched for %s: %s %s (image=%s)",
                url,
                result.price.price_local,
                result.price.currency,
                bool(result.price.image_url),
            )
            break
        # A definitive "no price on page" needs no retry; blocked/failed are
        # transient (challenge may lift, network may recover) and retry.
        if result.status == FETCH_NO_PRICE:
            break
        if attempt < _FETCH_MAX_RETRIES:
            wait = 2**attempt
            logger.warning(
                "Fetch attempt %d failed for %s (%s), retrying in %ds",
                attempt,
                url,
                result.status,
                wait,
            )
            time.sleep(wait)

    db = SessionLocal()
    try:
        store_row = (
            db.query(TrackedItemStore)
            .filter(
                TrackedItemStore.tracked_item_id == tracked_item_id,
                TrackedItemStore.store_id == store_id,
            )
            .first()
        )
        if store_row is None:
            # Item/store was deleted between scheduling and execution.
            return

        if result is None or result.status != FETCH_OK or result.price is None:
            final_status = result.status if result is not None else FETCH_FAILED
            final_reason = result.reason if result is not None else "no fetch result"
            logger.warning(
                "Fetch ended %s for %s (item=%s, store=%s): %s",
                final_status,
                url,
                tracked_item_id,
                store_id,
                final_reason,
            )
            store_row.last_fetch_status = final_status
            store_row.last_fetch_error = final_reason
            db.commit()
            return

        fetched = result.price
        price_usd = _to_usd(fetched.price_local, fetched.currency)
        now = datetime.utcnow()

        # Upsert current_prices (PK: tracked_item_id, store_id).
        existing = (
            db.query(CurrentPrice)
            .filter(
                CurrentPrice.tracked_item_id == tracked_item_id,
                CurrentPrice.store_id == store_id,
            )
            .first()
        )
        if existing:
            existing.price_usd = price_usd
            existing.price_local = fetched.price_local
            existing.currency = fetched.currency
            existing.in_stock = fetched.in_stock
            existing.image_url = fetched.image_url
            existing.last_updated = now
        else:
            db.add(
                CurrentPrice(
                    tracked_item_id=tracked_item_id,
                    store_id=store_id,
                    price_usd=price_usd,
                    price_local=fetched.price_local,
                    currency=fetched.currency,
                    in_stock=fetched.in_stock,
                    image_url=fetched.image_url,
                    last_updated=now,
                )
            )

        # Upsert lowest_prices (PK: tracked_item_id) — single-store for now.
        low = (
            db.query(LowestPrice)
            .filter(LowestPrice.tracked_item_id == tracked_item_id)
            .first()
        )
        if low:
            low.store_id = store_id
            low.price_usd = price_usd
            low.price_local = fetched.price_local
            low.currency = fetched.currency
            low.url = url
            low.image_url = fetched.image_url
            low.last_updated = now
        else:
            db.add(
                LowestPrice(
                    tracked_item_id=tracked_item_id,
                    store_id=store_id,
                    price_usd=price_usd,
                    price_local=fetched.price_local,
                    currency=fetched.currency,
                    url=url,
                    image_url=fetched.image_url,
                    last_updated=now,
                )
            )

        # Commit the price upserts first: a best-effort history append must
        # never roll back (and lose) the current/lowest price rows.
        db.commit()

        # Append to price_history (best-effort; ignore conflicts).
        try:
            db.execute(
                text(
                    "INSERT INTO price_history "
                    "(time, sku, store_id, price_usd, price_local, "
                    "currency, in_stock, source_url, image_url) "
                    "VALUES (:t, :sku, :store, :usd, :local, :cur, :stock, :url, :img)"
                ),
                {
                    "t": now,
                    "sku": canonical_id,
                    "store": store_id,
                    "usd": price_usd,
                    "local": fetched.price_local,
                    "cur": fetched.currency,
                    "stock": 1 if fetched.in_stock else 0,
                    "url": url,
                    "img": fetched.image_url,
                },
            )
            db.commit()
        except SQLAlchemyError:
            db.rollback()

        # Record the successful fetch on the store mapping (clears any
        # earlier failure state so the UI stops showing the error).
        store_row.last_fetch_status = FETCH_OK
        store_row.last_fetch_error = None
        db.commit()

        logger.info(
            "Price persisted for item=%s store=%s price=%s %s",
            tracked_item_id,
            store_id,
            fetched.price_local,
            fetched.currency,
        )
    except SQLAlchemyError as exc:
        logger.exception(
            "DB error persisting price for item=%s: %s",
            tracked_item_id,
            exc,
        )
        db.rollback()
    finally:
        db.close()


@router.post("/from-url", status_code=status.HTTP_201_CREATED)
async def create_tracked_item_from_url(
    payload: TrackedItemByUrl,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Create a tracked item from a single product URL.

    Derives a canonical product id and store mapping from the URL so the
    frontend can create trackers with just a link (and optional target price).
    """
    from urllib.parse import urlparse

    parsed = urlparse(payload.url)
    host = (parsed.netloc or "").lower()
    path = parsed.path or "/"

    # Detect store from host.
    store_id = "unknown"
    for key, domain in (
        ("amazon_eg", "amazon.eg"),
        ("jumia_eg", "jumia.eg"),
        ("noon_eg", "noon.com"),
        ("elbadr_eg", "elbadrgroup.com"),
        ("compumarts_eg", "compumarts.com"),
        ("sigma_eg", "sigma-eg.com"),
        ("geeks_store_eg", "geeks-store.com"),
        ("ravin_eg", "ravin.com"),
        ("tie_house_eg", "tiehouse.com"),
        ("town_team_eg", "town-team.com"),
        ("alfrensia_eg", "alfrensia.com"),
    ):
        if domain in host:
            store_id = key
            break

    # Last non-empty path segment = SKU / slug.
    segments = [s for s in path.split("/") if s]
    sku = segments[-1] if segments else path.strip("/")
    if len(sku) < 3:
        sku = path.strip("/").replace("/", "-") or "item"

    canonical_id = f"{store_id}:{sku}"

    # Avoid duplicate trackers for the same URL.
    existing = (
        db.query(TrackedItemStore)
        .filter(TrackedItemStore.store_url == payload.url)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This product is already being tracked",
        )

    db_item = TrackedItem(
        user_id=current_user.id,
        canonical_product_id=canonical_id,
        specs={"source_url": payload.url},
        target_price=payload.target_price,
        is_active=True,
    )
    db.add(db_item)
    db.flush()

    deduct(db, current_user, amount=1, reason="tracker_created")

    db_store = TrackedItemStore(
        tracked_item_id=db_item.id,
        store_id=store_id,
        store_sku=sku,
        store_url=payload.url,
        is_active=True,
    )
    db.add(db_store)

    db.commit()
    db.refresh(db_item)

    # Visit the URL now to fetch the live price (background, non-blocking).
    item_id = db_item.id
    background_tasks.add_task(
        _persist_fetched_price, item_id, store_id, payload.url, canonical_id
    )

    return {
        "id": db_item.id,
        "message": "Tracked item created successfully. "
        "Monitoring will begin on next scrape cycle.",
        "canonical_product_id": db_item.canonical_product_id,
        "store_count": 1,
        "price_status": "fetching",
    }


@router.post("/{item_id}/refresh")
async def refresh_tracked_item_price(
    item_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Re-trigger the background price fetch for a tracked item.

    Useful when the initial fetch failed or the user wants fresher data.
    """
    _validate_item_id(db, item_id)
    item = (
        db.query(TrackedItem)
        .filter(
            TrackedItem.id == item_id,
            TrackedItem.user_id == current_user.id,
        )
        .first()
    )

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tracked item not found",
        )

    # Throttle: one refresh attempt per minute per item, tracked in-memory so
    # the limit holds even when every fetch fails and no price is persisted.
    now = datetime.utcnow()
    key = str(item.id)
    last_attempt = _refresh_attempts.get(key)
    if (
        last_attempt is not None
        and (now - last_attempt).total_seconds() < _REFRESH_THROTTLE_SECONDS
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Price refresh was attempted less than a minute ago; " "try again later"
            ),
        )

    stores = (
        db.query(TrackedItemStore)
        .filter(
            TrackedItemStore.tracked_item_id == item.id,
            TrackedItemStore.is_active,
        )
        .all()
    )

    if not stores:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active store mappings for this item",
        )

    _refresh_attempts[key] = now
    for store in stores:
        background_tasks.add_task(
            _persist_fetched_price,
            item.id,
            store.store_id,
            store.store_url,
            item.canonical_product_id,
        )
        # Reset the previous failure state so the UI immediately shows the
        # "fetching" spinner (the new fetch overwrites this when it settles).
        store.last_fetch_status = None
        store.last_fetch_error = None
    db.commit()

    lowest = (
        db.query(LowestPrice).filter(LowestPrice.tracked_item_id == item.id).first()
    )
    return {
        "message": f"Price refresh triggered for {len(stores)} store(s)",
        "store_count": len(stores),
        "price_status": "fetching",
        "last_updated": (
            lowest.last_updated.isoformat() if lowest and lowest.last_updated else None
        ),
    }


# Add to main.py:
# from services.api.tracked_items_api import router as tracked_items_router
# app.include_router(tracked_items_router)
