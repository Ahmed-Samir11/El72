# Cross-Store Intelligence

`services/analyzer/cross_store.py` compares prices for one already-matched logical product. It uses the repository's existing product identity, `canonical_product_id`; it does not introduce a second product-matching system.

`compare_store_prices` returns:

- Cheapest and most expensive store
- Market minimum, maximum, and average
- Absolute and percentage spread
- Deterministic store ranking
- Difference from market average for each store
- Market-wide historical-low status
- Store-specific historical-low status when histories are supplied

Historical lows are intentionally separated:

- `is_historical_low` means the current market minimum is near the minimum across all supplied store histories.
- `store_historical_lows` reports whether each individual store's current price is near its own historical minimum.

Store ties are resolved by store ID so API output does not depend on dictionary insertion order.
