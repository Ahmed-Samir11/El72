# B2B Intelligence

`services/analyzer/b2b_analytics.py` contains focused retailer intelligence calculations over existing price observations. It does not create a second database model or product-matching system.

## Retailer positioning

`competitor_position(store_id, product_prices)` returns:

- Retailer price
- Market average, minimum, and maximum
- Market rank
- Percentage gap versus market average and minimum
- Whether the retailer has the market minimum

## Category trends

`category_trends(observations)` aggregates timestamped observations by category and reports:

- Observation and product counts
- Average price
- Normalized price volatility
- Products whose latest price dropped or increased versus their first observation
- Deal density based on observations with a supplied discount of at least 15%

## Competitor movement

`store_movements(observations)` reports first price, latest price, percentage change, and direction for each store/product pair.

## Opportunity signals

`opportunity_signals` combines computed retailer positions with historical-low and high-volatility counts. It reports actual counts for products priced more than 10% above market, products at historical lows, and volatile products.

The module accepts plain mappings so a later adapter can query PostgreSQL/TimescaleDB efficiently and pass bounded results into these calculations.
