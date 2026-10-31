-- El72 PostgreSQL Schema
-- Canonical operational/payment database schema.
--
-- Fresh-install model: this file is the BASELINE. Feature migrations add
-- the remaining tables on top of it — 0007 (cash payments), 0009
-- (admin dispute/refund) and 0010 (subscriptions/renewals). A complete
-- fresh install is scripts/db-bootstrap.sh (canonical schema + every
-- migration, in order). The legacy merged artifact infra/sql/schema.sql
-- is reference-only and is not applied by the bootstrap.
--
-- User identifier strategy (reconciled): operational tables (users, alerts,
-- tracked_items, ...) use INTEGER primary keys matching the operational ORM
-- models (OperationalIdType). Payment/audit rows keep UUID or SERIAL primary
-- keys as historically issued. This is a schema RECONCILIATION, not an
-- in-place migration: an existing database whose users.id is still UUID is
-- not converted by any migration. To move such a database to this schema,
-- follow docs/user-id-reconciliation.md (rebuild from a dump with a scripted
-- id remap); scripts/audit-db-and-bootstrap.sh reports drift from this
-- canonical schema (read-only) to verify the end state.
-- Do not ALTER a live UUID column to SERIAL.

-- Canonical PostgreSQL Schema (v1.0)
-- Operational, authentication, payment, and application data
-- Merges ddl.sql and alerts.sql into a single canonical schema

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;

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
    active_status BOOLEAN NOT NULL DEFAULT TRUE,

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
    last_fetch_status TEXT,
    last_fetch_error TEXT,
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
    image_url TEXT,
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
    image_url TEXT,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()
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
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS credit_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount INTEGER NOT NULL,
    reason VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Separate admin credentials (not user tiers). Provisioned out-of-band.
-- Admin IDs remain VARCHAR(36) dashed UUID strings for compatibility with
-- SQLAlchemy models and foreign keys from payment_audit_log/manual_payments.
-- User IDs are INTEGER, generated by users.id SERIAL.
CREATE TABLE IF NOT EXISTS admins (
    id VARCHAR(36) PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Manual payments (bridge flow, pre-Paymob): user submits "I've paid",
-- admin verifies the transfer and approves/rejects. Approval grants credits.
CREATE TABLE IF NOT EXISTS manual_payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
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
        CHECK (status IN ('pending', 'approved', 'rejected')),
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
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    -- Set at /payment/confirm; unique — one Paymob payment per record.
    paymob_payment_id VARCHAR(255) UNIQUE,
    package VARCHAR(20) NOT NULL
        CHECK (package IN ('standard', 'premium')),
    amount_egp NUMERIC(10, 2) NOT NULL CHECK (amount_egp > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'succeeded', 'failed', 'canceled')),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_card_payments_user_created
    ON card_payments(user_id, created_at);

-- Wallet payments (Paymob wallet flow): Vodafone Cash / Orange Money /
-- Etisalat Cash / Fawry. The wallet NUMBER is deliberately NOT stored —
-- only the wallet TYPE is kept for audit/ledger purposes (plan 2.8).
CREATE TABLE IF NOT EXISTS wallet_payments (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    -- Set at /payment/confirm; unique — one Paymob payment per record.
    paymob_payment_id VARCHAR(255) UNIQUE,
    wallet_type VARCHAR(30) NOT NULL,
    package VARCHAR(20) NOT NULL
        CHECK (package IN ('standard', 'premium')),
    amount_egp NUMERIC(10, 2) NOT NULL CHECK (amount_egp > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'pending_otp'
        CHECK (status IN ('pending_otp', 'processing', 'succeeded',
            'failed', 'canceled')),
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
-- Defined here (in addition to legacy migration 0007) so a canonical fresh
-- install has the table with the reconciled INTEGER user FK; on databases
-- where 0007 already created it, this is a no-op.
CREATE TABLE IF NOT EXISTS cash_payments (
    id SERIAL PRIMARY KEY,
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
        CHECK (status IN ('pending', 'succeeded', 'failed', 'canceled',
            'refunded')),
    -- Code/order expiry: 24 h from creation (plan 3.3).
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cash_payments_user_created
    ON cash_payments(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_cash_payments_code
    ON cash_payments(payment_code);

-- Append-only audit trail of ALL payment events: admin actions
-- (approve / reject / reveal_contact) and system security events (webhook
-- signature failures, OTP failures, token expiry, amount mismatches).
-- `detail` is sanitized free-form text — never raw card data, gateway
-- tokens or OTPs. No UPDATE/DELETE path exists in the application.
--
-- The action list below is the BASELINE set. Migrations 0003 (reconcile),
-- 0008 (cash events) and 0010 (subscription events) widen it in order on
-- existing databases; the widest set wins because each widening is a full
-- drop/re-add.
CREATE TABLE IF NOT EXISTS payment_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action VARCHAR(50) NOT NULL
        CHECK (action IN ('approve', 'reject', 'reveal_contact',
            'webhook_received', 'webhook_signature_failed',
            'webhook_duplicate', 'validation_rejected', 'otp_failed',
            'token_expired', 'amount_mismatch', 'card_payment_created',
            'staging_rejected', 'wallet_payment_created')),
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
CREATE INDEX IF NOT EXISTS idx_payment_audit_log_target_user_id ON payment_audit_log(target_user_id);

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

-- Affiliate clicks for merchant revenue attribution (Gate 3/4, plans/p1).
-- A click row must answer the report's §11 affiliate questions: per user,
-- per surface (source), per session, per category. user_id only — never a
-- phone number (PII rule); nullable because unauthenticated web/landing
-- clicks are still clicks. source is the app surface that opened the merchant
-- (deal_feed | search_result | tracker_card | browse | web; 'unknown' for
-- callers that do not declare one). created_at renames the legacy clicked_at
-- (deployed trees are migrated by migrations/0012_affiliate_click_attribution.sql).
-- The user FK is ON DELETE SET NULL, never CASCADE: the click itself is not
-- PII, so deleting a user must not erase click history from Gate 3/4 KPIs —
-- the row degrades to an anonymous click.
CREATE TABLE IF NOT EXISTS affiliate_clicks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id VARCHAR(32) NOT NULL,
    sku VARCHAR(255),
    deal_id VARCHAR(255),
    category VARCHAR(100),
    source VARCHAR(32) NOT NULL DEFAULT 'unknown',
    session_id VARCHAR(128),
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    event_id VARCHAR(64),
    target_url TEXT NOT NULL,
    affiliate_url TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
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


CREATE INDEX IF NOT EXISTS idx_payment_logs_user_id ON payment_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_payment_logs_status ON payment_logs(status);
CREATE INDEX IF NOT EXISTS idx_credit_transactions_user_id ON credit_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_credit_transactions_created_at ON credit_transactions(created_at);

CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_store_id ON affiliate_clicks(store_id);
CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_sku ON affiliate_clicks(sku);
CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_created_at ON affiliate_clicks(created_at);
-- Affiliate CTR per user and per surface (§11 KPI family): the two reads the
-- funnel needs are "clicks of this user over time" and "clicks per source over
-- time"; both get a composite index here.
CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_user_time ON affiliate_clicks(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_source ON affiliate_clicks(source, created_at);

CREATE INDEX IF NOT EXISTS idx_retailer_analytics_store_id ON retailer_analytics(store_id);
CREATE INDEX IF NOT EXISTS idx_retailer_analytics_period ON retailer_analytics(period_start, period_end);

-- Chatbot sessions and messages
-- UUID primary keys avoid sequence desynchronization when clients supply ids.
CREATE TABLE IF NOT EXISTS chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role VARCHAR(10) NOT NULL CHECK (role IN ('user', 'bot')),
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_search_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    store_id TEXT NOT NULL,
    product_title TEXT NOT NULL,
    price_local NUMERIC(10, 2) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'EGP',
    url TEXT NOT NULL,
    image_url TEXT,
    -- Rank inside the list the user saw, so "add the third one" resolves to
    -- the same product after a restart (the in-process cache is an optimization).
    position INTEGER NOT NULL DEFAULT 0,
    -- Shared by the rows of one search. Both searches of a session restart at
    -- position 0, so the group id says which rows belong to the same list; the
    -- newest group is found by created_at, never by ordering the uuids.
    -- Rows written before migration 0011 have it NULL until that migration
    -- stamps them with one deterministic id per session.
    search_id UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Warm store searches, keyed by the normalized (store, query, price window)
-- the chatbot builds. Mirrored from its in-process cache so a repeat search
-- answers from the database instead of re-crawling the store, and so warm
-- results survive a container restart. Writes upsert on cache_key, and expired
-- rows are swept (first cache read of a process, then every 20 writes), so the
-- table grows with distinct queries, not with page size or repeat searches.
CREATE TABLE IF NOT EXISTS chat_query_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cache_key TEXT NOT NULL UNIQUE,
    store_id TEXT NOT NULL,
    results JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    -- Epoch seconds rather than a timestamptz: the chatbot compares expiry
    -- numerically, which keeps the query identical on PostgreSQL and on the in-memory
    -- SQLite its unit tests use. Negative (empty-result) entries get a short
    -- expiry here, not the full CACHE_TTL_SECONDS.
    expires_at_epoch BIGINT NOT NULL,
    -- Named exactly as 0011_chatbot_query_cache.sql adds it, so a fresh database
    -- and a migrated one agree on the constraint, not just the column type.
    CONSTRAINT chat_query_cache_expiry_non_negative CHECK (expires_at_epoch >= 0)
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_search_results_session_id ON chat_search_results(session_id);
-- Ordinal requests ("أadd رقم 3") filter a session by position; without the
-- pair, PostgreSQL scans every row the session ever produced.
-- Which search is newest is decided by created_at inside one session, so the
-- session index above already bounds that lookup to the session's own rows;
-- the triple below serves the grouped read itself. A separate
-- (session_id, created_at) index would buy little on a table that holds at most
-- a few dozen rows per search.
CREATE INDEX IF NOT EXISTS idx_chat_search_results_session_search
    ON chat_search_results (session_id, search_id, position);
CREATE INDEX IF NOT EXISTS idx_chat_query_cache_expiry ON chat_query_cache(expires_at_epoch);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON chat_sessions(user_id);

-- Keep updated_at columns current.
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_alerts_updated_at ON alerts;
CREATE TRIGGER update_alerts_updated_at
    BEFORE UPDATE ON alerts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_tracked_items_updated_at ON tracked_items;
CREATE TRIGGER update_tracked_items_updated_at
    BEFORE UPDATE ON tracked_items
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
