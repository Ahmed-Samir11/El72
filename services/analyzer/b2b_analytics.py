"""Focused B2B pricing intelligence calculations."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from statistics import mean, pstdev
from typing import Iterable, Mapping, Sequence


def _positive(value: float, name: str) -> float:
    value = float(value)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def competitor_position(
    store_id: str,
    product_prices: Mapping[str, float],
) -> dict:
    """Return a retailer's market position for one matched product."""
    if not store_id or store_id not in product_prices:
        raise ValueError("store_id must identify a supplied product price")
    prices = {store: _positive(price, "product price") for store, price in product_prices.items()}
    own_price = prices[store_id]
    market_average = mean(prices.values())
    market_minimum = min(prices.values())
    market_maximum = max(prices.values())
    rank = sorted(prices, key=lambda store: (prices[store], store)).index(store_id) + 1
    return {
        "store_id": store_id,
        "own_price": round(own_price, 2),
        "market_average": round(market_average, 2),
        "market_minimum": round(market_minimum, 2),
        "market_maximum": round(market_maximum, 2),
        "market_rank": rank,
        "store_count": len(prices),
        "price_gap_vs_average": round((own_price - market_average) / market_average, 4),
        "price_gap_vs_minimum": round((own_price - market_minimum) / market_minimum, 4),
        "is_market_minimum": own_price == market_minimum,
    }


def category_trends(observations: Iterable[Mapping]) -> list[dict]:
    """Aggregate category movement from timestamped price observations."""
    groups: dict[str, list[Mapping]] = defaultdict(list)
    for observation in observations:
        category = observation.get("category")
        if not category:
            raise ValueError("each observation requires a category")
        _positive(observation["price"], "price")
        if not isinstance(observation.get("timestamp"), datetime):
            raise ValueError("each observation requires a datetime timestamp")
        groups[category].append(observation)

    results = []
    for category, items in sorted(groups.items()):
        prices = [float(item["price"]) for item in items]
        by_product = defaultdict(list)
        for item in items:
            by_product[item["product_id"]].append(item)
        drops = increases = 0
        for product_items in by_product.values():
            ordered = sorted(product_items, key=lambda item: item["timestamp"])
            if len(ordered) < 2:
                continue
            first = float(ordered[0]["price"])
            last = float(ordered[-1]["price"])
            drops += last < first
            increases += last > first
        results.append({
            "category": category,
            "observation_count": len(items),
            "product_count": len(by_product),
            "average_price": round(mean(prices), 2),
            "price_volatility": round(pstdev(prices) / mean(prices), 4),
            "products_dropping": drops,
            "products_increasing": increases,
            "deal_density": round(sum(float(item.get("discount_percent", 0)) >= 15 for item in items) / len(items), 4),
        })
    return results


def store_movements(observations: Iterable[Mapping]) -> list[dict]:
    """Summarize price movement by store and product."""
    groups: dict[tuple[str, str], list[Mapping]] = defaultdict(list)
    for observation in observations:
        store_id = observation.get("store_id")
        product_id = observation.get("product_id")
        if not store_id or not product_id:
            raise ValueError("each observation requires store_id and product_id")
        _positive(observation["price"], "price")
        groups[(store_id, product_id)].append(observation)

    movements = []
    for (store_id, product_id), items in sorted(groups.items()):
        ordered = sorted(items, key=lambda item: item["timestamp"])
        first = float(ordered[0]["price"])
        last = float(ordered[-1]["price"])
        change = (last - first) / first
        movements.append({
            "store_id": store_id,
            "product_id": product_id,
            "first_price": round(first, 2),
            "last_price": round(last, 2),
            "change_percent": round(change, 4),
            "direction": "down" if change < -0.001 else "up" if change > 0.001 else "stable",
        })
    return movements


def opportunity_signals(
    competitor_positions: Sequence[Mapping],
    historical_low_count: int = 0,
    volatile_product_count: int = 0,
) -> dict:
    """Summarize retailer-facing opportunities from computed signals."""
    above_market = sum(float(item.get("price_gap_vs_average", 0)) > 0.10 for item in competitor_positions)
    return {
        "products_above_market_10_percent": above_market,
        "products_at_historical_lows": max(0, int(historical_low_count)),
        "products_with_high_volatility": max(0, int(volatile_product_count)),
        "total_products": len(competitor_positions),
    }
