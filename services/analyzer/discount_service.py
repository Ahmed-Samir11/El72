"""Service layer for the fake-discount detector.

Wraps the pure :func:`services.analyzer.fake_discount.detect_fake_discount`
with a human-readable ``stats`` block and a plain-English ``summary`` so the
API can return something like:

    "The product has typically sold for ~1,200–1,250. The current
     1,180 price is only ~2–6% below its normal price."

(Prices are in the market's local currency — EGP for the tracked stores.)

The core detection math is NOT duplicated here — it lives in
``fake_discount.py`` and is unchanged. This module only formats.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .discount_data import DiscountInputs, load_discount_inputs
from .fake_discount import detect_fake_discount


def _pct_below(normal: float, current: float) -> Optional[float]:
    """Percent the current price is below ``normal`` (positive = cheaper)."""
    if not normal:
        return None
    return round((normal - current) / normal * 100.0, 1)


def _typical_range(median_30d: Optional[float], median_90d: Optional[float]):
    """Return (low, high) of the two medians, or None if neither exists."""
    values = [v for v in (median_30d, median_90d) if v is not None]
    if not values:
        return None
    return (min(values), max(values))


def _build_summary(inputs: DiscountInputs, detection: Dict[str, Any]) -> str:
    """Compose the plain-English verdict shown to the user."""
    if inputs.status != "ok":
        return (
            f"Not enough price history yet ({inputs.point_count} points). "
            "The detector needs at least a couple of weeks of data to judge "
            "whether a discount is genuine."
        )

    current = inputs.current_price
    low, high = _typical_range(inputs.median_30d, inputs.median_90d) or (None, None)

    if low is None or high is None or current is None:
        return "Insufficient price data to assess this discount."

    # Range of "how far below normal" across the 30d and 90d medians.
    # "How far below normal" across the 30d and 90d medians. Only positive
    # values mean "below"; a non-positive gap means the current price is at
    # or above normal, which needs its own wording (review finding: the
    # summary could render nonsensical negative percentages).
    below_all = [
        p
        for p in (
            _pct_below(inputs.median_30d, current),
            _pct_below(inputs.median_90d, current),
        )
        if p is not None
    ]
    below = [p for p in below_all if p > 0]
    at_or_above = bool(below_all) and not below
    below_lo = min(below) if below else None
    below_hi = max(below) if below else None

    typical = f"~{low:,.0f}–{high:,.0f}" if low != high else f"~{low:,.0f}"

    if detection.get("is_suspicious"):
        if at_or_above:
            return (
                f"The product has typically sold for {typical}. The current "
                f"{current:,.0f} price is at or above its normal price, "
                "which is not a real deal."
            )
        if below_lo is not None and below_hi is not None:
            spread = (
                f"only ~{below_lo:.0f}–{below_hi:.0f}% below its normal price"
                if below_lo != below_hi
                else f"only ~{below_lo:.0f}% below its normal price"
            )
            return (
                f"The product has typically sold for {typical}. The current "
                f"{current:,.0f} price is {spread}, which is not a real deal."
            )
        return (
            f"The product has typically sold for {typical}, so the current "
            f"{current:,.0f} price is not a genuine discount."
        )

    # Not suspicious — describe the genuine discount.
    if below_lo is not None and below_hi is not None:
        spread = (
            f"~{below_lo:.0f}–{below_hi:.0f}% below its normal price"
            if below_lo != below_hi
            else f"~{below_lo:.0f}% below its normal price"
        )
        return (
            f"The product has typically sold for {typical}. The current "
            f"{current:,.0f} price is {spread} — a genuine discount."
        )
    return (
        f"The product has typically sold for {typical}. The current "
        f"{current:,.0f} price looks like a genuine discount."
    )


def analyze_discount(inputs: DiscountInputs) -> Dict[str, Any]:
    """Run detection on pre-loaded inputs and attach human-readable stats.

    Pure function — no I/O — so it is trivially unit-testable.
    """
    if inputs.status != "ok":
        return {
            "sku": inputs.sku,
            "store_id": inputs.store_id,
            "status": inputs.status,
            "is_suspicious": False,
            "confidence": 0.0,
            "reasons": [],
            "signals": {},
            "stats": _stats_block(inputs),
            "summary": _build_summary(inputs, {}),
        }

    detection = detect_fake_discount(
        current_price=inputs.current_price,
        historical_prices=inputs.historical_prices,
        advertised_reference_price=inputs.advertised_reference_price,
        competitor_prices=inputs.competitor_prices,
        recent_prices=inputs.recent_prices,
    )

    return {
        "sku": inputs.sku,
        "store_id": inputs.store_id,
        "status": inputs.status,
        "is_suspicious": detection.get("is_suspicious", False),
        "confidence": detection.get("confidence", 0.0),
        "reasons": detection.get("reasons", []),
        "signals": detection.get("signals", {}),
        "stats": _stats_block(inputs),
        "summary": _build_summary(inputs, detection),
    }


def _stats_block(inputs: DiscountInputs) -> Dict[str, Any]:
    low, high = _typical_range(inputs.median_30d, inputs.median_90d) or (None, None)
    return {
        "current_price": inputs.current_price,
        "median_30d": inputs.median_30d,
        "median_90d": inputs.median_90d,
        "historical_low": inputs.historical_low,
        "advertised_reference_price": inputs.advertised_reference_price,
        "reference_source": (
            "advertised" if inputs.advertised_reference_price is not None else "none"
        ),
        "competitor_prices": inputs.competitor_prices,
        "typical_range": [low, high],
        "point_count": inputs.point_count,
    }


async def analyze_discount_for_sku(
    conn: Any,
    sku: str,
    store_id: Optional[str] = None,
    **load_kwargs: Any,
) -> Dict[str, Any]:
    """Load inputs from the DB and run detection. Thin async wrapper."""
    inputs = await load_discount_inputs(conn, sku, store_id, **load_kwargs)
    return analyze_discount(inputs)
