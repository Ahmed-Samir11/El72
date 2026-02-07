"""
Product models — unified representation of products across all retailers.
"""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field


class CrawledProduct(BaseModel):
    """Raw product data as extracted by the crawler (per-store schema)."""

    name: str
    price: float
    currency: str = "USD"
    image_url: Optional[str] = None
    product_url: str = ""
    delivery_estimate: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    in_stock: bool = True
    variants: list[str] = Field(default_factory=list)


class Product(BaseModel):
    """Normalised product used throughout the application."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    price: float
    currency: str = "USD"
    price_usd: float = 0.0
    image_url: Optional[str] = None
    product_url: str = ""
    retailer: str = ""
    delivery_days: Optional[int] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    in_stock: bool = True
    category: str = ""
    variants: list[str] = Field(default_factory=list)

    # Ranking metadata (filled by the ranking engine)
    rank_score: float = 0.0
    rank_explanation: str = ""
