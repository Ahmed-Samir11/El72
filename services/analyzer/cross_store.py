"""Cross-store price comparison for one canonical product."""

from __future__ import annotations

from statistics import mean
from typing import Mapping, Sequence


def _validated_prices(store_prices: Mapping[str, float]) -> dict[str, float]:
    if not store_prices:
        raise ValueError("store_prices must not be empty")
    prices = {str(store_id): float(price) for store_id, price in store_prices.items()}
    if any(not store_id or price <= 0 for store_id, price in prices.items()):
        raise ValueError("store_prices must contain positive prices and store IDs")
    return prices


def compare_store_prices(
    product_id: str,
    store_prices: Mapping[str, float],
    historical_prices_by_store: Mapping[str, Sequence[float]] | None = None,
) -> dict:
    """Compare current prices for one already-matched logical product."""
    if not product_id:
        raise ValueError("product_id must not be empty")
    prices = _validated_prices(store_prices)
    market_average = mean(prices.values())
    cheapest_store = min(prices, key=lambda store_id: (prices[store_id], store_id))
    most_expensive_store = min(
        prices, key=lambda store_id: (-prices[store_id], store_id)
    )
    market_minimum = prices[cheapest_store]
    market_maximum = prices[most_expensive_store]
    spread = market_maximum - market_minimum
    spread_percent = spread / market_average

    ranked_stores = sorted(prices.items(), key=lambda item: (item[1], item[0]))
    ranking = [
        {
            "store_id": store_id,
            "price": round(price, 2),
            "rank": rank,
            "difference_from_average": round((price - market_average) / market_average, 4),
            "is_cheapest": store_id == cheapest_store,
            "is_most_expensive": store_id == most_expensive_store,
        }
        for rank, (store_id, price) in enumerate(ranked_stores, start=1)
    ]

    historical_low = False
    historical_minimum = None
    store_historical_lows: dict[str, bool] = {}
    if historical_prices_by_store:
        all_history = []
        for store_id, history in historical_prices_by_store.items():
            values = [float(price) for price in history]
            if not values or any(price <= 0 for price in values):
                raise ValueError("historical prices must contain positive values")
            all_history.extend(values)
            if store_id in prices:
                store_historical_lows[store_id] = prices[store_id] <= min(values) * 1.005
        if all_history:
            historical_minimum = min(all_history)
            historical_low = market_minimum <= historical_minimum * 1.005

    if spread_percent >= 0.05:
        market_position = "meaningful_spread"
    elif market_minimum < market_average:
        market_position = "tight_spread"
    else:
        market_position = "no_spread"

    return {
        "product_id": product_id,
        "market_average": round(market_average, 2),
        "market_minimum": round(market_minimum, 2),
        "market_maximum": round(market_maximum, 2),
        "cheapest_store": cheapest_store,
        "most_expensive_store": most_expensive_store,
        "spread": round(spread, 2),
        "spread_percent": round(spread_percent, 4),
        "market_position": market_position,
        "is_historical_low": historical_low,
        "historical_minimum": round(historical_minimum, 2) if historical_minimum is not None else None,
        "store_historical_lows": store_historical_lows,
        "ranking": ranking,
    }
