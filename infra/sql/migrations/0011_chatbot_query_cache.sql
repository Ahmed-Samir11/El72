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
    -- a short expiry here, not the full CACHE_TTL_SECONDS.
    expires_at_epoch DOUBLE PRECISION NOT NULL
);

-- Lets the chatbot sweep expired rows in one statement instead of deleting
-- on every write.
CREATE INDEX IF NOT EXISTS idx_chat_query_cache_expiry
    ON chat_query_cache (expires_at_epoch);

ALTER TABLE chat_search_results
    ADD COLUMN IF NOT EXISTS position INTEGER NOT NULL DEFAULT 0;

-- Rows written before this migration all carry the default 0, which makes an
-- ordinal request against an old session ambiguous. Re-rank them inside their
-- session by insertion time. Only rows still at the default are touched, so
-- already-ranked sessions are left alone and re-running this is a no-op.
UPDATE chat_search_results AS target
   SET position = ranked.rank_minus_one
  FROM (
    SELECT id,
           (ROW_NUMBER() OVER (
               PARTITION BY session_id
               ORDER BY created_at, id
           ) - 1)::INTEGER AS rank_minus_one
      FROM chat_search_results
     WHERE position = 0
  ) AS ranked
 WHERE target.id = ranked.id;
