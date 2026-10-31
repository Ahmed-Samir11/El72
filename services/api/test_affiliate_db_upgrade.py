"""In-place upgrade of a legacy affiliate_clicks table (create_tables.ensure_columns).

No live Postgres in CI; this replays the SQLite path of the upgrade against
the old deployed shape (clicked_at, no attribution columns, legacy-named
index) and asserts the tree converges on the canonical contract — the same
invariants migrations/0012 and schema/postgres.sql are guarded for by
services/common/test_migration_files.py.
"""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from services.api.create_tables import ensure_columns

LEGACY_DDL = """
CREATE TABLE affiliate_clicks (
    id TEXT PRIMARY KEY,
    store_id TEXT NOT NULL,
    target_url TEXT NOT NULL,
    affiliate_url TEXT NOT NULL,
    clicked_at TEXT NOT NULL
);
CREATE INDEX idx_affiliate_clicks_clicked_at
    ON affiliate_clicks(clicked_at);
INSERT INTO affiliate_clicks (id, store_id, target_url, affiliate_url, clicked_at)
VALUES ('c1', 'amazon_eg', 'https://www.amazon.eg/dp/A',
        'https://www.amazon.eg/dp/A', '2024-01-01T00:00:00Z');
"""


def _legacy_engine():
    # In-memory with a shared connection: ensure_columns opens several
    # transactions and the test one file-per-pid trick (a Windows-locked
    # sidecar on teardown) buys nothing here.
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as conn:
        for stmt in LEGACY_DDL.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
    return engine


def test_ensure_columns_converges_legacy_affiliate_table():
    engine = _legacy_engine()
    ensure_columns(engine)

    columns = {c["name"] for c in inspect(engine).get_columns("affiliate_clicks")}
    # Legacy shape is gone; canonical shape is in place.
    assert "clicked_at" not in columns
    assert columns >= {
        "created_at",
        "category",
        "source",
        "session_id",
        "user_id",
        "event_id",
    }

    # The legacy-named index was dropped by the upgrade...
    with engine.connect() as conn:
        indexed = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='index'")
            )
        }
    assert "idx_affiliate_clicks_clicked_at" not in indexed

    # ...and the pre-existing row reads as a real click under the new
    # contract: source backfilled to the allowlist default, not NULL.
    with engine.connect() as conn:
        (source,) = conn.execute(
            text("SELECT source FROM affiliate_clicks WHERE id = 'c1'")
        ).fetchone()
    assert source == "unknown"

    # Re-running must be a no-op, not a second rename or duplicate column.
    ensure_columns(engine)
    columns2 = {c["name"] for c in inspect(engine).get_columns("affiliate_clicks")}
    assert columns2 == columns


def test_new_inserts_get_the_source_default_without_naming_it():
    engine = _legacy_engine()
    ensure_columns(engine)
    # A writer that predates the client contract still cannot produce a NULL
    # source on an upgraded SQLite tree: NOT NULL DEFAULT was part of the
    # ADD COLUMN itself. (created_at follows the old clicked_at NOT NULL
    # column the rename carried over — the ORM supplies it via default.)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO affiliate_clicks (id, store_id, target_url,"
                " affiliate_url, created_at) VALUES ('c2', 'amazon_eg',"
                " 'https://www.amazon.eg/dp/B', 'https://www.amazon.eg/dp/B',"
                " '2024-02-01T00:00:00Z')"
            )
        )
    with engine.connect() as conn:
        (source,) = conn.execute(
            text("SELECT source FROM affiliate_clicks WHERE id = 'c2'")
        ).fetchone()
    assert source == "unknown"
