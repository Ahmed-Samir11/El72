"""Structural tests for the schema/migration layout.

These guard the invariants the review flagged without requiring a live
Postgres: no committed database dumps, no explicit transaction control in
migrations (the bootstrap wraps each file in --single-transaction), the
bootstrap only references files that exist, and no plaintext credentials
are committed. They run in CI via ``pytest services``.
"""

import re
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INFRA_SQL = REPO_ROOT / "infra" / "sql"
BOOTSTRAP = REPO_ROOT / "scripts" / "db-bootstrap.sh"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
FREE_TIER_MIGRATION = INFRA_SQL / "migrations/postgres/0005_free_tier_100_credits.sql"

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
    "migrations/0012_affiliate_click_attribution.sql",
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


def _cte_body(sql: str, name: str) -> str:
    """Return the SELECT inside ``WITH <name> AS ( ... )``.

    Parentheses are balanced by scanning, skipping single-quoted literals, so
    nested calls (COALESCE/SUM/FILTER) stay inside the returned body.
    """
    match = re.search(rf"\b{re.escape(name)}\s+AS\s*\(", sql, re.IGNORECASE)
    assert match, f"{name} CTE not found"
    start = match.end()
    depth = 1
    i = start
    while depth:
        ch = sql[i]
        if ch == "'":
            i = sql.index("'", i + 1) + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        i += 1
    return sql[start : i - 1]


# --- SQLite replay of 0005_free_tier_100_credits.sql -------------------------
#
# No Postgres is reachable in CI, but SQLite (3.53+) understands the migration's
# core constructs: ``FILTER (WHERE ...)``, ``IS DISTINCT FROM`` and ``UPDATE t
# AS c ... FROM other AS a``. It cannot attach a CTE to an UPDATE, and it rejects
# RETURNING on that statement, so the replay below materialises the two CTEs
# into temp tables. The allowance CTE is taken verbatim from the migration file,
# so the arithmetic under test is the shipped one.


def _pg_db(tmp_db=sqlite3.connect):
    conn = sqlite3.connect(":memory:")
    # ``public.foo`` references in the migration resolve against an attached
    # schema named public.
    conn.execute('ATTACH DATABASE \':memory:\' AS "public"')
    # The migration calls Postgres-only functions; stub them. gen_random_uuid
    # must return a fresh value per call, like the real thing.
    seq = iter(range(1, 1 << 30))
    conn.create_function(
        "gen_random_uuid",
        0,
        lambda: f"{next(seq):032x}",
    )
    conn.create_function("now", 0, lambda: "2024-01-01T00:00:00Z")
    conn.executescript(
        '''
        CREATE TABLE "public".users (id INTEGER PRIMARY KEY, tier VARCHAR(20) NOT NULL);
        CREATE TABLE "public".user_credits (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER NOT NULL CHECK (balance >= 0),
            updated_at TEXT NOT NULL
        );
        CREATE TABLE "public".credit_transactions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        );
        '''
    )
    return conn


def _allowance_rows(conn) -> list[tuple[int, int]]:
    """Run the migration's allowance CTE verbatim."""
    sql = _strip_comments(FREE_TIER_MIGRATION.read_text(encoding="utf-8"))
    body = _cte_body(sql, "allowance")
    conn.execute("DROP TABLE IF EXISTS allowance")
    conn.execute(f"CREATE TEMP TABLE allowance AS {body}")
    return conn.execute(
        "SELECT user_id, starting_credits FROM allowance ORDER BY user_id"
    ).fetchall()


def _apply_free_tier_top_up(conn) -> None:
    """Replay 0005 against ``conn``.

    Mirrors the Postgres statement's three effects: compute the allowance,
    raise balances whose allowance is below 100, then record one grant row
    per topped-up account with reason 'free_tier_100'.
    """
    sql = _strip_comments(FREE_TIER_MIGRATION.read_text(encoding="utf-8"))
    conn.execute("DROP TABLE IF EXISTS allowance")
    conn.execute("DROP TABLE IF EXISTS upgraded")
    conn.execute(f'CREATE TEMP TABLE allowance AS {_cte_body(sql, "allowance")}')
    # ``upgraded`` is the migration's UPDATE ... RETURNING; SQLite needs the
    # update and the returned rows as separate steps.
    conn.execute(
        """
        CREATE TEMP TABLE upgraded AS
        SELECT a.user_id, 100 - a.starting_credits AS granted
        FROM allowance AS a
        WHERE a.starting_credits < 100
        """
    )
    conn.execute(
        """
        UPDATE "public".user_credits AS c
           SET balance = c.balance + (100 - a.starting_credits),
               updated_at = now()
          FROM allowance AS a
         WHERE a.user_id = c.user_id AND a.starting_credits < 100
        """
    )
    conn.execute(
        """
        INSERT INTO "public".credit_transactions
        (id, user_id, amount, reason, created_at)
        SELECT gen_random_uuid(), user_id, granted, 'free_tier_100', now()
        FROM upgraded
        """
    )


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


# Fixture SQL, kept as constants so the statements stay readable at 88 cols.
INS_USERS = 'INSERT INTO "public".users (id, tier) VALUES (?, ?)'
INS_CREDITS = (
    'INSERT INTO "public".user_credits '
    "(user_id, balance, updated_at) VALUES (?, ?, ?)"
)
INS_TX = (
    'INSERT INTO "public".credit_transactions '
    "(id, user_id, amount, reason, created_at) VALUES (?, ?, ?, ?, ?)"
)
SEL_BALANCES = 'SELECT user_id, balance FROM "public".user_credits ORDER BY user_id'
COUNT_GRANTS = (
    'SELECT COUNT(*) FROM "public".credit_transactions'
    " WHERE reason = 'free_tier_100'"
)


def test_free_tier_top_up_raises_old_free_accounts_to_100():
    """A row created under the old 3-credit allowance ends at 100 minus its
    existing trackers, with the grant recorded as one credit transaction."""
    conn = _pg_db()
    conn.executemany(INS_USERS, [(1, "free"), (2, "free")])
    # u1 was created under the old allowance and spent two trackers; one of
    # those transactions carries a NULL reason, which must still count.
    conn.executemany(INS_CREDITS, [(1, 3, "x"), (2, 1, "x")])
    conn.executemany(
        INS_TX,
        [
            ("t1", 1, -1, "tracker_created", "x"),
            ("t2", 1, -1, None, "x"),
            ("t3", 2, -3, "tracker_created", "x"),
        ],
    )

    assert _allowance_rows(conn) == [(1, 5), (2, 4)]

    _apply_free_tier_top_up(conn)

    assert conn.execute(SEL_BALANCES).fetchall() == [(1, 98), (2, 97)]
    grants = conn.execute(
        'SELECT user_id, amount FROM "public".credit_transactions'
        " WHERE reason = 'free_tier_100' ORDER BY user_id"
    ).fetchall()
    assert grants == [(1, 95), (2, 96)]


def test_free_tier_top_up_leaves_paid_and_provisioned_accounts_alone():
    """``WHERE u.tier = 'free'`` excludes paid accounts, and the ``< 100``
    predicate excludes rows already provisioned at the new allowance."""
    conn = _pg_db()
    conn.executemany(INS_USERS, [(1, "paid"), (2, "free")])
    conn.executemany(INS_CREDITS, [(1, 3, "x"), (2, 100, "x")])
    conn.execute(INS_TX, ("t1", 1, -5, "tracker_created", "x"))

    # The paid row is absent from the CTE; the provisioned row computes to 100.
    assert _allowance_rows(conn) == [(2, 100)]

    _apply_free_tier_top_up(conn)

    assert conn.execute(SEL_BALANCES).fetchall() == [(1, 3), (2, 100)]
    assert conn.execute(COUNT_GRANTS).fetchone()[0] == 0


def test_free_tier_top_up_leaves_a_spent_down_new_account_alone():
    """The one case that could silently double-fund: a free account created under
    the *new* allowance that has already used part of it. Its allowance is the
    balance plus the deductions it already made - 100 - so the ``< 100`` predicate
    skips it. A top-up here would hand the same allowance out twice."""
    conn = _pg_db()
    conn.executemany(INS_USERS, [(1, "free"), (2, "free")])
    # Both sit at 60 after 40 tracker deductions. u2 also carries the +100
    # signup grant journaled under this migration's own reason, which the
    # allowance sums out of the way.
    conn.executemany(INS_CREDITS, [(1, 60, "x"), (2, 60, "x")])
    conn.executemany(
        INS_TX,
        [("t%d" % i, 1, -1, "tracker_created", "x") for i in range(40)]
        + [("u%d" % i, 2, -1, "tracker_created", "x") for i in range(40)]
        + [("g1", 2, 100, "free_tier_100", "x")],
    )

    assert _allowance_rows(conn) == [(1, 100), (2, 100)]

    _apply_free_tier_top_up(conn)

    assert conn.execute(SEL_BALANCES).fetchall() == [(1, 60), (2, 60)]
    assert conn.execute(COUNT_GRANTS).fetchone()[0] == 1  # only u2's signup row


def test_free_tier_top_up_is_a_no_op_when_reapplied():
    """The bootstrap re-applies every migration file, so a second run must not
    grant twice: the recorded grant lifts the allowance to exactly 100."""
    conn = _pg_db()
    conn.execute(INS_USERS, (1, "free"))
    conn.execute(INS_CREDITS, (1, 3, "x"))
    conn.execute(INS_TX, ("t1", 1, -2, "tracker_created", "x"))

    _apply_free_tier_top_up(conn)
    first = conn.execute(
        'SELECT balance FROM "public".user_credits WHERE user_id = 1'
    ).fetchone()[0]
    assert first == 98

    _apply_free_tier_top_up(conn)

    assert conn.execute(
        'SELECT balance FROM "public".user_credits WHERE user_id = 1'
    ).fetchone()[0] == first
    assert conn.execute(COUNT_GRANTS).fetchone()[0] == 1


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
