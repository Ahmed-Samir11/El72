-- El72 Unified Schema (v1.0)
-- Uses UUID throughout for distributed system compatibility
-- Merges ddl.sql and alerts.sql into a single canonical schema

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Users table (UUID-based)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone VARCHAR(20) UNIQUE NOT NULL,
    password_hash VARCHAR(128) NOT NULL,
    salt VARCHAR(32) NOT NULL,
    tier VARCHAR(20) NOT NULL DEFAULT 'free',
    valid_until TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Alerts table (merged from ddl.sql and alerts.sql)
CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Original ddl.sql columns
    target_url TEXT,
    target_price NUMERIC(10, 2),
    active_status BOOLEAN DEFAULT TRUE,
    
    -- alerts.sql columns (more granular tracking)
    sku TEXT,
    store_id TEXT,
    category TEXT,
    desired_price_egp NUMERIC(10, 2),
    target_price_bucket TEXT,
    notify_channel TEXT DEFAULT 'whatsapp',
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Tracked Items (UUID-based)
CREATE TABLE IF NOT EXISTS tracked_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    canonical_product_id TEXT NOT NULL,
    specs JSONB,
    target_price NUMERIC(10, 2),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Tracked Item Store Mappings
CREATE TABLE IF NOT EXISTS tracked_item_stores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tracked_item_id UUID NOT NULL REFERENCES tracked_items(id) ON DELETE CASCADE,
    store_id TEXT NOT NULL,
    store_sku TEXT NOT NULL,
    store_url TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Current Prices (Materialized snapshots)
CREATE TABLE IF NOT EXISTS current_prices (
    tracked_item_id UUID NOT NULL REFERENCES tracked_items(id) ON DELETE CASCADE,
    store_id TEXT NOT NULL,
    price_usd NUMERIC(10, 4) NOT NULL,
    price_local NUMERIC(10, 2) NOT NULL,
    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
    in_stock BOOLEAN DEFAULT TRUE,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (tracked_item_id, store_id)
);

-- Lowest Prices Cache
CREATE TABLE IF NOT EXISTS lowest_prices (
    tracked_item_id UUID PRIMARY KEY REFERENCES tracked_items(id) ON DELETE CASCADE,
    store_id TEXT NOT NULL,
    price_usd NUMERIC(10, 4) NOT NULL,
    price_local NUMERIC(10, 2) NOT NULL,
    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
    url TEXT NOT NULL,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Price History (TimescaleDB hypertable)
CREATE TABLE IF NOT EXISTS price_history (
    time TIMESTAMP WITH TIME ZONE NOT NULL,
    sku TEXT NOT NULL,
    store_id TEXT NOT NULL,
    price_usd NUMERIC(10, 4) NOT NULL,
    price_local NUMERIC(10, 2) NOT NULL,
    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
    in_stock BOOLEAN DEFAULT TRUE,
    source_url TEXT,
    PRIMARY KEY (time, sku, store_id)
);

-- Convert to hypertable if not already
SELECT create_hypertable('price_history', 'time') 
WHERE NOT EXISTS (
    SELECT 1 FROM timescaledb_information.hypertables 
    WHERE hypertable_name = 'price_history'
);

-- Payment Logs (UUID-based)
CREATE TABLE IF NOT EXISTS payment_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    paymob_order_id VARCHAR(255) UNIQUE NOT NULL,
    amount NUMERIC(10, 2) NOT NULL,
    currency VARCHAR(10) NOT NULL DEFAULT 'EGP',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    tier VARCHAR(20) NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Retailer Analytics (Aggregated B2B metrics, no PII)
CREATE TABLE IF NOT EXISTS retailer_analytics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id TEXT NOT NULL,
    metric_name VARCHAR(100) NOT NULL,
    metric_value NUMERIC(15, 4) NOT NULL,
    period_start TIMESTAMP WITH TIME ZONE NOT NULL,
    period_end TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_alerts_user_id ON alerts(user_id);
CREATE INDEX IF NOT EXISTS idx_alerts_sku ON alerts(sku);
CREATE INDEX IF NOT EXISTS idx_alerts_active_status ON alerts(active_status);
CREATE INDEX IF NOT EXISTS idx_alerts_notify_channel ON alerts(notify_channel);

CREATE INDEX IF NOT EXISTS idx_tracked_items_user_id ON tracked_items(user_id);
CREATE INDEX IF NOT EXISTS idx_tracked_items_canonical_product_id ON tracked_items(canonical_product_id);
CREATE INDEX IF NOT EXISTS idx_tracked_items_is_active ON tracked_items(is_active);

CREATE INDEX IF NOT EXISTS idx_tracked_item_stores_tracked_item_id ON tracked_item_stores(tracked_item_id);
CREATE INDEX IF NOT EXISTS idx_tracked_item_stores_store_id ON tracked_item_stores(store_id);

CREATE INDEX IF NOT EXISTS idx_current_prices_in_stock ON current_prices(in_stock);
CREATE INDEX IF NOT EXISTS idx_current_prices_last_updated ON current_prices(last_updated);

CREATE INDEX IF NOT EXISTS idx_price_history_sku ON price_history(sku);
CREATE INDEX IF NOT EXISTS idx_price_history_store_id ON price_history(store_id);

CREATE INDEX IF NOT EXISTS idx_payment_logs_user_id ON payment_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_payment_logs_status ON payment_logs(status);

CREATE INDEX IF NOT EXISTS idx_retailer_analytics_store_id ON retailer_analytics(store_id);
CREATE INDEX IF NOT EXISTS idx_retailer_analytics_period ON retailer_analytics(period_start, period_end);

-- Functions for updating timestamps
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_alerts_updated_at BEFORE UPDATE ON alerts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tracked_items_updated_at BEFORE UPDATE ON tracked_items
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();