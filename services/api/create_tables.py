"""Create/upgrade API database tables.

``Base.metadata.create_all`` only adds *missing* tables; columns added to
existing ORM models later are not backfilled. The ``_ensure_columns`` step
below upgrades existing databases in place (idempotent):

- Postgres: ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` (native).
- SQLite:   ``ALTER TABLE ... ADD COLUMN`` wrapped in try/except
  (no ``IF NOT EXISTS`` support; "duplicate column name" means done).
"""

import logging
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.api.models import Base

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://elhaq:elhaq_pass@localhost:5432/elhaq"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# (table, column, sql_type) — new columns that must exist on upgraded DBs.
_REQUIRED_COLUMNS = [
    ("tracked_item_stores", "last_fetch_status", "TEXT"),
    ("tracked_item_stores", "last_fetch_error", "TEXT"),
    ("current_prices", "image_url", "TEXT"),
    ("lowest_prices", "image_url", "TEXT"),
]


def _ensure_columns() -> None:
    """Add any missing columns from ``_REQUIRED_COLUMNS`` (idempotent)."""
    dialect = engine.dialect.name
    for table, column, sql_type in _REQUIRED_COLUMNS:
        if dialect == "postgresql":
            with engine.begin() as conn:
                conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {sql_type}"
                )
        else:
            try:
                with engine.begin() as conn:
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"
                    )
            except Exception as exc:  # noqa: BLE001
                # "duplicate column name" (SQLite) → already present.
                if "duplicate column" in str(exc).lower():
                    continue
                logger.warning("Could not add %s.%s: %s", table, column, exc)
                raise
        logger.info("Ensured column %s.%s", table, column)


if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    print("Tables created")
