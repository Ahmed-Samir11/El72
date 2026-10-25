"""Structural tests for the schema/migration layout.

These guard the invariants the review flagged without requiring a live
Postgres: no committed database dumps, no explicit transaction control in
migrations (the bootstrap wraps each file in --single-transaction), the
bootstrap only references files that exist, and no plaintext credentials
are committed. They run in CI via ``pytest services``.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INFRA_SQL = REPO_ROOT / "infra" / "sql"
BOOTSTRAP = REPO_ROOT / "scripts" / "db-bootstrap.sh"
ENV_EXAMPLE = REPO_ROOT / ".env.example"

# Files added upstream (e.g. the advertised-price migration from the fake
# discount detector PR) that this branch's bootstrap references before the
# merge. They always exist on the merged tree; on a pre-merge branch the
# existence checks below tolerate their absence.
UPSTREAM_ADDED = {
    "infra/sql/migrations/timescaledb/0001_price_history_advertised_price.sql",
}

# Migrations applied by the bootstrap; each must be safe to wrap in a single
# transaction, i.e. must NOT contain its own transaction-control statements.
POSTGRES_MIGRATIONS = [
    "migrations/postgres/0000_baseline.sql",
    "migrations/postgres/0001_monitor_role.sql",
    "migrations/postgres/0002_payment_history_fk_alignment.sql",
    "migrations/postgres/0003_payment_audit_log_action_events.sql",
    "migrations/postgres/0004_schema_compatibility_repairs.sql",
    "migrations/0007_cash_payments.sql",
    "migrations/0008_payment_audit_log_cash_events.sql",
    "migrations/0009_admin_dispute_refunds.sql",
    "migrations/0010_subscriptions.sql",
    "migrations/0011_chatbot_query_cache.sql",
]
TIMESCALE_MIGRATIONS = [
    "migrations/timescaledb/0000_baseline.sql",
    "migrations/timescaledb/0001_price_history_advertised_price.sql",
    "migrations/timescaledb/0002_monitor_role.sql",
]

_TX_CONTROL = re.compile(
    r"^\s*(BEGIN|COMMIT|END|ROLLBACK|ABORT)\s*;", re.IGNORECASE | re.MULTILINE
)


def _strip_comments(sql: str) -> str:
    """Remove -- line comments so only executable SQL remains."""
    return "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )


def _top_level_statements(sql: str) -> str:
    """Remove -- comments AND dollar-quoted bodies.

    Inside a $$ ... $$ body (PL/pgSQL) the keywords BEGIN/END appear as
    block delimiters (e.g. ``END;`` closes a CREATE FUNCTION body) and must
    not be confused with top-level SQL transaction control.
    """
    without_bodies = re.sub(r"\$\$.+?\$\$", "", sql, flags=re.DOTALL)
    return _strip_comments(without_bodies)


def test_no_committed_database_backups():
    backups = REPO_ROOT / "backups"
    if backups.exists():
        dumps = list(backups.rglob("*.dump")) + list(backups.rglob("*.sql.gz"))
        assert not dumps, f"Committed database backups found: {dumps}"


def test_bootstrap_references_only_existing_files():
    text = BOOTSTRAP.read_text(encoding="utf-8")
    referenced = re.findall(r"infra/sql/[A-Za-z0-9_./-]+\.sql", text)
    assert referenced, "bootstrap should reference at least one SQL file"
    for ref in set(referenced):
        if not (REPO_ROOT / ref).exists():
            assert ref in UPSTREAM_ADDED, f"bootstrap references missing file: {ref}"


def test_bootstrap_migrations_have_no_explicit_transactions():
    for rel in POSTGRES_MIGRATIONS + TIMESCALE_MIGRATIONS:
        path = INFRA_SQL / rel
        if not path.exists():
            # Upstream file not present on a pre-merge branch; the merged
            # tree (where CI's merge status runs) always has it.
            assert f"infra/sql/{rel}" in UPSTREAM_ADDED, f"missing migration: {rel}"
            continue
        body = _top_level_statements(path.read_text(encoding="utf-8"))
        matches = _TX_CONTROL.findall(body)
        assert not matches, (
            f"{rel} contains explicit transaction control {matches}; "
            "the bootstrap's --single-transaction wrapper provides atomicity"
        )


def test_monitor_role_migrations_are_idempotent():
    for rel in (
        "migrations/postgres/0001_monitor_role.sql",
        "migrations/timescaledb/0002_monitor_role.sql",
    ):
        body = _strip_comments((INFRA_SQL / rel).read_text(encoding="utf-8"))
        assert "CREATE ROLE" in body.upper()
        # Guarded creation: the role must only be created when absent.
        assert re.search(
            r"IF\s+NOT\s+EXISTS", body, re.IGNORECASE
        ), f"{rel} should guard role creation with IF NOT EXISTS"


def test_fk_alignment_has_uuid_precondition_guard():
    body = _strip_comments(
        (
            INFRA_SQL / "migrations/postgres/0002_payment_history_fk_alignment.sql"
        ).read_text(encoding="utf-8")
    )
    assert "uuid" in body.lower(), "0002 should fail explicitly on a UUID users.id"
    assert "RAISE EXCEPTION" in body.upper()


def test_env_example_has_no_plaintext_passwords():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition("=")
        if "PASSWORD" in key.upper() or "SECRET" in key.upper():
            # Placeholders like CHANGE_ME are allowed; a real-looking value is not.
            assert value in (
                "",
                "CHANGE_ME",
            ), f"{key} appears to carry a committed secret in .env.example"


def test_numbered_migrations_are_applied_by_the_bootstrap():
    """A migration the bootstrap never applies leaves a column missing.

    The chatbot inserts ``chat_search_results.position`` and writes its cache
    through ``chat_query_cache``, so a database bootstrapped without 0011 fails
    at query time rather than at startup. Legacy migrations are applied by
    operators only, hence the narrower scan of the numbered files.
    """
    text = BOOTSTRAP.read_text(encoding="utf-8")
    referenced = set(re.findall(r"infra/sql/[A-Za-z0-9_./-]+\.sql", text))

    for directory in (
        INFRA_SQL / "migrations",
        INFRA_SQL / "migrations/postgres",
        INFRA_SQL / "migrations/timescaledb",
    ):
        for path in sorted(directory.glob("*.sql")):
            rel = "infra/sql/" + path.relative_to(INFRA_SQL).as_posix()
            assert rel in referenced, f"{rel} is never applied by the bootstrap"


def test_migration_tables_are_declared_in_the_canonical_schema():
    """A fresh database and a migrated one must end up with the same shape.

    ``0011_chatbot_query_cache.sql`` creates what an existing deployment is
    missing; ``schema/postgres.sql`` is what a new one starts from. If they
    drift, the chatbot's cache writes fail on exactly one of the two paths.
    """
    migration = (INFRA_SQL / "migrations/0011_chatbot_query_cache.sql").read_text(
        encoding="utf-8"
    )
    schema = (INFRA_SQL / "schema/postgres.sql").read_text(encoding="utf-8")

    for table in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", migration):
        assert (
            f"CREATE TABLE IF NOT EXISTS {table} (" in schema
        ), f"{table} is created by 0011 but missing from schema/postgres.sql"

    for index in re.findall(r"CREATE INDEX IF NOT EXISTS (\w+)", migration):
        assert (
            f"CREATE INDEX IF NOT EXISTS {index}" in schema
        ), f"{index} is created by 0011 but missing from schema/postgres.sql"

    # position is added by ALTER TABLE here and must exist in the fresh table.
    assert "ADD COLUMN IF NOT EXISTS position" in migration
    assert re.search(
        r"position INTEGER NOT NULL", schema
    ), "chat_search_results.position is missing from schema/postgres.sql"


def test_the_position_backfill_only_touches_unranked_sessions():
    """Re-ranking legacy rows must stay idempotent, live sessions included.

    The migration re-ranks ``chat_search_results`` rows that still carry the
    column default. Limiting the statement to sessions in which *nothing* is
    ranked yet is what keeps a rerun after new inserts harmless: a session that
    already has real positions is never touched, so a fresh row written into an
    old session cannot be shuffled by a later run of the same migration.
    """
    migration = (INFRA_SQL / "migrations/0011_chatbot_query_cache.sql").read_text(
        encoding="utf-8"
    )
    body = _strip_comments(migration)

    assert re.search(
        r"UPDATE\s+chat_search_results", body, re.IGNORECASE
    ), "legacy rows should be re-ranked"
    assert "ROW_NUMBER() OVER" in body.upper()

    # The ranking window must span the whole session: filtering the rows before
    # the window would rank the surviving ones 0..n and corrupt live sessions.
    assert re.search(
        r"FROM\s+chat_search_results\s*\)\s*AS ranked", body, re.IGNORECASE
    ), "the ranking window should see every row of the session"

    # Sessions that already carry positions are left alone entirely.
    assert re.search(
        r"MAX\(position\)\s+OVER\s*\(\s*PARTITION\s+BY\s+session_id\s*\)",
        body,
        re.IGNORECASE,
    ), "the backfill should detect already-ranked sessions"
    assert re.search(
        r"session_max_position\s*=\s*0", body, re.IGNORECASE
    ), "already-ranked sessions must be skipped"
    assert re.search(
        r"target\.position\s*=\s*0", body, re.IGNORECASE
    ), "only rows still at the default may be written"


def test_cache_expiry_is_an_integer_with_a_non_negative_check():
    """Expiry is compared numerically by the chatbot; floats buy nothing.

    A fresh database and a migrated one must agree on the type and on the
    constraint name, otherwise the two paths drift silently and only one of
    them rejects a bogus expiry.
    """
    migration = (INFRA_SQL / "migrations/0011_chatbot_query_cache.sql").read_text(
        encoding="utf-8"
    )
    schema = (INFRA_SQL / "schema/postgres.sql").read_text(encoding="utf-8")

    for name, sql in (("0011", migration), ("schema", schema)):
        assert (
            "expires_at_epoch BIGINT NOT NULL" in sql
        ), f"{name} should store expiry as an integer number of seconds"
        assert (
            "chat_query_cache_expiry_non_negative" in sql
        ), f"{name} should declare the non-negative expiry constraint"
        assert (
            "idx_chat_search_results_session_position" in sql
        ), f"{name} should index ordinal lookups by (session_id, position)"
    assert (
        "expires_at_epoch DOUBLE PRECISION" not in migration
    ), "the migrated column should not fall back to a float expiry"
    assert (
        "expires_at_epoch DOUBLE PRECISION" not in schema
    ), "the fresh column should not fall back to a float expiry"
