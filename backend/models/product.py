"""
Product models — unified representation of products across all retailers.
"""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field


class CrawledProduct(BaseModel):
    """Raw product data as extracted by the crawler (per-store schema)."""

    name: str = Field(..., description="Full product title")
    price: float = Field(..., description="Numeric price (no currency symbol)")
    currency: str = Field("USD", description="Currency code: USD, EGP, AED, etc.")
    image_url: Optional[str] = Field(None, description="Not used — always null")
    product_url: str = Field("", description="Absolute URL to the product detail page")
    delivery_estimate: Optional[str] = Field(
        None,
        description="Delivery time text, e.g. 'Delivers in 3-5 days', 'Free delivery by Friday', 'Ships in 2 days'. Extract exactly as shown on page.",
    )
    rating: Optional[float] = Field(None, description="Star rating, e.g. 4.5")
    review_count: Optional[int] = Field(None, description="Number of reviews")
    in_stock: bool = Field(True, description="Whether the product is available for purchase")
    variants: list[str] = Field(
        default_factory=list,
        description="Product variants visible on the listing: sizes, colors, pack counts, etc. E.g. ['Pack of 12', 'Pack of 24'] or ['Red', 'Blue', 'Black']",
    )


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
