-- Add nullable alert metadata expected by the current ORM to the preserved
-- legacy alerts table. Existing alert rows remain unchanged.
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS sku TEXT;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS store_id TEXT;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS category TEXT;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS desired_price_egp NUMERIC(10, 2);
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS target_price_bucket TEXT;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS notify_channel TEXT DEFAULT 'whatsapp';

CREATE INDEX IF NOT EXISTS idx_alerts_sku ON alerts(sku);
CREATE INDEX IF NOT EXISTS idx_alerts_notify_channel ON alerts(notify_channel);