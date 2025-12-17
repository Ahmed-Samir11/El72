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

-- Alerts table
CREATE TABLE IF NOT EXISTS alerts (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  target_url TEXT NOT NULL,
  target_price NUMERIC(10,2) NOT NULL,
  active_status BOOLEAN NOT NULL DEFAULT TRUE
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
