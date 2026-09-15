"""Explainable deal quality and suspicious-discount scoring."""

from __future__ import annotations

from statistics import mean, median, pstdev
from typing import Sequence

from services.analyzer.fake_discount import (
    _clamp,
    _validate_prices,
    detect_fake_discount,
)


def score_deal(
    current_price: float,
    historical_prices: Sequence[float],
    competitor_prices: Sequence[float] = (),
    advertised_reference_price: float | None = None,
    discount_duration_days: int = 0,
    recent_prices: Sequence[float] = (),
) -> dict:
    """Calculate a 0-100 explainable deal quality score.

    Components are historical discount (35), historical percentile (25),
    cross-store advantage (20), historical-low status (15), and duration (5).
    Suspicious-discount confidence applies a penalty of up to 30 points.
    """
    history = _validate_prices(historical_prices, "historical_prices")
    current = float(current_price)
    if current <= 0:
        raise ValueError("current_price must be positive")
    if discount_duration_days < 0:
        raise ValueError("discount_duration_days must not be negative")

    historical_median = median(history)
    historical_mean = mean(history)
    historical_minimum = min(history)
    historical_discount = max(0.0, (historical_median - current) / historical_median)
    historical_percentile = sum(price <= current for price in history) / len(history)
    historical_low = current <= historical_minimum * 1.005

    cross_store_average = None
    cross_store_advantage = 0.0
    if competitor_prices:
        competitors = _validate_prices(competitor_prices, "competitor_prices")
        cross_store_average = mean(competitors)
        cross_store_advantage = max(0.0, (cross_store_average - current) / cross_store_average)

    suspicious = detect_fake_discount(
        current,
        history,
        advertised_reference_price,
        competitor_prices,
        recent_prices,
    )
    duration_signal = _clamp(discount_duration_days / 7.0)
    raw_score = (
        35.0 * _clamp(historical_discount / 0.30)
        + 25.0 * _clamp(1.0 - historical_percentile)
        + 20.0 * _clamp(cross_store_advantage / 0.15)
        + (15.0 if historical_low else 0.0)
        + 5.0 * duration_signal
        - 30.0 * suspicious["confidence"]
    )
    score = int(round(_clamp(raw_score, 0.0, 100.0)))
    if score >= 80:
        grade = "Excellent"
    elif score >= 60:
        grade = "Good"
    elif score >= 40:
        grade = "Fair"
    elif score >= 20:
        grade = "Weak"
    else:
        grade = "No deal"

    reasons = [
        f"{historical_discount:.0%} below the historical median"
        if historical_discount > 0
        else "At or above the historical median",
        f"Current price is in the {historical_percentile:.0%} historical percentile",
    ]
    if historical_low:
        reasons.append("Lowest observed price in the historical window")
    if cross_store_average is not None:
        reasons.append(f"{cross_store_advantage:.0%} below the cross-store average")
    if discount_duration_days:
        reasons.append(f"Discount observed for {discount_duration_days} days")
    if suspicious["is_suspicious"]:
        reasons.append("Suspicious-discount signal reduced the score")

    return {
        "score": score,
        "grade": grade,
        "explanation": reasons,
        "signals": {
            "current_price": round(current, 2),
            "historical_median": round(historical_median, 2),
            "historical_mean": round(historical_mean, 2),
            "historical_minimum": round(historical_minimum, 2),
            "historical_percentile": round(historical_percentile, 4),
            "historical_discount": round(historical_discount, 4),
            "cross_store_average": round(cross_store_average, 2) if cross_store_average is not None else None,
            "cross_store_advantage": round(cross_store_advantage, 4),
            "price_volatility": round(pstdev(history) / historical_mean, 4),
            "discount_duration_days": discount_duration_days,
            "is_historical_low": historical_low,
            "suspicious_discount": suspicious,
        },
    }
