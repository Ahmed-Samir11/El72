-- Alerts table DDL and example data for Elhaq
-- Note: ensure UUID generation extension exists on Postgres (pgcrypto or uuid-ossp)

-- Enable pgcrypto for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pgcrypto;

BEGIN;

CREATE TABLE IF NOT EXISTS alerts (
  alert_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  sku TEXT NOT NULL,
  store_id TEXT,
  category TEXT,
  desired_price_egp NUMERIC(10,2),
  target_price_bucket TEXT,
  notify_channel TEXT DEFAULT 'whatsapp',
  active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_alerts_sku ON alerts (sku);
CREATE INDEX IF NOT EXISTS idx_alerts_user ON alerts (user_id);

-- Example alerts (replace user_id values with real user UUIDs from your users table)
INSERT INTO alerts (user_id, sku, store_id, category, desired_price_egp, target_price_bucket)
VALUES
  ('00000000-0000-0000-0000-000000000001','SKU-ABC-123','noon','laptops',4999.00,'0-4999'),
  ('00000000-0000-0000-0000-000000000002','SKU-XYZ-999','sigma','phones',999.00,'0-4999');

COMMIT;
