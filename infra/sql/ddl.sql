-- DDL for Elhaq

-- Price history hypertable (TimescaleDB)
CREATE TABLE IF NOT EXISTS price_history (
  time timestamptz NOT NULL,
  sku TEXT NOT NULL,
  store_id TEXT NOT NULL,
  price_egp NUMERIC(10,2) NOT NULL,
  in_stock BOOLEAN,
  PRIMARY KEY (time, sku, store_id)
);

SELECT create_hypertable('price_history', 'time', if_not_exists => TRUE);

-- Users table
CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  phone VARCHAR(20) UNIQUE NOT NULL,
  password_hash VARCHAR(128) NOT NULL,
  salt VARCHAR(32) NOT NULL,
  tier VARCHAR(20) NOT NULL DEFAULT 'free',
  valid_until TIMESTAMPTZ
);

-- Alerts table (legacy - kept for backward compatibility)
CREATE TABLE IF NOT EXISTS alerts (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  target_url TEXT NOT NULL,
  target_price NUMERIC(10,2) NOT NULL,
  active_status BOOLEAN NOT NULL DEFAULT TRUE
);

-- Tracked items table (new price monitoring system)
CREATE TABLE IF NOT EXISTS tracked_items (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  canonical_product_id TEXT NOT NULL,  -- Unified product identifier across stores
  specs JSONB,                         -- Optional spec-based tracking (e.g., {"gpu": "RTX 4060", "ram": "16GB"})
  target_price NUMERIC(10,2),          -- User's desired price (optional)
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tracked_items_user_id ON tracked_items(user_id);
CREATE INDEX IF NOT EXISTS idx_tracked_items_canonical_id ON tracked_items(canonical_product_id);
CREATE INDEX IF NOT EXISTS idx_tracked_items_active ON tracked_items(is_active) WHERE is_active = TRUE;

-- Store-specific product mappings (links tracked items to store SKUs/URLs)
CREATE TABLE IF NOT EXISTS tracked_item_stores (
  id SERIAL PRIMARY KEY,
  tracked_item_id INTEGER NOT NULL REFERENCES tracked_items(id) ON DELETE CASCADE,
  store_id TEXT NOT NULL,              -- e.g., 'amazon_eg', 'noon', 'jumia'
  store_sku TEXT NOT NULL,             -- Store-specific SKU or product ID
  store_url TEXT NOT NULL,             -- Full product URL
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tracked_item_stores_tracked_id ON tracked_item_stores(tracked_item_id);
CREATE INDEX IF NOT EXISTS idx_tracked_item_stores_store ON tracked_item_stores(store_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tracked_item_stores_unique ON tracked_item_stores(tracked_item_id, store_id, store_sku);

-- Current price snapshot (materialized view of latest prices)
CREATE TABLE IF NOT EXISTS current_prices (
  tracked_item_id INTEGER NOT NULL REFERENCES tracked_items(id) ON DELETE CASCADE,
  store_id TEXT NOT NULL,
  price_usd NUMERIC(10,4) NOT NULL,    -- Normalized to USD
  price_local NUMERIC(10,2) NOT NULL,  -- Original price in local currency
  currency TEXT NOT NULL,
  in_stock BOOLEAN NOT NULL DEFAULT TRUE,
  last_updated TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tracked_item_id, store_id)
);

CREATE INDEX IF NOT EXISTS idx_current_prices_tracked_id ON current_prices(tracked_item_id);
CREATE INDEX IF NOT EXISTS idx_current_prices_in_stock ON current_prices(in_stock) WHERE in_stock = TRUE;

-- Lowest price cache (per tracked item)
CREATE TABLE IF NOT EXISTS lowest_prices (
  tracked_item_id INTEGER PRIMARY KEY REFERENCES tracked_items(id) ON DELETE CASCADE,
  store_id TEXT NOT NULL,
  price_usd NUMERIC(10,4) NOT NULL,
  price_local NUMERIC(10,2) NOT NULL,
  currency TEXT NOT NULL,
  url TEXT NOT NULL,
  last_updated TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Payment logs table
CREATE TABLE IF NOT EXISTS payment_logs (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  paymob_order_id TEXT NOT NULL,
  amount NUMERIC(10,2) NOT NULL,
  currency TEXT NOT NULL DEFAULT 'EGP',
  status TEXT NOT NULL,
  tier TEXT NOT NULL,
  valid_until TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Aggregated table for B2B product (no PII)
CREATE TABLE IF NOT EXISTS retailer_analytics (
  store_id TEXT NOT NULL,
  category TEXT NOT NULL,
  target_price_bucket TEXT NOT NULL,
  user_waitlist_count INTEGER DEFAULT 0,
  demand_velocity NUMERIC DEFAULT 0,
  last_updated timestamptz DEFAULT now(),
  PRIMARY KEY (store_id, category, target_price_bucket)
);

-- Example view exposing aggregated metrics (safe for export - no PII)
CREATE OR REPLACE VIEW vw_retailer_analytics AS
SELECT store_id, category, target_price_bucket, user_waitlist_count, demand_velocity, last_updated
FROM retailer_analytics;
