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
]


def _existing_columns(engine) -> dict:
    """{table: {column, ...}} for the tables we care about (missing = {})."""
    inspector = inspect(engine)
    tables = {table for table, _, _ in _REQUIRED_COLUMNS}
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
        if column in existing.get(table, set()):
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


if __name__ == "__main__":
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    ensure_columns(engine)
    print("Tables created")
