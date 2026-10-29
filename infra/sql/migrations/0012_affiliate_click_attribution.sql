-- Widen affiliate_clicks so a click row answers the report's §11 affiliate
-- questions (per user, per surface, per session, per category) — plans/p1
-- (Gate 3/4 instrumentation). Fresh databases get the new shape from
-- schema/postgres.sql; deployed trees are upgraded here. Idempotent, so it
-- is safe to re-run: ADD COLUMN IF NOT EXISTS, guarded rename,
-- CREATE INDEX IF NOT EXISTS.

-- Attribution context (never a phone number — user_id only; nullable because
-- unauthenticated landing-page clicks are still clicks).
ALTER TABLE affiliate_clicks ADD COLUMN IF NOT EXISTS category VARCHAR(100);
ALTER TABLE affiliate_clicks ADD COLUMN IF NOT EXISTS source VARCHAR(32)
    NOT NULL DEFAULT 'unknown';
ALTER TABLE affiliate_clicks ADD COLUMN IF NOT EXISTS session_id VARCHAR(128);
ALTER TABLE affiliate_clicks ADD COLUMN IF NOT EXISTS user_id INTEGER
    REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE affiliate_clicks ADD COLUMN IF NOT EXISTS event_id VARCHAR(64);

-- clicked_at -> created_at (rename of one release; the ORM keeps a
-- clicked_at alias during the transition). Guarded because the fresh
-- schema already uses created_at, and re-running must not fail.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'affiliate_clicks' AND column_name = 'clicked_at'
    ) THEN
        ALTER TABLE affiliate_clicks RENAME COLUMN clicked_at TO created_at;
    END IF;
END
$$;

-- Affiliate CTR per user and per surface (§11 KPI family).
CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_user_time
    ON affiliate_clicks(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_source
    ON affiliate_clicks(source, created_at);
