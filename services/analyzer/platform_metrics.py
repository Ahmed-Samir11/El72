"""Data-backed platform and investor metrics."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Iterable, Mapping


def platform_metrics(
    products: Iterable[Mapping],
    observations: Iterable[Mapping],
    deals: Iterable[Mapping] = (),
    suspicious_discounts: Iterable[Mapping] = (),
    as_of: date | None = None,
) -> dict:
    """Calculate bounded platform metrics from supplied records."""
    product_rows = list(products)
    observation_rows = list(observations)
    deal_rows = list(deals)
    suspicious_rows = list(suspicious_discounts)
    dates = [
        row["timestamp"].date()
        for row in observation_rows
        if isinstance(row.get("timestamp"), datetime)
    ]
    stores = {row.get("store_id") for row in observation_rows if row.get("store_id")}
    categories = {row.get("category") for row in product_rows if row.get("category")}
    coverage_days = (max(dates) - min(dates)).days + 1 if dates else 0
    reference_day = as_of or (max(dates) if dates else None)
    week_start = reference_day - timedelta(days=6) if reference_day else None
    weekly_observations = sum(
        row.get("timestamp").date() >= week_start
        for row in observation_rows
        if week_start and isinstance(row.get("timestamp"), datetime)
    )
    weekly_deals = sum(
        row.get("timestamp").date() >= week_start
        for row in deal_rows
        if week_start and isinstance(row.get("timestamp"), datetime)
    )
    weekly_suspicious = sum(
        row.get("timestamp").date() >= week_start
        for row in suspicious_rows
        if week_start and isinstance(row.get("timestamp"), datetime)
    )
    prices = [float(row["price"]) for row in observation_rows if row.get("price") is not None]
    average_price_change = mean(
        float(row["change_percent"]) for row in observation_rows if row.get("change_percent") is not None
    ) if any(row.get("change_percent") is not None for row in observation_rows) else 0.0
    return {
        "products_tracked": len({row.get("product_id") for row in product_rows if row.get("product_id")}),
        "stores_tracked": len(stores),
        "price_observations": len(observation_rows),
        "days_of_historical_coverage": coverage_days,
        "categories_tracked": len(categories),
        "deals_detected": len(deal_rows),
        "historical_lows_detected": sum(bool(row.get("is_historical_low")) for row in deal_rows),
        "suspicious_discounts_detected": sum(bool(row.get("is_suspicious", True)) for row in suspicious_rows),
        "average_price_change": round(average_price_change, 4),
        "average_observed_price": round(mean(prices), 2) if prices else 0.0,
        "weekly": {
            "price_observations": weekly_observations,
            "deals_detected": weekly_deals,
            "suspicious_discounts_detected": weekly_suspicious,
        },
    }
