-- Chatbot speed: cached store searches, and stable search-result ordering.
-- Idempotent: safe to run multiple times.
--
-- 1. New `chat_query_cache` table — the chatbot mirrors each warm (store,
--    query, price window) result set here, so a repeat search answers from the
--    database instead of re-crawling the store, and the cache survives a
--    container restart. `cache_key` is the normalized lookup key the chatbot
--    builds (e.g. "amazon_eg|laptop|10000|20000"), which is why the store and
--    price window are not separate columns.
-- 2. `chat_search_results.position` — the rank a result held in the list the
--    user saw. Without it, "أضf رقم 3" after a restart could resolve to a
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
    -- in-memory SQLite its unit tests use.
    expires_at_epoch DOUBLE PRECISION NOT NULL
);

-- Lets the chatbot sweep expired rows in one statement instead of deleting
-- on every write.
CREATE INDEX IF NOT EXISTS idx_chat_query_cache_expiry
    ON chat_query_cache (expires_at_epoch);

ALTER TABLE chat_search_results
    ADD COLUMN IF NOT EXISTS position INTEGER NOT NULL DEFAULT 0;
