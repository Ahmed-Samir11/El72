"""
Ranking Engine — combines scoring strategies to produce an
explainable ranking for a list of products.
"""

from __future__ import annotations

import logging
from typing import Sequence

from backend.config import get_settings
from backend.models.product import Product
from backend.models.shopping import ShoppingSpec
from backend.modules.ranking.strategies.base import ScoringStrategy, ScoringResult
from backend.modules.ranking.strategies.cost import CostScorer
from backend.modules.ranking.strategies.delivery import DeliveryScorer
from backend.modules.ranking.strategies.coherence import CoherenceScorer

logger = logging.getLogger(__name__)


class RankingEngine:
    """
    Composes multiple ScoringStrategy instances and produces a
    weighted total score + human-readable explanation per product.
    """

    def __init__(self, cart_retailers: list[str] | None = None) -> None:
        s = get_settings()
        self.strategies: list[ScoringStrategy] = [
            CostScorer(weight=s.ranking_weight_cost),
            DeliveryScorer(weight=s.ranking_weight_delivery),
            CoherenceScorer(weight=s.ranking_weight_coherence, cart_retailers=cart_retailers or []),
        ]

    def update_cart_retailers(self, retailers: list[str]) -> None:
        for strat in self.strategies:
            if hasattr(strat, "update_cart_retailers"):
                strat.update_cart_retailers(retailers)

    # ------------------------------------------------------------------
    def rank(
        self,
        products: list[Product],
        spec: ShoppingSpec,
    ) -> list[Product]:
        """
        Score, sort, and annotate every product.

        Returns products sorted best-first with rank_score and
        rank_explanation filled in.
        """
        for product in products:
            total = 0.0
            explanations: list[str] = []

            for strat in self.strategies:
                result: ScoringResult = strat.score(product, spec)
                weighted = result.score * strat.weight
                total += weighted
                explanations.append(f"{strat.name}: {result.reason} ({result.score:.1f}×{strat.weight:.1f})")

            product.rank_score = round(total, 3)
            product.rank_explanation = "; ".join(explanations)

        products.sort(key=lambda p: p.rank_score, reverse=True)

        # Stamp rank positions
        for i, p in enumerate(products, 1):
            p.rank_explanation = f"Rank #{i} — " + p.rank_explanation

        return products

    # ------------------------------------------------------------------
    def explain(self, product: Product, spec: ShoppingSpec) -> str:
        """Return a verbose ranking explanation for one product."""
        lines = [f"**{product.name}** (${product.price_usd:.2f} from {product.retailer})"]
        total = 0.0

        for strat in self.strategies:
            result = strat.score(product, spec)
            weighted = result.score * strat.weight
            total += weighted
            lines.append(f"  • {strat.name} ({strat.weight:.0%}): {result.reason} → {result.score:.2f}")

        lines.append(f"  **Total score: {total:.3f}**")
        return "\n".join(lines)
