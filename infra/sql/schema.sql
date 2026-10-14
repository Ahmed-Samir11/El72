-- El72 Unified Schema (v1.0)
-- Operational tables use INTEGER primary keys (matching the operational
-- ORM models); payment/audit rows keep UUID primary keys for compatibility.
-- Merges ddl.sql and alerts.sql into a single canonical schema

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Users table (integer primary key; matches the operational ORM models)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL DEFAULT 'Customer',
    preferred_language VARCHAR(10) NOT NULL DEFAULT 'en',
    password_hash VARCHAR(128) NOT NULL,
    salt VARCHAR(32) NOT NULL,
    tier VARCHAR(20) NOT NULL DEFAULT 'free',
    valid_until TIMESTAMP WITH TIME ZONE,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DELETED')),
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Alerts table (merged from ddl.sql and alerts.sql)
CREATE TABLE IF NOT EXISTS alerts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,

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

-- Tracked Items (integer primary key; references users.id as INTEGER)
CREATE TABLE IF NOT EXISTS tracked_items (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    canonical_product_id TEXT NOT NULL,
    specs JSONB,
    target_price NUMERIC(10, 2),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Tracked Item Store Mappings
CREATE TABLE IF NOT EXISTS tracked_item_stores (
    id SERIAL PRIMARY KEY,
    tracked_item_id INTEGER NOT NULL REFERENCES tracked_items(id) ON DELETE CASCADE,
    store_id TEXT NOT NULL,
    store_sku TEXT NOT NULL,
    store_url TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Current Prices (Materialized snapshots)
CREATE TABLE IF NOT EXISTS current_prices (
    tracked_item_id INTEGER NOT NULL REFERENCES tracked_items(id) ON DELETE CASCADE,
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
    tracked_item_id INTEGER PRIMARY KEY REFERENCES tracked_items(id) ON DELETE CASCADE,
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
    image_url TEXT,
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
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    paymob_order_id VARCHAR(255) UNIQUE NOT NULL,
    amount NUMERIC(10, 2) NOT NULL,
    currency VARCHAR(10) NOT NULL DEFAULT 'EGP',
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    tier VARCHAR(20) NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_credits (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    balance INTEGER NOT NULL DEFAULT 0 CHECK (balance >= 0),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS credit_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount INTEGER NOT NULL,
    reason VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Separate admin credentials (not user tiers). Provisioned out-of-band.
-- id is VARCHAR(36) (dashed UUID string) to match the SQLAlchemy models
-- and allow FKs from payment_audit_log / manual_payments on both engines.
-- NOTE: users.id is INTEGER (SERIAL) in this DDL, matching the operational
-- ORM models; admin ids remain VARCHAR(36) strings by design.
CREATE TABLE IF NOT EXISTS admins (
    id VARCHAR(36) PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Manual payments (bridge flow, pre-Paymob): user submits "I've paid",
-- admin verifies the transfer and approves/rejects. Approval grants credits.
CREATE TABLE IF NOT EXISTS manual_payments (
    id SERIAL PRIMARY KEY,
    order_ref VARCHAR(32) UNIQUE NOT NULL,
    -- SET NULL (not CASCADE): payment history is a financial record and
    -- must survive user deletion for auditing.
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    -- Snapshot of the payer's phone at creation time so the row keeps
    -- forensic attribution even if the user account is later deleted.
    user_phone VARCHAR(20),
    package VARCHAR(20) NOT NULL
        CHECK (package IN ('standard', 'premium')),
    amount_egp NUMERIC(10, 2) NOT NULL CHECK (amount_egp > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'refunded')),
    reject_reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_by VARCHAR(36) REFERENCES admins(id) ON DELETE SET NULL,
    -- Snapshot of the resolving admin's username (survives admin deletion).
    resolved_by_username VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_manual_payments_user_id ON manual_payments(user_id);
-- Composite index for the primary admin query pattern: status filter +
-- created_at date-range scan.
CREATE INDEX IF NOT EXISTS idx_manual_payments_status_created
    ON manual_payments(status, created_at);

-- Card payments (Paymob card flow). Tracks a payment from /payment/start
-- through /payment/confirm until the webhook records the final outcome in
-- payment_logs. Stores NO card data — only Paymob ids and server-determined
-- amounts (PCI-DSS: card data is tokenized on-device and never reaches us).
CREATE TABLE IF NOT EXISTS card_payments (
    id SERIAL PRIMARY KEY,
    -- SET NULL (not CASCADE): payment records survive user deletion.
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    -- Set at /payment/confirm; unique — one Paymob payment per record.
    paymob_payment_id VARCHAR(255) UNIQUE,
    package VARCHAR(20) NOT NULL
        CHECK (package IN ('standard', 'premium')),
    amount_egp NUMERIC(10, 2) NOT NULL CHECK (amount_egp > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'succeeded', 'failed', 'canceled', 'refunded')),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_card_payments_user_created
    ON card_payments(user_id, created_at);

-- Wallet payments (Paymob wallet flow): Vodafone Cash / Orange Money /
-- Etisalat Cash / Fawry. The wallet NUMBER is deliberately NOT stored —
-- only the wallet TYPE is kept for audit/ledger purposes (plan 2.8).
CREATE TABLE IF NOT EXISTS wallet_payments (
    id SERIAL PRIMARY KEY,
    -- SET NULL (not CASCADE): payment records survive user deletion.
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    -- Set at /payment/confirm; unique — one Paymob payment per record.
    paymob_payment_id VARCHAR(255) UNIQUE,
    wallet_type VARCHAR(30) NOT NULL,
    package VARCHAR(20) NOT NULL
        CHECK (package IN ('standard', 'premium')),
    amount_egp NUMERIC(10, 2) NOT NULL CHECK (amount_egp > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'pending_otp'
        CHECK (status IN ('pending_otp', 'processing', 'succeeded',
            'failed', 'canceled', 'refunded')),
    -- OTP brute-force guard (plan 2.1): max 3 attempts, then canceled.
    otp_attempts INTEGER NOT NULL DEFAULT 0 CHECK (otp_attempts >= 0),
    -- OTP challenge expiry (60 s from payment creation, plan 2.1).
    otp_expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wallet_payments_user_created
    ON wallet_payments(user_id, created_at);

-- Cash payments (Paymob cash flow): the user pays at a Fawry cash point or
-- a bank branch using a random single-use code. The code is not PII (it
-- identifies the payment, not the user) and expires after 24 h.
CREATE TABLE IF NOT EXISTS cash_payments (
    id SERIAL PRIMARY KEY,
    -- SET NULL (not CASCADE): cash payment records survive user deletion.
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    -- Set at /payment/confirm; unique — one Paymob payment per record.
    paymob_payment_id VARCHAR(255) UNIQUE,
    -- Random single-use code shown to the user (8 unambiguous chars,
    -- non-sequential; never contains user data — plan 3.1/3.2).
    payment_code VARCHAR(32) UNIQUE NOT NULL,
    cash_type VARCHAR(20) NOT NULL CHECK (cash_type IN ('fawry', 'bank')),
    package VARCHAR(20) NOT NULL
        CHECK (package IN ('standard', 'premium')),
    amount_egp NUMERIC(10, 2) NOT NULL CHECK (amount_egp > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'succeeded', 'failed', 'canceled', 'refunded')),
    -- Code/order expiry: 24 h from creation (plan 3.3).
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cash_payments_user_created
    ON cash_payments(user_id, created_at);

-- Append-only audit trail of ALL payment events: admin actions
-- (approve / reject / reveal_contact) and system security events (webhook
-- signature failures, OTP failures, token expiry, amount mismatches).
-- `detail` is sanitized free-form text — never raw card data, gateway
-- tokens or OTPs. No UPDATE/DELETE path exists in the application.
CREATE TABLE IF NOT EXISTS payment_audit_log (
    id SERIAL PRIMARY KEY,
    action VARCHAR(50) NOT NULL
        CHECK (action IN ('approve', 'reject', 'reveal_contact',
            'refund', 'adjust_credits',
            'webhook_received', 'webhook_signature_failed',
            'webhook_duplicate', 'validation_rejected', 'otp_failed',
            'token_expired', 'amount_mismatch', 'card_payment_created',
            'staging_rejected', 'wallet_payment_created',
            'cash_payment_created', 'cash_expired',
            'subscription_created', 'subscription_canceled',
            'subscription_renewal_succeeded', 'subscription_renewal_failed',
            'subscription_auto_canceled')),
    detail TEXT,
    actor_id VARCHAR(36) REFERENCES admins(id) ON DELETE SET NULL,
    -- Snapshot of the acting admin's username (survives admin deletion).
    actor_username VARCHAR(50),
    -- SET NULL (not CASCADE): audit rows are forensic records and must
    -- survive user deletion.
    target_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    -- Snapshot of the target user's phone at action time.
    target_user_phone VARCHAR(20),
    order_ref VARCHAR(32) NOT NULL,
    client_ip VARCHAR(45),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payment_audit_log_order_ref ON payment_audit_log(order_ref);

-- DB-level append-only enforcement: no UPDATE or DELETE on the audit log,
-- independent of application code.
CREATE OR REPLACE FUNCTION prevent_payment_audit_modification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'payment_audit_log is append-only';
END;
$$;

DROP TRIGGER IF EXISTS payment_audit_log_append_only ON payment_audit_log;
CREATE TRIGGER payment_audit_log_append_only
    BEFORE UPDATE OR DELETE ON payment_audit_log
    FOR EACH ROW EXECUTE FUNCTION prevent_payment_audit_modification();

-- Admin-processed refunds (plan Feature 6). Append-only: a refund is
-- irreversible, and the unique order_key is the idempotency guard against
-- double-deducting a user's credits.
CREATE TABLE IF NOT EXISTS refunds (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    order_key VARCHAR(255) NOT NULL UNIQUE,
    method VARCHAR(20) NOT NULL
        CHECK (method IN ('manual', 'card', 'wallet', 'cash')),
    order_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    package VARCHAR(20) NOT NULL
        CHECK (package IN ('standard', 'premium')),
    amount_egp NUMERIC(10, 2) NOT NULL CHECK (amount_egp > 0),
    credits_deducted INTEGER NOT NULL,
    reason TEXT NOT NULL,
    admin_id VARCHAR(36) REFERENCES admins(id) ON DELETE SET NULL,
    admin_username VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Append-only: a refund is irreversible (plan 6.4). No UPDATE or DELETE.
CREATE OR REPLACE FUNCTION prevent_refund_modification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'refunds is append-only';
END;
$$;

DROP TRIGGER IF EXISTS refunds_append_only ON refunds;
CREATE TRIGGER refunds_append_only
    BEFORE UPDATE OR DELETE ON refunds
    FOR EACH ROW EXECUTE FUNCTION prevent_refund_modification();

-- Recurring subscriptions (plan Feature 7). One active subscription per
-- user; the recurring mandate is charged by Paymob each month.
CREATE TABLE IF NOT EXISTS subscriptions (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    paymob_subscription_id VARCHAR(255) NOT NULL UNIQUE,
    card_payment_method_id VARCHAR(255) NOT NULL,
    package VARCHAR(20) NOT NULL
        CHECK (package IN ('standard', 'premium')),
    amount_egp NUMERIC(10, 2) NOT NULL CHECK (amount_egp > 0),
    billing_interval VARCHAR(10) NOT NULL DEFAULT 'month'
        CHECK (billing_interval IN ('month')),
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'canceled', 'failed')),
    failed_renewals INTEGER NOT NULL DEFAULT 0,
    next_charge TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    canceled_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS ix_subscriptions_user_status
    ON subscriptions (user_id, status);

-- One active subscription per user, enforced at the database level
-- (plan 7.1). Partial unique index: only 'active' rows are constrained,
-- so a user can keep multiple historical (canceled/failed) subscriptions.
DROP INDEX IF EXISTS uq_subscriptions_one_active_per_user;
CREATE UNIQUE INDEX uq_subscriptions_one_active_per_user
    ON subscriptions (user_id) WHERE status = 'active';

-- Append-only: a renewal is a historical record of a charge. The UNIQUE
-- paymob_renewal_id is the idempotency guard against double-charging
-- (plan 7.6). No UPDATE or DELETE.
CREATE TABLE IF NOT EXISTS subscription_renewals (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id VARCHAR(36) NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    paymob_renewal_id VARCHAR(255) NOT NULL UNIQUE,
    amount_egp NUMERIC(10, 2) NOT NULL CHECK (amount_egp > 0),
    status VARCHAR(20) NOT NULL
        CHECK (status IN ('succeeded', 'failed')),
    charged_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_subscription_renewals_subscription
    ON subscription_renewals (subscription_id, created_at);

CREATE OR REPLACE FUNCTION prevent_renewal_modification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'subscription_renewals is append-only';
END;
$$;

DROP TRIGGER IF EXISTS subscription_renewals_append_only ON subscription_renewals;
CREATE TRIGGER subscription_renewals_append_only
    BEFORE UPDATE OR DELETE ON subscription_renewals
    FOR EACH ROW EXECUTE FUNCTION prevent_renewal_modification();

-- Affiliate clicks for merchant revenue attribution
CREATE TABLE IF NOT EXISTS affiliate_clicks (
    id SERIAL PRIMARY KEY,
    store_id VARCHAR(32) NOT NULL,
    sku VARCHAR(255),
    deal_id VARCHAR(255),
    target_url TEXT NOT NULL,
    affiliate_url TEXT NOT NULL,
    clicked_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Retailer Analytics (Aggregated B2B metrics, no PII)
CREATE TABLE IF NOT EXISTS retailer_analytics (
    id SERIAL PRIMARY KEY,
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
CREATE INDEX IF NOT EXISTS idx_credit_transactions_user_id ON credit_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_credit_transactions_created_at ON credit_transactions(created_at);

CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_store_id ON affiliate_clicks(store_id);
CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_sku ON affiliate_clicks(sku);
CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_clicked_at ON affiliate_clicks(clicked_at);

CREATE INDEX IF NOT EXISTS idx_retailer_analytics_store_id ON retailer_analytics(store_id);
CREATE INDEX IF NOT EXISTS idx_retailer_analytics_period ON retailer_analytics(period_start, period_end);

-- NOTE: The analytical tables (analytics.*) have been moved to the
-- TimescaleDB canonical schema (infra/sql/schema/timescaledb.sql).
-- They are no longer part of the operational PostgreSQL schema.

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