"""
Cart Manager — CRUD operations on the combined cart.
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.models.product import Product
from backend.models.shopping import Cart, CartItem

logger = logging.getLogger(__name__)


class CartManager:
    """
    Operates on a Cart instance (owned by a session).
    All mutations return the updated Cart for convenience.
    """

    def __init__(self, cart: Cart) -> None:
        self.cart = cart

    # ------------------------------------------------------------------
    def add(self, product: Product, quantity: int = 1) -> Cart:
        """Add a product (or increase qty if already in cart)."""
        for item in self.cart.items:
            if item.product_id == product.id:
                item.quantity += quantity
                return self.cart

        self.cart.items.append(
            CartItem(
                product_id=product.id,
                name=product.name,
                price=product.price,
                currency=product.currency,
                price_usd=product.price_usd,
                quantity=quantity,
                retailer=product.retailer,
                image_url=product.image_url,
                product_url=product.product_url,
                delivery_days=product.delivery_days,
                category=product.category,
            )
        )
        return self.cart

    # ------------------------------------------------------------------
    def remove(self, product_id: str) -> Cart:
        """Remove an item entirely from the cart."""
        self.cart.items = [i for i in self.cart.items if i.product_id != product_id]
        return self.cart

    # ------------------------------------------------------------------
    def update_quantity(self, product_id: str, quantity: int) -> Cart:
        """Set the quantity for an existing item."""
        for item in self.cart.items:
            if item.product_id == product_id:
                if quantity <= 0:
                    return self.remove(product_id)
                item.quantity = quantity
                return self.cart
        return self.cart

    # ------------------------------------------------------------------
    def swap(self, old_product_id: str, new_product: Product, quantity: int = 1) -> Cart:
        """Replace one item with another."""
        self.remove(old_product_id)
        return self.add(new_product, quantity)

    # ------------------------------------------------------------------
    def clear(self) -> Cart:
        self.cart.items.clear()
        return self.cart

    # ------------------------------------------------------------------
    def find_product_in_results(
        self,
        product_id: str,
        search_results: dict[str, list[Product]],
    ) -> Optional[Product]:
        """Look up a Product by id across all search result categories."""
        for products in search_results.values():
            for p in products:
                if p.id == product_id:
                    return p
        return None
