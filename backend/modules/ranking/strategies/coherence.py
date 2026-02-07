"""
Set-coherence scoring — favour products from stores already in the cart.

Fewer unique retailers → fewer checkouts → better UX.
"""

from __future__ import annotations

from backend.models.product import Product
from backend.models.shopping import ShoppingSpec
from backend.modules.ranking.strategies.base import ScoringResult


class CoherenceScorer:
    name: str = "coherence"

    def __init__(self, weight: float = 0.30, cart_retailers: list[str] | None = None):
        self.weight = weight
        self.cart_retailers: list[str] = cart_retailers or []

    def update_cart_retailers(self, retailers: list[str]) -> None:
        self.cart_retailers = retailers

    def score(self, product: Product, spec: ShoppingSpec) -> ScoringResult:
        if not self.cart_retailers:
            return ScoringResult(score=0.5, reason="cart empty, neutral")

        if product.retailer in self.cart_retailers:
            return ScoringResult(
                score=1.0,
                reason=f"same store as existing cart items ({product.retailer})",
            )

        # Penalty proportional to how many extra stores we'd add
        unique_now = len(set(self.cart_retailers))
        s = max(0.0, 1.0 - 0.25 * unique_now)
        return ScoringResult(
            score=round(s, 2),
            reason=f"would add a new retailer (currently {unique_now} store(s))",
        )
