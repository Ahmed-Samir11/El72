-- Widen affiliate_clicks so a click row answers the report's §11 affiliate
-- questions (per user, per surface, per session, per category) — plans/p1
-- (Gate 3/4 instrumentation). Fresh databases get the new shape from
-- schema/postgres.sql; deployed trees are upgraded here. Idempotent, so it
-- is safe to re-run: ADD COLUMN IF NOT EXISTS, guarded rename, repair blocks,
-- CREATE INDEX IF NOT EXISTS.

-- Attribution context (never a phone number — user_id only; nullable because
-- unauthenticated landing-page clicks are still clicks). The user FK is
-- ON DELETE SET NULL, never CASCADE: a click row is not PII and deleting a
-- user must not erase historical clicks from the Gate 3/4 KPIs.
ALTER TABLE affiliate_clicks ADD COLUMN IF NOT EXISTS category VARCHAR(100);
ALTER TABLE affiliate_clicks ADD COLUMN IF NOT EXISTS source VARCHAR(32)
    NOT NULL DEFAULT 'unknown';
ALTER TABLE affiliate_clicks ADD COLUMN IF NOT EXISTS session_id VARCHAR(128);
ALTER TABLE affiliate_clicks ADD COLUMN IF NOT EXISTS user_id INTEGER
    REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE affiliate_clicks ADD COLUMN IF NOT EXISTS event_id VARCHAR(64);

-- source is a NOT NULL metric dimension in the canonical schema. A tree
-- upgraded by an older in-place path may already carry a nullable source
-- with NULL rows; backfill those and tighten the column so fresh, migrated
-- and upgraded databases agree on the same contract.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'affiliate_clicks' AND column_name = 'source'
          AND is_nullable = 'YES'
    ) THEN
        UPDATE affiliate_clicks SET source = 'unknown' WHERE source IS NULL;
        ALTER TABLE affiliate_clicks ALTER COLUMN source SET DEFAULT 'unknown';
        ALTER TABLE affiliate_clicks ALTER COLUMN source SET NOT NULL;
    END IF;
END
$$;

-- clicked_at -> created_at (rename of one release; the ORM keeps a
-- clicked_at alias during the transition). Guarded on BOTH sides: rename only
-- when the old name is present and the new one is not, so re-running — or
-- a tree that somehow has both — never fails.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'affiliate_clicks' AND column_name = 'clicked_at'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'affiliate_clicks' AND column_name = 'created_at'
    ) THEN
        ALTER TABLE affiliate_clicks RENAME COLUMN clicked_at TO created_at;
    END IF;
END
$$;

-- The legacy index name followed the rename and then became redundant next
-- to the canonical one: drop it.
DROP INDEX IF EXISTS idx_affiliate_clicks_clicked_at;

-- Affiliate CTR per user and per surface (§11 KPI family).
CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_user_time
    ON affiliate_clicks(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_source
    ON affiliate_clicks(source, created_at);

-- Repair the user FK to exactly one constraint with ON DELETE SET NULL.
-- Trees whose user_id was added before this migration (or by an in-place
-- upgrade) may have no FK at all, and trees that recorded the first draft of
-- this migration have a CASCADE FK; both converge here. Any non-SET NULL
-- FK to users is dropped, then one SET NULL FK is added when none remains.
DO $$
DECLARE
    con RECORD;
BEGIN
    FOR con IN
        SELECT c.conname
        FROM pg_constraint c
        -- fkrelid links pg_foreign_key to its pg_constraint row — the
        -- same join psql's own \d uses to fetch referential actions.
        JOIN pg_foreign_key f ON f.fkrelid = c.oid
        WHERE c.conrelid = 'affiliate_clicks'::regclass
          AND c.contype = 'f'
          AND c.confrelid = 'users'::regclass
          AND f.deltype <> 'n'
    LOOP
        EXECUTE format('ALTER TABLE affiliate_clicks DROP CONSTRAINT %I',
                       con.conname);
    END LOOP;
    -- Orphaned user_id values (rows pointing at users deleted while the
    -- table had no FK) would make ADD CONSTRAINT fail; the column is
    -- nullable BY DESIGN, so an orphan degrades to an anonymous click
    -- row — the same end state ON DELETE SET NULL would give.
    UPDATE affiliate_clicks
       SET user_id = NULL
     WHERE user_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM users u WHERE u.id = affiliate_clicks.user_id);
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'affiliate_clicks'::regclass
          AND contype = 'f'
          AND confrelid = 'users'::regclass
    ) THEN
        ALTER TABLE affiliate_clicks
            ADD CONSTRAINT fk_affiliate_clicks_user_id
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;
    END IF;
END
$$;
