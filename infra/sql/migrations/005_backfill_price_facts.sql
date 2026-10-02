-- Backfill the analytical dimensions and price fact from preserved TimescaleDB
-- observations. The NOT EXISTS predicate makes this safe to rerun.
INSERT INTO analytics.dim_product (source_product_id, name)
SELECT DISTINCT ph.sku, ph.sku
FROM price_history ph
WHERE NOT EXISTS (
    SELECT 1 FROM analytics.dim_product dp
    WHERE dp.source_system = 'el72'
      AND dp.source_product_id = ph.sku
      AND dp.is_current = TRUE
);

INSERT INTO analytics.dim_retailer (source_retailer_id, name)
SELECT DISTINCT ph.store_id, ph.store_id
FROM price_history ph
ON CONFLICT (source_retailer_id) DO NOTHING;

INSERT INTO analytics.dim_date
    (date_key, full_date, day, day_of_week, week, month, month_name, quarter, year)
SELECT DISTINCT
    to_char(ph.time AT TIME ZONE 'UTC', 'YYYYMMDD')::integer,
    (ph.time AT TIME ZONE 'UTC')::date,
    extract(day FROM ph.time AT TIME ZONE 'UTC')::integer,
    extract(isodow FROM ph.time AT TIME ZONE 'UTC')::integer,
    extract(week FROM ph.time AT TIME ZONE 'UTC')::integer,
    extract(month FROM ph.time AT TIME ZONE 'UTC')::integer,
    to_char(ph.time AT TIME ZONE 'UTC', 'Month'),
    extract(quarter FROM ph.time AT TIME ZONE 'UTC')::integer,
    extract(year FROM ph.time AT TIME ZONE 'UTC')::integer
FROM price_history ph
ON CONFLICT (date_key) DO NOTHING;

INSERT INTO analytics.dim_time (time_key, hour, minute, second, time_period)
SELECT DISTINCT
    extract(hour FROM ph.time AT TIME ZONE 'UTC')::integer * 10000
        + extract(minute FROM ph.time AT TIME ZONE 'UTC')::integer * 100
        + extract(second FROM ph.time AT TIME ZONE 'UTC')::integer,
    extract(hour FROM ph.time AT TIME ZONE 'UTC')::integer,
    extract(minute FROM ph.time AT TIME ZONE 'UTC')::integer,
    extract(second FROM ph.time AT TIME ZONE 'UTC')::integer,
    CASE WHEN extract(hour FROM ph.time AT TIME ZONE 'UTC') < 12 THEN 'morning'
         WHEN extract(hour FROM ph.time AT TIME ZONE 'UTC') < 18 THEN 'afternoon'
         ELSE 'evening' END
FROM price_history ph
ON CONFLICT (time_key) DO NOTHING;

INSERT INTO analytics.fact_price_history
    (observed_at, product_key, retailer_key, date_key, time_key,
     observed_price, currency, availability, source_sku, source_timestamp)
SELECT ph.time, dp.product_key, dr.retailer_key,
       to_char(ph.time AT TIME ZONE 'UTC', 'YYYYMMDD')::integer,
       extract(hour FROM ph.time AT TIME ZONE 'UTC')::integer * 10000
           + extract(minute FROM ph.time AT TIME ZONE 'UTC')::integer * 100
           + extract(second FROM ph.time AT TIME ZONE 'UTC')::integer,
       ph.price_local, ph.currency, COALESCE(ph.in_stock, TRUE), ph.sku, ph.time
FROM price_history ph
JOIN analytics.dim_product dp
  ON dp.source_product_id = ph.sku AND dp.source_system = 'el72'
 AND dp.is_current = TRUE
JOIN analytics.dim_retailer dr ON dr.source_retailer_id = ph.store_id
WHERE NOT EXISTS (
    SELECT 1 FROM analytics.fact_price_history f
    WHERE f.observed_at = ph.time
      AND f.product_key = dp.product_key
      AND f.retailer_key = dr.retailer_key
      AND f.source_sku = ph.sku
);