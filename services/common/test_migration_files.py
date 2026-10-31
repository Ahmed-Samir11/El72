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
    "migrations/0011_chatbot_query_cache.sql",
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
    conn.executescript('''
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
        ''')
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
    conn.execute("""
        CREATE TEMP TABLE upgraded AS
        SELECT a.user_id, 100 - a.starting_credits AS granted
        FROM allowance AS a
        WHERE a.starting_credits < 100
        """)
    conn.execute("""
        UPDATE "public".user_credits AS c
           SET balance = c.balance + (100 - a.starting_credits),
               updated_at = now()
          FROM allowance AS a
         WHERE a.user_id = c.user_id AND a.starting_credits < 100
        """)
    conn.execute("""
        INSERT INTO "public".credit_transactions
        (id, user_id, amount, reason, created_at)
        SELECT gen_random_uuid(), user_id, granted, 'free_tier_100', now()
        FROM upgraded
        """)


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

    assert (
        conn.execute(
            'SELECT balance FROM "public".user_credits WHERE user_id = 1'
        ).fetchone()[0]
        == first
    )
    assert conn.execute(COUNT_GRANTS).fetchone()[0] == 1


def test_affiliate_attribution_keeps_click_history_on_user_delete():
    """affiliate_clicks is Gate 3/4 KPI data, not PII: the user FK must be
    ON DELETE SET NULL in the canonical schema, the fresh-add column and the
    repair block of the migration, and never CASCADE. A tree that already
    recorded the first draft's CASCADE FK is repaired (drop non-SET NULL FKs,
    add exactly one SET NULL FK)."""
    schema = _strip_comments(
        (INFRA_SQL / "schema/postgres.sql").read_text(encoding="utf-8")
    )
    migration = _strip_comments(
        (INFRA_SQL / "migrations" / "0012_affiliate_click_attribution.sql").read_text(
            encoding="utf-8"
        )
    )
    assert "user_id INTEGER REFERENCES users(id) ON DELETE SET NULL" in schema
    # Fresh ADD must match the schema's retention rule...
    assert "REFERENCES users(id) ON DELETE SET NULL" in migration
    # ...and the repair block converges on EXACTLY one SET NULL FK: every
    # pre-existing FK from affiliate_clicks to users is dropped (CASCADE
    # drafts, NO ACTION, duplicates), then one SET NULL constraint is re-added.
    assert "DROP CONSTRAINT" in migration
    assert "ADD CONSTRAINT fk_affiliate_clicks_user_id" in migration
    # Orphaned user_id rows must be neutralized before ADD CONSTRAINT, or
    # the migration aborts on real deployed data.
    assert "SET user_id = NULL" in migration
    table_body = schema[schema.index("affiliate_clicks (") :]
    assert (
        "ON DELETE CASCADE" not in table_body.split(");")[0]
    ), "affiliate_clicks table body must not carry a CASCADE FK"


def test_affiliate_attribution_source_is_not_null_everywhere():
    """source is the CTR metric dimension: fresh schema, migration ADD and
    the in-place upgrade (create_tables) all declare NOT NULL DEFAULT 'unknown',
    and the migration backfills NULL rows left by older upgrade paths."""
    schema = (INFRA_SQL / "schema/postgres.sql").read_text(encoding="utf-8")
    migration = (
        INFRA_SQL / "migrations/0012_affiliate_click_attribution.sql"
    ).read_text(encoding="utf-8")
    from services.api import create_tables

    assert "source VARCHAR(32)" in schema and "NOT NULL DEFAULT 'unknown'" in schema
    assert "source VARCHAR(32)" in migration
    assert "NOT NULL DEFAULT 'unknown'" in migration
    assert "SET source = 'unknown' WHERE source IS NULL" in migration
    assert "SET NOT NULL" in migration
    specs = {
        spec
        for table, column, spec in create_tables._REQUIRED_COLUMNS
        if (table, column) == ("affiliate_clicks", "source")
    }
    assert specs == {"TEXT NOT NULL DEFAULT 'unknown'"}
    common = "\n".join(create_tables._AFFILIATE_UPGRADES_COMMON)
    assert "SET source = 'unknown' WHERE source IS NULL" in common


def test_affiliate_rename_guard_and_legacy_index_cleanup():
    """The clicked_at rename must be guarded on BOTH sides (old present AND
    new absent) and must drop the legacy-named index so migrated trees keep
    only the canonical idx_affiliate_clicks_created_at."""
    migration = _strip_comments(
        (INFRA_SQL / "migrations" / "0012_affiliate_click_attribution.sql").read_text(
            encoding="utf-8"
        )
    )
    assert "DROP INDEX IF EXISTS idx_affiliate_clicks_clicked_at" in migration
    assert "CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_created_at" in migration
    assert "column_name = 'clicked_at'" in migration
    assert "NOT EXISTS" in migration and "column_name = 'created_at'" in migration
    # create_tables' in-place upgrade must drop the same legacy index.
    from services.api import create_tables

    assert (
        "DROP INDEX IF EXISTS idx_affiliate_clicks_clicked_at"
        in create_tables._AFFILIATE_UPGRADES_COMMON
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


def test_the_backfill_only_touches_unstamped_sessions():
    """Legacy re-ranking must be decided by the search id, never by position.

    The service writes position 0 for the first result of *every* search, so a
    row sitting at the default position may be a live one — the old heuristic
    ("max position in the session is still 0") would re-rank and re-stamp a
    session whose searches each returned a single row. Only rows with no search
    id are ranked, and only in a session that has no grouped rows at all, which
    makes a rerun of the migration a no-op.
    """
    migration = (INFRA_SQL / "migrations/0011_chatbot_query_cache.sql").read_text(
        encoding="utf-8"
    )
    body = _strip_comments(migration)

    assert re.search(
        r"UPDATE\s+chat_search_results", body, re.IGNORECASE
    ), "legacy rows should be re-ranked"
    assert "ROW_NUMBER() OVER" in body.upper()

    assert re.search(
        r"WHERE search_id IS NULL", body, re.IGNORECASE
    ), "only unstamped rows should be ranked"
    assert re.search(
        r"target\.search_id IS NULL", body, re.IGNORECASE
    ), "a stamped row must never be rewritten"
    assert re.search(
        r"NOT EXISTS \(\s*SELECT 1\s+FROM chat_search_results AS live\s+"
        r"WHERE live\.session_id = target\.session_id\s+AND live\.search_id "
        r"IS NOT NULL\s*\)",
        body,
        re.IGNORECASE,
    ), "a session that already has grouped rows must be skipped entirely"
    assert (
        "session_max_position" not in body
    ), "position must not be used to identify a legacy row"


def test_legacy_rows_are_stamped_with_a_search_id():
    """Ordinal resolution reads the newest search group, so old rows need an id.

    A session can hold several searches and every search restarts at position 0,
    which is why position alone cannot identify the list the user is looking at.
    Rows written before migration 0011 have no search id; if the migration left
    them NULL the service's grouped read would never see them, so the same
    statement stamps an old session's rows with one deterministic id.
    """
    migration = (INFRA_SQL / "migrations/0011_chatbot_query_cache.sql").read_text(
        encoding="utf-8"
    )
    schema = (INFRA_SQL / "schema/postgres.sql").read_text(encoding="utf-8")
    body = _strip_comments(migration)

    assert re.search(
        r"ADD COLUMN IF NOT EXISTS search_id UUID", body, re.IGNORECASE
    ), "0011 should add the search id column"
    assert re.search(
        r"search_id UUID", schema, re.IGNORECASE
    ), "search_id is missing from schema/postgres.sql"

    assert re.search(
        r"SET search_id = ranked\.legacy_search_id", body, re.IGNORECASE
    ), "legacy rows should receive a search id"
    assert re.search(
        r"md5\(session_id::text", body, re.IGNORECASE
    ), "the legacy id must come from the session, so it is stable per session"

    assert re.search(
        r"ON chat_search_results \(session_id, search_id, position\)",
        body,
        re.IGNORECASE,
    ), "the grouped read needs the (session, search, position) index"
    assert re.search(
        r"DROP INDEX IF EXISTS idx_chat_search_results_session_position",
        body,
        re.IGNORECASE,
    ), "the superseded pair index should not linger as write overhead"


def test_sql_files_parse_as_postgres():
    """Every schema and migration file has to parse as PostgreSQL.

    The bootstrap applies each file with ``psql --single-transaction``, so one
    malformed statement rolls the whole file back and the deployment comes up
    half-migrated — a broken migration is a production outage, not a lint nit.
    sqlglot's postgres dialect catches it here; it is a test-only dependency
    (declared in requirements-test.txt) because no service imports it.
    """
    import sqlglot

    # psql interpolates this helper's :'monitor_password' variable, so it is
    # not plain SQL and cannot be parsed by a SQL parser.
    skipped = {"provision_monitor_password.sql"}

    for path in sorted(INFRA_SQL.rglob("*.sql")):
        if path.name in skipped:
            continue
        sql = path.read_text(encoding="utf-8")
        parsed = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
        if not parsed:
            # A file with nothing but comments (or empty) parses to nothing,
            # which is fine; anything else must produce a statement.
            assert not _strip_comments(
                sql
            ).strip(), f"{path} contains SQL that does not parse as PostgreSQL"


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
            "idx_chat_search_results_session_search" in sql
        ), f"{name} should index ordinal lookups by (session_id, search_id, position)"
    assert (
        "expires_at_epoch DOUBLE PRECISION" not in migration
    ), "the migrated column should not fall back to a float expiry"
    assert (
        "expires_at_epoch DOUBLE PRECISION" not in schema
    ), "the fresh column should not fall back to a float expiry"


def test_the_expiry_retype_is_conditional():
    """A fresh database must not pay for a rewrite it does not need.

    The migration keeps the retype for deployments whose earlier revision
    created a floating-point expiry, but it has to check the catalog first:
    schema/postgres.sql already declares BIGINT, so an unconditional ALTER
    would lock and rewrite the cache table on every bootstrap.
    """
    migration = (INFRA_SQL / "migrations/0011_chatbot_query_cache.sql").read_text(
        encoding="utf-8"
    )

    assert (
        "information_schema.columns" in migration
    ), "the retype should be guarded on the live column type"
    assert re.search(
        r"DO\s+\$\$", migration, re.IGNORECASE
    ), "the guard should be a conditional block"
    assert re.search(
        r"ALTER\s+COLUMN\s+expires_at_epoch\s+TYPE\s+BIGINT",
        migration,
        re.IGNORECASE,
    ), "the migration should still repair an older float column"
