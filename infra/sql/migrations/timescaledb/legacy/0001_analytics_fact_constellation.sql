-- Analytics fact constellation migration.
-- Execute against the TimescaleDB database after the operational schema exists.
-- Source IDs are mappings, not cross-database foreign keys.

CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.dim_product (
    product_key BIGSERIAL PRIMARY KEY,
    source_product_id TEXT NOT NULL,
    source_system VARCHAR(50) NOT NULL DEFAULT 'el72',
    name TEXT,
    brand TEXT,
    category TEXT,
    subcategory TEXT,
    model TEXT,
    specifications JSONB,
    valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_to TIMESTAMPTZ,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (source_system, source_product_id, valid_from)
);
CREATE TABLE IF NOT EXISTS analytics.dim_retailer (
    retailer_key BIGSERIAL PRIMARY KEY,
    source_retailer_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    website TEXT,
    retailer_type VARCHAR(50),
    location TEXT
);
CREATE TABLE IF NOT EXISTS analytics.dim_user (
    user_key BIGSERIAL PRIMARY KEY,
    source_user_id UUID UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DELETED', 'ANONYMOUS')),
    created_date DATE,
    deleted_date DATE
);
CREATE TABLE IF NOT EXISTS analytics.dim_date (
    date_key INTEGER PRIMARY KEY,
    full_date DATE NOT NULL UNIQUE,
    day INTEGER NOT NULL,
    day_of_week INTEGER NOT NULL,
    week INTEGER NOT NULL,
    month INTEGER NOT NULL,
    month_name VARCHAR(20) NOT NULL,
    quarter INTEGER NOT NULL,
    year INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS analytics.dim_time (
    time_key INTEGER PRIMARY KEY,
    hour INTEGER NOT NULL,
    minute INTEGER NOT NULL,
    second INTEGER NOT NULL,
    time_period VARCHAR(20) NOT NULL
);
CREATE TABLE IF NOT EXISTS analytics.dim_promotion (
    promotion_key BIGSERIAL PRIMARY KEY,
    promotion_type VARCHAR(50),
    promotion_name TEXT,
    advertised_discount NUMERIC(7, 4),
    start_date DATE,
    end_date DATE,
    coupon_required BOOLEAN NOT NULL DEFAULT FALSE,
    description TEXT
);
CREATE TABLE IF NOT EXISTS analytics.dim_channel (
    channel_key BIGSERIAL PRIMARY KEY,
    channel_name VARCHAR(30) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS analytics.fact_price_history (
    price_history_key BIGSERIAL,
    observed_at TIMESTAMPTZ NOT NULL,
    product_key BIGINT NOT NULL REFERENCES analytics.dim_product(product_key),
    retailer_key BIGINT NOT NULL REFERENCES analytics.dim_retailer(retailer_key),
    date_key INTEGER NOT NULL REFERENCES analytics.dim_date(date_key),
    time_key INTEGER NOT NULL REFERENCES analytics.dim_time(time_key),
    promotion_key BIGINT REFERENCES analytics.dim_promotion(promotion_key),
    observed_price NUMERIC(12, 2) NOT NULL CHECK (observed_price >= 0),
    currency VARCHAR(10) NOT NULL DEFAULT 'EGP',
    availability BOOLEAN NOT NULL DEFAULT TRUE,
    source_sku TEXT NOT NULL,
    source_timestamp TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (observed_at, price_history_key)
);
CREATE TABLE IF NOT EXISTS analytics.fact_deal (
    deal_key BIGSERIAL PRIMARY KEY,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    product_key BIGINT NOT NULL REFERENCES analytics.dim_product(product_key),
    retailer_key BIGINT NOT NULL REFERENCES analytics.dim_retailer(retailer_key),
    date_key INTEGER NOT NULL REFERENCES analytics.dim_date(date_key),
    promotion_key BIGINT REFERENCES analytics.dim_promotion(promotion_key),
    current_price NUMERIC(12, 2) NOT NULL CHECK (current_price >= 0),
    advertised_price NUMERIC(12, 2),
    historical_avg_price NUMERIC(12, 2),
    historical_min_price NUMERIC(12, 2),
    historical_max_price NUMERIC(12, 2),
    fair_price NUMERIC(12, 2),
    price_change_percentage NUMERIC(7, 4),
    advertised_discount_percentage NUMERIC(7, 4),
    historical_discount_percentage NUMERIC(7, 4),
    deal_score NUMERIC(7, 4),
    classification VARCHAR(40) NOT NULL,
    model_version VARCHAR(100) NOT NULL,
    feature_version VARCHAR(100)
);
CREATE TABLE IF NOT EXISTS analytics.fact_notification (
    notification_key BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_key BIGINT NOT NULL REFERENCES analytics.dim_user(user_key),
    product_key BIGINT REFERENCES analytics.dim_product(product_key),
    retailer_key BIGINT REFERENCES analytics.dim_retailer(retailer_key),
    date_key INTEGER NOT NULL REFERENCES analytics.dim_date(date_key),
    channel_key BIGINT NOT NULL REFERENCES analytics.dim_channel(channel_key),
    deal_key BIGINT REFERENCES analytics.fact_deal(deal_key),
    status VARCHAR(20) NOT NULL CHECK (status IN ('queued', 'sent', 'delivered', 'failed')),
    sent_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    provider_message_id TEXT,
    error_code TEXT
);

CREATE INDEX IF NOT EXISTS idx_fact_price_product_date
    ON analytics.fact_price_history(product_key, date_key);
CREATE INDEX IF NOT EXISTS idx_fact_price_retailer_date
    ON analytics.fact_price_history(retailer_key, date_key);
CREATE INDEX IF NOT EXISTS idx_fact_price_product_retailer_date
    ON analytics.fact_price_history(product_key, retailer_key, date_key);
CREATE INDEX IF NOT EXISTS idx_fact_deal_product_date
    ON analytics.fact_deal(product_key, date_key);
CREATE INDEX IF NOT EXISTS idx_fact_deal_retailer_date
    ON analytics.fact_deal(retailer_key, date_key);
CREATE INDEX IF NOT EXISTS idx_fact_notification_user_date
    ON analytics.fact_notification(user_key, date_key);
CREATE INDEX IF NOT EXISTS idx_fact_notification_product_date
    ON analytics.fact_notification(product_key, date_key);

INSERT INTO analytics.dim_channel (channel_name)
VALUES ('WhatsApp'), ('Web'), ('Email'), ('Push')
ON CONFLICT (channel_name) DO NOTHING;