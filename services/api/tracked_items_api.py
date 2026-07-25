"""API endpoints for tracked items management.

Add these endpoints to services/api/main.py to enable frontend integration.
"""

from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, validator
from sqlalchemy.orm import Session

from services.api.dependencies import get_db, get_current_user
from services.api.models import User
from services.api.tracked_items_models import TrackedItem, TrackedItemStore, CurrentPrice, LowestPrice


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
    id: int
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


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_tracked_item(
    item: TrackedItemWithStores,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
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
        is_active=True
    )
    db.add(db_item)
    db.flush()
    
    # Add store mappings
    for store in item.stores:
        db_store = TrackedItemStore(
            tracked_item_id=db_item.id,
            store_id=store.store_id,
            store_sku=store.store_sku,
            store_url=store.store_url,
            is_active=True
        )
        db.add(db_store)
    
    db.commit()
    db.refresh(db_item)
    
    return {
        "id": db_item.id,
        "message": "Tracked item created successfully. Monitoring will begin on next scrape cycle.",
        "canonical_product_id": db_item.canonical_product_id,
        "store_count": len(item.stores)
    }


@router.get("/", response_model=List[dict])
async def list_tracked_items(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    include_inactive: bool = False
) -> List[dict]:
    """List all tracked items for the current user.
    
    Query params:
    - include_inactive: Include disabled items (default: false)
    """
    query = db.query(TrackedItem).filter(TrackedItem.user_id == current_user.id)
    
    if not include_inactive:
        query = query.filter(TrackedItem.is_active == True)
    
    items = query.all()
    
    result = []
    for item in items:
        # Get store count
        store_count = db.query(TrackedItemStore).filter(
            TrackedItemStore.tracked_item_id == item.id,
            TrackedItemStore.is_active == True
        ).count()
        
        # Get lowest price
        lowest = db.query(LowestPrice).filter(
            LowestPrice.tracked_item_id == item.id
        ).first()
        
        result.append({
            "id": item.id,
            "canonical_product_id": item.canonical_product_id,
            "target_price": float(item.target_price) if item.target_price else None,
            "is_active": item.is_active,
            "store_count": store_count,
            "lowest_price": {
                "store_id": lowest.store_id,
                "price_local": float(lowest.price_local),
                "currency": lowest.currency,
                "url": lowest.url
            } if lowest else None,
            "created_at": item.created_at,
            "updated_at": item.updated_at
        })
    
    return result


@router.get("/{item_id}", response_model=dict)
async def get_tracked_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> dict:
    """Get detailed information about a tracked item including all prices."""
    # Verify ownership
    item = db.query(TrackedItem).filter(
        TrackedItem.id == item_id,
        TrackedItem.user_id == current_user.id
    ).first()
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tracked item not found"
        )
    
    # Get all current prices
    prices = db.query(CurrentPrice, TrackedItemStore.store_url).join(
        TrackedItemStore,
        (CurrentPrice.tracked_item_id == TrackedItemStore.tracked_item_id) &
        (CurrentPrice.store_id == TrackedItemStore.store_id)
    ).filter(CurrentPrice.tracked_item_id == item_id).all()
    
    # Get lowest price
    lowest = db.query(LowestPrice).filter(
        LowestPrice.tracked_item_id == item_id
    ).first()
    
    return {
        "id": item.id,
        "canonical_product_id": item.canonical_product_id,
        "specs": item.specs,
        "target_price": float(item.target_price) if item.target_price else None,
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "lowest_price": {
            "store_id": lowest.store_id,
            "price_usd": float(lowest.price_usd),
            "price_local": float(lowest.price_local),
            "currency": lowest.currency,
            "url": lowest.url,
            "last_updated": lowest.last_updated
        } if lowest else None,
        "all_prices": [
            {
                "store_id": price.CurrentPrice.store_id,
                "price_usd": float(price.CurrentPrice.price_usd),
                "price_local": float(price.CurrentPrice.price_local),
                "currency": price.CurrentPrice.currency,
                "in_stock": price.CurrentPrice.in_stock,
                "last_updated": price.CurrentPrice.last_updated,
                "url": price.store_url
            }
            for price in prices
        ]
    }


@router.patch("/{item_id}/target-price")
async def update_target_price(
    item_id: int,
    target_price: float,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> dict:
    """Update the target price for a tracked item."""
    item = db.query(TrackedItem).filter(
        TrackedItem.id == item_id,
        TrackedItem.user_id == current_user.id
    ).first()
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tracked item not found"
        )
    
    if target_price <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target price must be positive"
        )
    
    item.target_price = target_price
    item.updated_at = datetime.utcnow()
    db.commit()
    
    return {
        "message": "Target price updated successfully",
        "new_target_price": float(target_price)
    }


@router.patch("/{item_id}/toggle")
async def toggle_tracked_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> dict:
    """Enable or disable tracking for an item."""
    item = db.query(TrackedItem).filter(
        TrackedItem.id == item_id,
        TrackedItem.user_id == current_user.id
    ).first()
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tracked item not found"
        )
    
    item.is_active = not item.is_active
    item.updated_at = datetime.utcnow()
    db.commit()
    
    return {
        "message": f"Tracking {'enabled' if item.is_active else 'disabled'}",
        "is_active": item.is_active
    }


@router.delete("/{item_id}")
async def delete_tracked_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> dict:
    """Delete a tracked item (cascades to stores, prices)."""
    item = db.query(TrackedItem).filter(
        TrackedItem.id == item_id,
        TrackedItem.user_id == current_user.id
    ).first()
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tracked item not found"
        )
    
    canonical_id = item.canonical_product_id
    db.delete(item)
    db.commit()
    
    return {
        "message": "Tracked item deleted successfully",
        "canonical_product_id": canonical_id
    }


@router.post("/{item_id}/stores")
async def add_store_mapping(
    item_id: int,
    store: StoreMapping,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> dict:
    """Add a new store mapping to an existing tracked item."""
    # Verify ownership
    item = db.query(TrackedItem).filter(
        TrackedItem.id == item_id,
        TrackedItem.user_id == current_user.id
    ).first()
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tracked item not found"
        )
    
    # Check for duplicate
    existing = db.query(TrackedItemStore).filter(
        TrackedItemStore.tracked_item_id == item_id,
        TrackedItemStore.store_id == store.store_id,
        TrackedItemStore.store_sku == store.store_sku
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Store mapping already exists"
        )
    
    # Add mapping
    db_store = TrackedItemStore(
        tracked_item_id=item_id,
        store_id=store.store_id,
        store_sku=store.store_sku,
        store_url=store.store_url,
        is_active=True
    )
    db.add(db_store)
    db.commit()
    
    return {
        "message": "Store mapping added successfully",
        "store_id": store.store_id
    }


# Add to main.py:
# from services.api.tracked_items_api import router as tracked_items_router
# app.include_router(tracked_items_router)
