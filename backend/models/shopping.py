"""
Shopping-session models — spec, cart, checkout plan.
"""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field


class ShoppingSpec(BaseModel):
    """Structured shopping specification captured from the user."""

    event_type: str = ""
    headcount: int = 0
    budget_usd: float = 500.0
    deadline_days: int = 5
    categories: list[str] = Field(default_factory=list)
    preferences: dict[str, str] = Field(default_factory=dict)


class CartItem(BaseModel):
    """A single item in the combined cart."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    product_id: str
    name: str
    price: float
    currency: str = "USD"
    price_usd: float = 0.0
    quantity: int = 1
    retailer: str = ""
    image_url: Optional[str] = None
    product_url: str = ""
    delivery_days: Optional[int] = None
    category: str = ""


class Cart(BaseModel):
    """Combined cart spanning multiple retailers."""

    session_id: str = ""
    items: list[CartItem] = Field(default_factory=list)
    budget_usd: float = 500.0

    # Computed helpers
    @property
    def total_usd(self) -> float:
        return sum(i.price_usd * i.quantity for i in self.items)

    @property
    def remaining_budget(self) -> float:
        return self.budget_usd - self.total_usd

    @property
    def retailers(self) -> list[str]:
        return list({i.retailer for i in self.items})

    def to_summary(self) -> dict:
        by_store: dict[str, list[dict]] = {}
        for item in self.items:
            by_store.setdefault(item.retailer, []).append(item.model_dump())
        return {
            "session_id": self.session_id,
            "items_count": len(self.items),
            "total_usd": round(self.total_usd, 2),
            "budget_usd": self.budget_usd,
            "remaining_budget_usd": round(self.remaining_budget, 2),
            "retailers": self.retailers,
            "items_by_store": by_store,
        }


class CheckoutStep(BaseModel):
    """One step in the simulated checkout flow."""

    step: int
    retailer: str
    action: str
    items: list[str] = Field(default_factory=list)
    subtotal_usd: float = 0.0
    status: str = "pending"


class CheckoutPlan(BaseModel):
    """Full simulated checkout plan across retailers."""

    session_id: str = ""
    steps: list[CheckoutStep] = Field(default_factory=list)
    total_usd: float = 0.0
    estimated_delivery: str = ""
