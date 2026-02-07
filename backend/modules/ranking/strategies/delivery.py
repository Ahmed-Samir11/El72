"""
Delivery scoring — on-time relative to deadline is better.
"""

from __future__ import annotations

from backend.models.product import Product
from backend.models.shopping import ShoppingSpec
from backend.modules.ranking.strategies.base import ScoringResult


class DeliveryScorer:
    name: str = "delivery"

    def __init__(self, weight: float = 0.30):
        self.weight = weight

    def score(self, product: Product, spec: ShoppingSpec) -> ScoringResult:
        if product.delivery_days is None:
            return ScoringResult(score=0.5, reason="delivery unknown")

        if spec.deadline_days <= 0:
            return ScoringResult(score=0.5, reason="no deadline set")

        margin = spec.deadline_days - product.delivery_days
        if margin >= 2:
            s = 1.0
            reason = f"arrives {margin} days early"
        elif margin >= 0:
            s = 0.8
            reason = "arrives just in time"
        elif margin >= -1:
            s = 0.3
            reason = "arrives 1 day late"
        else:
            s = 0.0
            reason = f"arrives {abs(margin)} days late"

        return ScoringResult(score=round(s, 2), reason=reason)
