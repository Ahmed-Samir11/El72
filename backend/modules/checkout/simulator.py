"""
Checkout Simulator — generates a step-by-step simulated
checkout plan across multiple retailers.
"""

from __future__ import annotations

from backend.models.shopping import Cart, CheckoutPlan, CheckoutStep


class CheckoutSimulator:
    """Build a multi-retailer checkout plan from a Cart."""

    @staticmethod
    def simulate(cart: Cart) -> CheckoutPlan:
        if not cart.items:
            return CheckoutPlan(session_id=cart.session_id)

        by_store: dict[str, list] = {}
        for item in cart.items:
            by_store.setdefault(item.retailer, []).append(item)

        steps: list[CheckoutStep] = []
        step_num = 1

        # Step 1 — shared: enter address
        steps.append(
            CheckoutStep(
                step=step_num,
                retailer="all",
                action="Enter shipping address (entered once, shared across stores)",
                status="pending",
            )
        )
        step_num += 1

        # Step 2 — shared: enter payment
        steps.append(
            CheckoutStep(
                step=step_num,
                retailer="all",
                action="Enter payment details (entered once, shared across stores)",
                status="pending",
            )
        )
        step_num += 1

        # Per-retailer checkout steps
        max_delivery = 0
        for retailer, items in by_store.items():
            subtotal = sum(i.price_usd * i.quantity for i in items)
            item_names = [f"{i.name} ×{i.quantity}" for i in items]
            delivery = max((i.delivery_days or 5) for i in items)
            max_delivery = max(max_delivery, delivery)

            steps.append(
                CheckoutStep(
                    step=step_num,
                    retailer=retailer,
                    action=f"Place order on {retailer} — {len(items)} item(s)",
                    items=item_names,
                    subtotal_usd=round(subtotal, 2),
                    status="pending",
                )
            )
            step_num += 1

        # Final confirmation step
        steps.append(
            CheckoutStep(
                step=step_num,
                retailer="all",
                action="All orders placed! Confirmation emails sent.",
                status="pending",
            )
        )

        return CheckoutPlan(
            session_id=cart.session_id,
            steps=steps,
            total_usd=round(cart.total_usd, 2),
            estimated_delivery=f"~{max_delivery} business days",
        )
