# Platform Metrics

`services/analyzer/platform_metrics.py` calculates investor-facing metrics from actual supplied records. It does not contain hardcoded demo values and returns zeroed metrics for empty datasets.

Reported totals include:

- Products tracked
- Stores tracked
- Price observations
- Days of historical coverage
- Categories tracked
- Deals detected
- Historical lows detected
- Suspicious discounts detected
- Average price movement
- Average observed price

The `weekly` section counts observations, deals, and suspicious discounts in the seven-day window ending on the explicit `as_of` date. When `as_of` is omitted, the latest observation date is used. This makes the output deterministic for historical/demo datasets and suitable for a later database-backed API adapter.
