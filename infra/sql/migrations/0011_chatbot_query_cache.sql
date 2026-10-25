-- Chatbot speed: cached store searches, and stable search-result ordering.
-- Idempotent: safe to run multiple times.
--
-- 1. New `chat_query_cache` table — the chatbot mirrors each warm (store,
--    query, price window) result set here, so a repeat search answers from the
--    database instead of re-crawling the store, and the cache survives a
--    container restart. `cache_key` is a SHA-256 digest of the normalized
--    (store, query, min, max) tuple: hashing keeps the key free of delimiters a
--    store id or query could contain, while `store_id` stays a real column so
--    an operator can see which store an entry belongs to.
-- 2. `chat_search_results.position` — the rank a result held in the list the
--    user saw. Without it, "أadd رقم 3" after a restart could resolve to a
--    different row, because created_at alone does not order results inside one
--    search.

CREATE TABLE IF NOT EXISTS chat_query_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cache_key TEXT NOT NULL UNIQUE,
    store_id TEXT NOT NULL,
    results JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    -- Epoch seconds rather than a timestamptz: the chatbot compares expiry
    -- numerically, which keeps the query identical on PostgreSQL and on the
    -- in-memory SQLite its unit tests use. Negative (empty-result) entries get
    -- a short expiry here, not the full CACHE_TTL_SECONDS. Whole seconds are
    -- enough, so the column is an integer; the non-negative rule is added below
    -- as a named constraint so a fresh database (which builds the table from
    -- schema/postgres.sql) and a migrated one agree on the constraint name too.
    expires_at_epoch BIGINT NOT NULL
);

-- Lets the chatbot sweep expired rows in one statement instead of deleting
-- on every write. The service sweeps on its first cache read of a process and
-- every CACHE_SWEEP_EVERY_WRITES writes, and writes are upserts keyed by
-- cache_key, so a repeated search refreshes a row instead of piling up copies.
CREATE INDEX IF NOT EXISTS idx_chat_query_cache_expiry
    ON chat_query_cache (expires_at_epoch);

-- Retype for a database where an earlier revision of this migration already
-- ran with a floating-point expiry. Fractional seconds were never used, so no
-- cache entry depends on them. Guarded on the actual column type: on a fresh
-- database (built from schema/postgres.sql, already BIGINT) this must not take
-- a lock or rewrite the table for nothing.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'chat_query_cache'
          AND column_name = 'expires_at_epoch'
          AND lower(data_type) IN ('double precision', 'real', 'numeric')
    ) THEN
        ALTER TABLE chat_query_cache
            ALTER COLUMN expires_at_epoch TYPE BIGINT;
    END IF;
END
$$;

ALTER TABLE chat_query_cache
    ADD CONSTRAINT IF NOT EXISTS chat_query_cache_expiry_non_negative
    CHECK (expires_at_epoch >= 0);

ALTER TABLE chat_search_results
    ADD COLUMN IF NOT EXISTS position INTEGER NOT NULL DEFAULT 0;

-- Ordinal requests ("number 3") filter a session by position; without the pair
-- index PostgreSQL scans every row the session ever produced. Declared in
-- schema/postgres.sql as well, so both paths end up with it.
CREATE INDEX IF NOT EXISTS idx_chat_search_results_session_position
    ON chat_search_results (session_id, position);

-- Rows written before this migration all carry the default 0, which makes an
-- ordinal request against an old session ambiguous. Re-rank them by insertion
-- time, but only inside a session in which *nothing* is ranked yet: a session
-- that already carries real positions is a live one, and re-ranking part of it
-- (the ranking below only ever sees the rows still at the default) would shuffle
-- it on every rerun. Rows already at the default inside a ranked session are
-- left alone, which makes the whole statement a no-op once rerun.
--
-- Positions are 0-based here exactly as the service writes them (the first
-- result the user was shown has position 0), and the Arabic ordinal is 1-based:
-- "رقم N" resolves to the row at position N-1 in services/chatbot/main.py, which
-- is asserted by test_add_command_resolves_position_against_saved_results. A
-- mixed session (some rows ranked, some still at the default) cannot occur,
-- because every write from the service supplies an explicit position.
UPDATE chat_search_results AS target
   SET position = ranked.rank_minus_one
  FROM (
    SELECT id, session_id,
           (ROW_NUMBER() OVER (
               PARTITION BY session_id
               ORDER BY created_at, id
           ) - 1)::INTEGER AS rank_minus_one,
           -- Highest position already stored in this session: 0 means the
           -- session predates this column and has nothing ranked yet.
           MAX(position) OVER (PARTITION BY session_id) AS session_max_position
      FROM chat_search_results
  ) AS ranked
 WHERE target.id = ranked.id
   AND ranked.session_max_position = 0
   AND target.position = 0;
