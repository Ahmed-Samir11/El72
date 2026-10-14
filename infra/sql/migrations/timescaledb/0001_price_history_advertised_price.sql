-- 0001 (timescaledb): Store the advertised "was" (strikethrough) price on
-- price_history, plus a covering index for the fake-discount detector's
-- per-SKU time-window queries.
--
-- Lives in the timescaledb/ migration directory because price_history is a
-- TimescaleDB hypertable (the operational Postgres database does not have
-- this table).
--
-- The scraper extracts `original_price` from product pages (the price shown
-- before a discount). Persisting it per observation lets the fake-discount
-- detector compare the site's claimed discount against the product's real
-- historical price. Nullable: most observations have no advertised price.
ALTER TABLE price_history ADD COLUMN IF NOT EXISTS advertised_price NUMERIC(10, 2);

-- The detector queries WHERE sku = $1 AND time >= $2 ORDER BY time; the
-- hypertable PK (time, sku, store_id) does not serve that access pattern,
-- so index it explicitly (secondary indexes on a hypertable are created
-- per chunk automatically).
CREATE INDEX IF NOT EXISTS idx_price_history_sku_time
    ON price_history (sku, time);
