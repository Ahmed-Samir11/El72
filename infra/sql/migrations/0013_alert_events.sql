-- Alert EVENT history (plans/p2 WS1 — Gate 2 "do alerts bring users back?").
-- Deployed trees have alerts (the user's tracker/target) but no per-user
-- record that a price event happened, so an alert was invisible on next app
-- open. Fresh databases get the table from schema/postgres.sql; existing
-- trees are upgraded here. Idempotent: CREATE TABLE/INDEX IF NOT EXISTS,
-- guarded trigger re-create, safe under a re-run of the bootstrap.
--
-- Semantics (identical to the canonical schema; keep the two in lockstep —
-- services/api/test_alert_events_schema_sync.py compares the ORM model with
-- both files):
--   user_id           CASCADE: the alert feed is the user's own derived data.
--   tracked_item_id   no FK: tracked_items is scraper-owned (service isolation)
--   opened_at         set when the user sees the event in the Alerts tab
--                     (POST /alerts/{id}/open) or taps its push — the metric
--                     that makes "alerts bring users back" measurable.
--   channel           'in_app' is the only channel this build delivers; the
--                     CHECK widens when the push/WhatsApp senders ship, and a
--                     row must never claim a send that did not happen.
--   timestamps        TIMESTAMP WITHOUT TIME ZONE, defaulted and triggered in
--                     UTC: services/api writes naive UTC and the same-day dedupe
--                     compares a stored value to a computed window boundary, so
--                     the column kind must match the value kind (the drift test
--                     pins this against schema/postgres.sql).

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- The shared updated_at trigger function; already present on any tree that
-- applied the canonical schema, re-declared here so this migration is safe
-- to apply on a tree that predates it (CREATE OR REPLACE, no-op otherwise).
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS alert_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tracked_item_id INTEGER NOT NULL,
    sku TEXT,
    store_id TEXT,
    category TEXT,
    url TEXT,
    event_type TEXT NOT NULL
        CHECK (event_type IN ('price_drop', 'threshold_crossed',
            'lowest_price_changed', 'back_in_stock')),
    price_egp NUMERIC(12, 2),
    reference_price_egp NUMERIC(12, 2),
    discount_pct NUMERIC(6, 2),
    channel TEXT NOT NULL DEFAULT 'in_app'
        CHECK (channel IN ('in_app', 'push', 'whatsapp')),
    opened_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'UTC'),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'UTC')
);

-- Alerts tab read (user, newest first), the consumer's same-day dedupe
-- (item, time) and the unopened-alert count (user, opened).
CREATE INDEX IF NOT EXISTS idx_alert_events_user_time
    ON alert_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_events_item_time
    ON alert_events(tracked_item_id, created_at);
CREATE INDEX IF NOT EXISTS idx_alert_events_user_opened
    ON alert_events(user_id, opened_at);

-- Same-day rule enforced by the database, not only by the consumer's check,
-- so concurrent consumers/replicas cannot both write the day's alert.
CREATE UNIQUE INDEX IF NOT EXISTS uq_alert_events_item_type_day
    ON alert_events(tracked_item_id, event_type, (created_at::date));

-- The UTC-pinned updated_at trigger (a naive column must not inherit the
-- session timezone through the shared trigger function).
CREATE OR REPLACE FUNCTION update_alert_events_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW() AT TIME ZONE 'UTC';
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_alert_events_updated_at ON alert_events;
CREATE TRIGGER update_alert_events_updated_at
    BEFORE UPDATE ON alert_events
    FOR EACH ROW
    EXECUTE FUNCTION update_alert_events_updated_at_column();

-- No backfill, deliberately: an alert_events row asserts "a price event
-- happened for this user", and an upgraded tree has no recorded history of
-- events, only of current prices. Synthesizing rows from current_prices would
-- invent events that never occurred and would inflate exactly the opened/un
-- opened ratio Gate 2 is measured on. The history starts empty and fills from
-- stream:alerts; "no alerts yet" is the honest first state.
