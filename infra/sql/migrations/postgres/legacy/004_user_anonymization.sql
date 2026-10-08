-- Preserve the operational user row and UUID while revoking access and removing
-- identifying account data. Analytical dimensions can retain the source UUID.
ALTER TABLE users ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE';
ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_status_check;
ALTER TABLE users ADD CONSTRAINT users_status_check
    CHECK (status IN ('ACTIVE', 'DELETED'));
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);