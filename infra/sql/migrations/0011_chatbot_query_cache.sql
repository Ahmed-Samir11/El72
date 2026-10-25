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

-- The non-negative expiry check must exist on both a migrated and a rerun
-- database, and ADD CONSTRAINT has no way to skip an existing constraint
-- inline, so the guard is a catalog lookup. Declared in schema/postgres.sql
-- under the same name, so the two paths converge on one constraint.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chat_query_cache_expiry_non_negative'
          AND conrelid = 'chat_query_cache'::regclass
    ) THEN
        ALTER TABLE chat_query_cache
            ADD CONSTRAINT chat_query_cache_expiry_non_negative
            CHECK (expires_at_epoch >= 0);
    END IF;
END
$$;

ALTER TABLE chat_search_results
    ADD COLUMN IF NOT EXISTS position INTEGER NOT NULL DEFAULT 0;

ALTER TABLE chat_search_results
    ADD COLUMN IF NOT EXISTS search_id UUID;

COMMENT ON COLUMN chat_search_results.search_id IS 'Group id shared by every row of one search. A session can hold several searches, each restarting at position 0, so the newest group is what an ordinal reference or a reference-less add-to-feed resolves against.';

-- Ordinal requests ("number 3") read the newest search group of a session
-- ordered by position; without this index PostgreSQL scans every row the session
-- ever produced. Declared in schema/postgres.sql as well, so both paths end up
-- with it. The pair index an earlier revision of this migration created is
-- dropped: it is a prefix of this one and would only slow writes down.
DROP INDEX IF EXISTS idx_chat_search_results_session_position;

CREATE INDEX IF NOT EXISTS idx_chat_search_results_session_search
    ON chat_search_results (session_id, search_id, position);

-- Rows written before this migration carry only the column defaults: position
-- 0 and no search id. That makes an ordinal request against an old session
-- ambiguous, so they are re-ranked by insertion time and stamped with one
-- deterministic id per session. The guard is the missing search id, never the
-- position: the service writes position 0 for the first result of every search,
-- so a default-looking position says nothing about whether a row is legacy.
--
-- Positions are 0-based here exactly as the service writes them (the first
-- result the user was shown has position 0), and the Arabic ordinal is 1-based:
-- "رقم N" resolves to the row at position N-1 in services/chatbot/main.py, which
-- is asserted by test_add_command_resolves_position_against_saved_results. A
-- session resumed after this migration does gain rows from a newer search, and
-- those rows carry their own search id; the statement below refuses to touch
-- any session that already has one, so an old list is ranked once and never
-- re-ranked.
--
-- The same statement stamps the legacy rows with one deterministic search id
-- per session (md5 of the session id, cast to uuid). A session's rows written
-- before this migration all belong to one list, and the service only reads
-- groups from now on, so leaving them NULL would make them unreachable.
UPDATE chat_search_results AS target
   SET search_id = ranked.legacy_search_id,
       position = ranked.rank_minus_one
  FROM (
    -- Only unstamped rows are ranked, and they are ranked inside their own
    -- session. A session that already has grouped rows is excluded below, so
    -- this can never interleave a live search into an old list, and the scan
    -- stays proportional to the legacy rows rather than to the whole table.
    SELECT id,
           session_id,
           md5(session_id::text || '#chatbot-pre-0011-legacy')::uuid
               AS legacy_search_id,
           (ROW_NUMBER() OVER (
               PARTITION BY session_id
               ORDER BY created_at, id
           ) - 1)::INTEGER AS rank_minus_one
      FROM chat_search_results
      WHERE search_id IS NULL
  ) AS ranked
 WHERE target.id = ranked.id
   AND target.search_id IS NULL
   AND NOT EXISTS (
       SELECT 1
       FROM chat_search_results AS live
       WHERE live.session_id = target.session_id
         AND live.search_id IS NOT NULL
   );
