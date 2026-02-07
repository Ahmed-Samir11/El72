"""
RetailerAdapter protocol — one implementation per store.

Adding a new store = create one file that implements this protocol.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from backend.models.product import CrawledProduct, Product


@runtime_checkable
class RetailerAdapter(Protocol):
    """Plug-in interface for each retailer."""

    name: str
    base_url: str

    def build_search_url(self, query: str) -> str:
        """Return a full search-results URL for *query*."""
        ...

    def get_product_schema(self) -> type[BaseModel]:
        """Return the Pydantic schema the LLM should extract to."""
        ...

    def normalize(self, raw: dict, category: str = "") -> Product:
        """Convert a raw crawled dict into the unified Product model."""
        ...


# ---------- Shared currency helpers ----------

# Very rough static rates (good enough for a 24-h demo)
_TO_USD: dict[str, float] = {
    "USD": 1.0,
    "EGP": 0.020,  # ~50 EGP = 1 USD
    "EUR": 1.08,
    "AED": 0.27,
    "SAR": 0.27,
    "GBP": 1.26,
}


def to_usd(amount: float, currency: str) -> float:
    rate = _TO_USD.get(currency.upper(), 1.0)
    return round(amount * rate, 2)


def _parse_delivery_days(text: str | None) -> int | None:
    """Best-effort parse of delivery text into number of days."""
    if not text:
        return None
    import re

    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None
