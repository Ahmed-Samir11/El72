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
    "migrations/postgres/0005_free_tier_100_credits.sql",
    "migrations/0007_cash_payments.sql",
    "migrations/0008_payment_audit_log_cash_events.sql",
    "migrations/0009_admin_dispute_refunds.sql",
    "migrations/0010_subscriptions.sql",
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


def test_free_tier_top_up_sums_credit_reasons_null_safely():
    """A credit transaction whose ``reason`` is unexpected must still count.

    The allowance is the balance minus every transaction other than this
    migration's own grants. Written as ``reason <> 'free_tier_100'`` the
    comparison evaluates to NULL for a transaction whose reason is NULL, which
    silently drops a real credit movement from the sum and so over-grants
    on every run. ``IS DISTINCT FROM`` is the null-safe form of the same test.
    """
    body = _strip_comments(
        (INFRA_SQL / "migrations/postgres/0005_free_tier_100_credits.sql").read_text(
            encoding="utf-8"
        )
    )
    assert "IS DISTINCT FROM" in body.upper()
    assert "reason <>" not in body.lower(), (
        "0005 must compare reasons null-safely: `<>` hides a NULL reason from"
        " the allowance sum"
    )


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
