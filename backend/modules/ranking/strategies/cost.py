"""
Cost scoring — cheaper relative to budget is better.
"""

from __future__ import annotations

from backend.models.product import Product
from backend.models.shopping import ShoppingSpec
from backend.modules.ranking.strategies.base import ScoringResult


class CostScorer:
    name: str = "cost"

    def __init__(self, weight: float = 0.40):
        self.weight = weight

    def score(self, product: Product, spec: ShoppingSpec) -> ScoringResult:
        if spec.budget_usd <= 0:
            return ScoringResult(score=0.5, reason="no budget set")

        ratio = product.price_usd / spec.budget_usd
        # Under 20% of budget → perfect score; over 50% → bad
        if ratio <= 0.05:
            s = 1.0
        elif ratio <= 0.20:
            s = 0.9
        elif ratio <= 0.35:
            s = 0.7
        elif ratio <= 0.50:
            s = 0.4
        else:
            s = max(0.0, 1.0 - ratio)

        return ScoringResult(
            score=round(s, 2),
            reason=f"${product.price_usd:.0f} is {ratio*100:.0f}% of ${spec.budget_usd:.0f} budget",
        )
