"""
Jumia adapter — jumia.com.eg / jumia.com.ng etc.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from pydantic import BaseModel

from backend.models.product import CrawledProduct, Product
from backend.modules.crawler.adapters.base import RetailerAdapter, to_usd, _parse_delivery_days


class JumiaAdapter:
    """RetailerAdapter for Jumia Egypt."""

    name: str = "Jumia"
    base_url: str = "https://www.jumia.com.eg"

    def build_search_url(self, query: str) -> str:
        return f"{self.base_url}/catalog/?q={quote_plus(query)}"

    def get_product_schema(self) -> type[BaseModel]:
        return CrawledProduct

    def normalize(self, raw: dict, category: str = "") -> Product:
        cp = CrawledProduct.model_validate(raw)
        return Product(
            name=cp.name,
            price=cp.price,
            currency=cp.currency,
            price_usd=to_usd(cp.price, cp.currency),
            image_url=cp.image_url,
            product_url=cp.product_url,
            retailer=self.name,
            delivery_days=_parse_delivery_days(cp.delivery_estimate),
            rating=cp.rating,
            review_count=cp.review_count,
            in_stock=cp.in_stock,
            category=category,
            variants=cp.variants,
        )
