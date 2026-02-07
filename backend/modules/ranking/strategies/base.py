"""
ScoringStrategy protocol — one implementation per ranking dimension.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from backend.models.product import Product
from backend.models.shopping import ShoppingSpec


class ScoringResult(BaseModel):
    """Result of a single scoring dimension."""

    score: float  # 0.0 – 1.0 (higher is better)
    reason: str   # Human-readable explanation fragment


@runtime_checkable
class ScoringStrategy(Protocol):
    weight: float
    name: str

    def score(self, product: Product, spec: ShoppingSpec) -> ScoringResult:
        ...
