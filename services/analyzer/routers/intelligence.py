"""Validated API routes for analyzer intelligence calculations."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, validator

from services.analyzer.b2b_analytics import (
    category_trends,
    store_movements,
)
from services.analyzer.cross_store import compare_store_prices
from services.analyzer.deal_scorer import score_deal
from services.analyzer.discount_service import analyze_discount_for_sku
from services.analyzer.fake_discount import detect_fake_discount
from services.analyzer.platform_metrics import platform_metrics

router = APIRouter(tags=["intelligence"])
logger = logging.getLogger(__name__)


class DealScoreRequest(BaseModel):
    current_price: float = Field(..., gt=0)
    historical_prices: List[float] = Field(..., min_items=1)
    competitor_prices: List[float] = Field(default_factory=list)
    advertised_reference_price: Optional[float] = Field(default=None, gt=0)
    discount_duration_days: int = Field(default=0, ge=0)
    recent_prices: List[float] = Field(default_factory=list)


class FakeDiscountRequest(BaseModel):
    current_price: float = Field(..., gt=0)
    historical_prices: List[float] = Field(..., min_items=1)
    advertised_reference_price: Optional[float] = Field(default=None, gt=0)
    competitor_prices: List[float] = Field(default_factory=list)
    recent_prices: List[float] = Field(default_factory=list)


class CrossStoreRequest(BaseModel):
    store_prices: Dict[str, float]
    historical_prices_by_store: Dict[str, List[float]] = Field(default_factory=dict)

    @validator("store_prices")
    def store_prices_required(cls, prices):
        if not prices:
            raise ValueError("store_prices must not be empty")
        return prices


class Observation(BaseModel):
    product_id: str
    category: Optional[str] = None
    store_id: str
    timestamp: datetime
    price: float = Field(..., gt=0)
    discount_percent: float = Field(default=0, ge=0)
    change_percent: Optional[float] = None


class CategoryTrendRequest(BaseModel):
    observations: List[Observation] = Field(..., min_items=1)

    @validator("observations")
    def categories_required(cls, observations):
        if any(not item.category for item in observations):
            raise ValueError("category is required for category trends")
        return observations


class StoreMovementRequest(BaseModel):
    observations: List[Observation] = Field(..., min_items=1)


class ProductRecord(BaseModel):
    product_id: str
    category: Optional[str] = None


class MetricRecord(BaseModel):
    product_id: Optional[str] = None
    store_id: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = Field(default=None, gt=0)
    timestamp: Optional[datetime] = None
    change_percent: Optional[float] = None
    is_historical_low: Optional[bool] = None
    is_suspicious: Optional[bool] = None


class PlatformMetricsRequest(BaseModel):
    products: List[ProductRecord] = Field(default_factory=list)
    observations: List[MetricRecord] = Field(default_factory=list)
    deals: List[MetricRecord] = Field(default_factory=list)
    suspicious_discounts: List[MetricRecord] = Field(default_factory=list)
    as_of: Optional[date] = None


@router.post("/intelligence/deal-score")
async def deal_score(request: DealScoreRequest):
    return score_deal(**request.dict())


@router.post("/intelligence/fake-discount")
async def fake_discount(request: FakeDiscountRequest):
    return detect_fake_discount(**request.dict())


@router.get("/intelligence/fake-discount/{sku}")
async def fake_discount_for_sku(
    sku: str, request: Request, store_id: Optional[str] = None
):
    """DB-backed fake-discount verdict for a product.

    Loads the 90-day price history for ``sku`` (optionally scoped to one
    ``store_id``) and runs the detector. Returns ``status:
    "insufficient_history"`` (not an error) when there isn't enough data yet.
    """
    ts_pool = getattr(request.app.state, "ts_pool", None)
    if ts_pool is None:
        raise HTTPException(
            status_code=503,
            detail="Price history store is not available.",
        )
    try:
        async with ts_pool.acquire() as conn:
            return await analyze_discount_for_sku(conn, sku, store_id)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - surface a clean 500, not a stack trace
        # Log the full error server-side; return a generic detail so internal
        # exception text (SQL, connection strings) never reaches the client.
        logger.exception("Failed to analyze discount for %s", sku)
        raise HTTPException(
            status_code=500,
            detail="Failed to analyze discount for this product.",
        ) from None


@router.post("/intelligence/cross-store/{product_id}")
async def cross_store(product_id: str, request: CrossStoreRequest):
    return compare_store_prices(
        product_id,
        request.store_prices,
        request.historical_prices_by_store,
    )


@router.post("/analytics/category-trends")
async def category_trends_endpoint(request: CategoryTrendRequest):
    return {
        "categories": category_trends([item.dict() for item in request.observations])
    }


@router.post("/analytics/store-movements")
async def store_movements_endpoint(request: StoreMovementRequest):
    return {
        "movements": store_movements([item.dict() for item in request.observations])
    }


@router.post("/metrics/platform")
async def platform_metrics_endpoint(request: PlatformMetricsRequest):
    return platform_metrics(
        [item.dict() for item in request.products],
        [item.dict() for item in request.observations],
        [item.dict() for item in request.deals],
        [item.dict() for item in request.suspicious_discounts],
        request.as_of,
    )
