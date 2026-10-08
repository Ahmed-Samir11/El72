-- El72 TimescaleDB canonical schema baseline.
-- infra/sql/schema/timescaledb.sql must be applied before this migration.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(100) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO schema_migrations (version)
VALUES ('canonical-v1.0')
ON CONFLICT (version) DO NOTHING;
