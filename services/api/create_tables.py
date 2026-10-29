"""Create/upgrade API database tables.

``Base.metadata.create_all`` only adds *missing* tables; columns added to
existing ORM models later are not backfilled. The :func:`ensure_columns`
step upgrades existing databases in place (idempotent, and safe under
concurrent startups).

This module is **import-safe**: no engine or connection pool is created at
import time (the API imports :func:`ensure_columns` and passes its own
engine). The standalone script entry point below builds its own engine from
``DATABASE_URL``.
"""

import logging
import os

from sqlalchemy import create_engine, inspect

from services.api.models import Base

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://elhaq:elhaq_pass@localhost:5432/elhaq"
)

# (table, column, sql_type) — new columns that must exist on upgraded DBs.
_REQUIRED_COLUMNS = [
    ("tracked_item_stores", "last_fetch_status", "TEXT"),
    ("tracked_item_stores", "last_fetch_error", "TEXT"),
    ("current_prices", "image_url", "TEXT"),
    ("lowest_prices", "image_url", "TEXT"),
    # Affiliate click attribution (plans/p1): the click row gains who/where
    # context so Gate 3/4 can be evaluated on upgraded databases too. source
    # carries the canonical NOT NULL DEFAULT contract (see _AFFILIATE_UPGRADES
    # below); user_id is INTEGER-only here — SQLite cannot attach a FK to an
    # existing table via ALTER, and the Postgres FK is restored by the guarded
    # statement in _AFFILIATE_UPGRADES.
    ("affiliate_clicks", "category", "TEXT"),
    ("affiliate_clicks", "source", "TEXT NOT NULL DEFAULT 'unknown'"),
    ("affiliate_clicks", "session_id", "TEXT"),
    ("affiliate_clicks", "user_id", "INTEGER"),
    ("affiliate_clicks", "event_id", "TEXT"),
]

# (table, old_column, new_column) — renames applied only when the old name
# is present and the new one is not (idempotent; the reverse of an already
# renamed database is NOT attempted: created_at stays the canonical name).
_RENAMED_COLUMNS = [("affiliate_clicks", "clicked_at", "created_at")]

# Constraint parity for affiliate_clicks on upgraded databases; the plain
# ADD COLUMN loop cannot express these. An older tree may hold a nullable
# source with NULL rows, the legacy-named index that followed the clicked_at
# rename and — on Postgres — either no user FK (column added by ALTER) or
# the first draft's CASCADE FK. Statements run in order; every one is idempotent
# and a missing-table error simply means "fresh database, nothing to upgrade".
# The Postgres block converges on exactly one SET NULL FK: a click row is not
# PII, so deleting a user must never erase click history (Gate 3/4 KPIs).
_AFFILIATE_UPGRADES_COMMON = [
    "UPDATE affiliate_clicks SET source = 'unknown' WHERE source IS NULL",
    "DROP INDEX IF EXISTS idx_affiliate_clicks_clicked_at",
]

# Named dollar-quote ($afffk$) so the test_migration_files stripper, which
# removes $$...$$ bodies, still sees this block as guarded SQL text when a
# future check needs it, and nesting never confuses the PL/pgSQL parser.
AFFILIATE_FK_REPAIR_SQL = """
DO $afffk$
DECLARE
    con RECORD;
BEGIN
    FOR con IN
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_foreign_key f ON f.fkrelid = c.oid
        WHERE c.conrelid = 'affiliate_clicks'::regclass
          AND c.contype = 'f'
          AND c.confrelid = 'users'::regclass
          AND f.deltype <> 'n'
    LOOP
        EXECUTE format('ALTER TABLE affiliate_clicks DROP CONSTRAINT %I',
                       con.conname);
    END LOOP;
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
$afffk$
"""

_AFFILIATE_UPGRADES_POSTGRESQL = [
    "ALTER TABLE affiliate_clicks ALTER COLUMN source SET DEFAULT 'unknown'",
    "ALTER TABLE affiliate_clicks ALTER COLUMN source SET NOT NULL",
    AFFILIATE_FK_REPAIR_SQL,
]


def _existing_columns(engine) -> dict:
    """{table: {column, ...}} for the tables we care about (missing = {})."""
    inspector = inspect(engine)
    tables = {table for table, _, _ in _REQUIRED_COLUMNS} | {
        table for table, _, _ in _RENAMED_COLUMNS
    }
    existing = {}
    for table in tables:
        try:
            existing[table] = {c["name"] for c in inspector.get_columns(table)}
        except Exception:  # table doesn't exist yet (fresh DB)
            existing[table] = set()
    return existing


def ensure_columns(engine) -> None:
    """Add any missing columns from ``_REQUIRED_COLUMNS`` (idempotent).

    Only columns actually added produce a log line, so startup logs stay
    quiet on already-upgraded databases. Dialect-aware DDL plus a
    duplicate-column tolerance makes concurrent startups (rolling deploy,
    two replicas against one DB) safe: Postgres uses ``IF NOT EXISTS``
    natively; SQLite (and a Postgres race between the inspector read and
    the ALTER) tolerates the duplicate-column error.
    """
    existing = _existing_columns(engine)
    dialect = engine.dialect.name
    for table, column, sql_type in _REQUIRED_COLUMNS:
        if not existing.get(table, set()):
            continue  # table absent (fresh DB): create_all owns its shape
        if column in existing[table]:
            continue  # already present — nothing to do, nothing to log
        ddl = (
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {sql_type}"
            if dialect == "postgresql"
            else f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"
        )
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(ddl)
        except Exception as exc:  # noqa: BLE001
            # Lost a race: a concurrent startup added the column between
            # our inspector read and this ALTER (Postgres pgcode 42701,
            # SQLite "duplicate column name") — both mean: already there.
            detail = str(exc).lower()
            if "duplicate column" in detail or "42701" in detail:
                continue
            raise
        logger.info("Added missing column %s.%s", table, column)

    for table, old_column, new_column in _RENAMED_COLUMNS:
        columns = existing.get(table, set())
        if new_column in columns or old_column not in columns:
            continue  # already renamed (or a fresh DB that never had the old)
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(
                    f"ALTER TABLE {table} RENAME COLUMN {old_column} "
                    f"TO {new_column}"
                )
        except Exception as exc:  # noqa: BLE001
            # Lost a race with a concurrent startup (or the deployed-tree
            # migration already renamed it): "no such column" means the
            # rename is done; anything else must stay loud.
            detail = str(exc).lower()
            if "no such column" in detail or "already exists" in detail:
                continue
            raise
        logger.info("Renamed legacy column %s.%s -> %s", table, old_column, new_column)

    _run_affiliate_upgrades(engine, dialect)


def _affiliate_upgrade_statements(dialect: str) -> list[str]:
    """Ordered constraint-parity statements for affiliate_clicks.

    Postgres runs the full set (backfill, tighten source, drop the legacy
    index, converge the user FK on SET NULL); SQLite runs the two statements
    it understands — it cannot ALTER a column's nullness or attach a FK to
    an existing table, and its FK (from the ORM metadata at table-creation
    time) already carries the SET NULL contract.
    """
    backfill, drop_legacy_index = _AFFILIATE_UPGRADES_COMMON
    if dialect == "postgresql":
        return [
            backfill,
            *_AFFILIATE_UPGRADES_POSTGRESQL[:2],
            drop_legacy_index,
            AFFILIATE_FK_REPAIR_SQL,
        ]
    return [backfill, drop_legacy_index]


def _run_affiliate_upgrades(engine, dialect: str) -> None:
    """Apply the affiliate constraint-parity statements (idempotent).

    A missing table means a fresh database that create_all just built from
    the canonical ORM metadata — nothing to upgrade; anything else stays
    loud.
    """
    for ddl in _affiliate_upgrade_statements(dialect):
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(ddl)
        except Exception as exc:  # noqa: BLE001
            detail = str(exc).lower()
            if "no such table" in detail or "does not exist" in detail:
                return
            raise


if __name__ == "__main__":
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    ensure_columns(engine)
    print("Tables created")
