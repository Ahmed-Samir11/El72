"""Suspicious or potentially misleading discount detection."""

from __future__ import annotations

from statistics import mean, median
from typing import Iterable, Sequence


def _validate_prices(prices: Iterable[float], name: str) -> list[float]:
    values = [float(price) for price in prices]
    if not values or any(price <= 0 for price in values):
        raise ValueError(f"{name} must contain positive prices")
    return values


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def detect_fake_discount(
    current_price: float,
    historical_prices: Sequence[float],
    advertised_reference_price: float | None = None,
    competitor_prices: Sequence[float] = (),
    recent_prices: Sequence[float] = (),
) -> dict:
    """Return a suspicious-discount signal, never a legal fraud determination."""
    history = _validate_prices(historical_prices, "historical_prices")
    current = float(current_price)
    if current <= 0:
        raise ValueError("current_price must be positive")

    historical_median = median(history)
    reference_gap = 0.0
    if advertised_reference_price is not None:
        reference = float(advertised_reference_price)
        if reference <= 0:
            raise ValueError("advertised_reference_price must be positive")
        reference_gap = max(0.0, (reference - historical_median) / historical_median)

    actual_discount = max(0.0, (historical_median - current) / historical_median)
    historical_low = current <= min(history) * 1.005
    competitor_advantage = 0.0
    if competitor_prices:
        competitors = _validate_prices(competitor_prices, "competitor_prices")
        competitor_average = mean(competitors)
        competitor_advantage = max(0.0, (current - competitor_average) / competitor_average)
    recent_inflation = 0.0
    if recent_prices:
        recent_inflation = max(
            0.0,
            (max(_validate_prices(recent_prices, "recent_prices")) - historical_median)
            / historical_median,
        )

    confidence = 0.0
    reasons: list[str] = []
    if reference_gap >= 0.10:
        confidence += 0.50 * _clamp(reference_gap / 0.20)
        reasons.append(f"Reference price is {reference_gap:.0%} above the historical median")
    if reference_gap >= 0.10 and actual_discount < 0.08:
        confidence += 0.30
        reasons.append(f"Current price is only {actual_discount:.0%} below the historical median")
    if competitor_advantage >= 0.03:
        confidence += 0.20 * _clamp(competitor_advantage / 0.15)
        reasons.append("Competitors offer a lower average price")
    if recent_inflation >= 0.10:
        confidence += 0.25 * _clamp(recent_inflation / 0.20)
        reasons.append(f"Recent price peaked {recent_inflation:.0%} above the historical median")
    if reference_gap >= 0.10 and not historical_low:
        confidence += 0.20
        reasons.append("Current price is not near the historical low")

    confidence = round(_clamp(confidence), 3)
    return {
        "is_suspicious": confidence >= 0.50,
        "confidence": confidence,
        "reasons": reasons,
        "signals": {
            "historical_median": round(historical_median, 2),
            "actual_discount": round(actual_discount, 4),
            "reference_gap": round(reference_gap, 4),
            "competitor_advantage": round(competitor_advantage, 4),
            "recent_inflation": round(recent_inflation, 4),
            "is_historical_low": historical_low,
        },
    }
