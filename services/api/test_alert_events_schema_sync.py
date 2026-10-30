"""Drift test: ``alert_events`` must agree across schema, migration, ORM and consumer.

Three artifacts describe one table: the canonical PostgreSQL schema, the
migration that upgrades deployed trees, and the SQLAlchemy model the API writes
through — plus the consumer's own event-type set, which is what decides what
rows the CHECK allows in the first place. A pair that must stay in lockstep
gets a test, not a comment (AGENTS), so this file fails when any one of the
four drifts.
"""

import re
from pathlib import Path

from services.api.alert_events_consumer import VALID_EVENT_TYPES
from services.api.models import AlertEvent

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL = REPO_ROOT / "infra" / "sql" / "schema" / "postgres.sql"
MIGRATION_SQL = REPO_ROOT / "infra" / "sql" / "migrations" / "0013_alert_events.sql"
BOOTSTRAP = REPO_ROOT / "scripts" / "db-bootstrap.sh"

_CONSTRAINT_STARTS = (
    "check",
    "primary key",
    "unique",
    "foreign key",
    "constraint",
    "exclude",
)


def _strip_comments(sql: str) -> str:
    """Drop -- line comments so only executable SQL remains."""
    return "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )


def _table_body(sql: str, table: str) -> str:
    """Return the body of ``CREATE TABLE ... <table> (``, comments stripped.

    Comments are removed BEFORE the body is located: a comment inside the table
    (which this schema uses to explain each column's meaning) would otherwise
    be mistaken for another column definition.
    """
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS {table}\s*\((.*?)\n\);",
        _strip_comments(sql),
        re.DOTALL,
    )
    assert match, f"{table} table not found"
    return match.group(1)


def _top_level_parts(body: str) -> list[str]:
    """Split a table body into column/constraint fragments.

    Commas inside ``NUMERIC(12, 2)``, ``REFERENCES users(id)`` or a wrapped
    ``CHECK (x IN (..))`` are NOT separators, so the split tracks parenthesis
    depth and quotes — otherwise a two-line CHECK becomes two phantom columns
    and the drift test passes for the wrong reason.
    """
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    in_quote = False
    for char in body:
        if char == "'":
            in_quote = not in_quote
            current.append(char)
            continue
        if not in_quote:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char == "," and depth == 0:
                parts.append("".join(current))
                current = []
                continue
        current.append(char)
    parts.append("".join(current))
    return [re.sub(r"\s+", " ", part).strip() for part in parts if part.strip()]


def _columns(sql: str, table: str) -> set[str]:
    names = set()
    for part in _top_level_parts(_table_body(sql, table)):
        if any(part.lower().startswith(keyword) for keyword in _CONSTRAINT_STARTS):
            continue
        names.add(part.split()[0])
    return names


def _quoted_values(sql: str, column: str) -> set[str]:
    """The value set a column's CHECK allows, e.g. event_type IN (...).

    The schema is searched with whitespace collapsed, so a CHECK wrapped over
    two lines still matches once.
    """
    pattern = rf"{column}[^,]*?IN\s*\((.*?)\)"
    match = re.search(pattern, _normalize(sql), re.DOTALL)
    assert match, f"no CHECK value list for {column}"
    return {value.strip(" '\"") for value in match.group(1).split(",")}


def _normalize(sql: str) -> str:
    """Collapse a CHECK's wrapped lines so one logical clause matches once."""
    return re.sub(r"\s+", " ", _strip_comments(sql))


# --- the table itself --------------------------------------------------------


def test_alert_events_columns_match_across_schema_migration_and_orm():
    schema = SCHEMA_SQL.read_text(encoding="utf-8")
    migration = MIGRATION_SQL.read_text(encoding="utf-8")
    orm_columns = {column.name for column in AlertEvent.__table__.columns}

    schema_columns = _columns(schema, "alert_events")
    migration_columns = _columns(migration, "alert_events")

    assert schema_columns == migration_columns, "schema and migration disagree"
    assert schema_columns == orm_columns, (
        f"ORM vs canonical schema: only-ORM={orm_columns - schema_columns} "
        f"only-schema={schema_columns - orm_columns}"
    )
    # Named for what they hold: the app displays EGP, so a price column says so.
    assert {"price_egp", "reference_price_egp", "discount_pct"} <= orm_columns
    assert "opened_at" in orm_columns, "Gate 2 needs the seen/not-seen column"


def test_alert_events_event_type_vocabulary_is_one_set_everywhere():
    """The consumer only writes types the CHECK allows, from one shared set."""
    schema = SCHEMA_SQL.read_text(encoding="utf-8")
    migration = MIGRATION_SQL.read_text(encoding="utf-8")

    allowed = _quoted_values(schema, "event_type")
    assert allowed == _quoted_values(migration, "event_type")
    assert (
        allowed == VALID_EVENT_TYPES
    ), f"consumer={VALID_EVENT_TYPES} schema={allowed}"
    # The emitter in services/scraper/alert_emitter.py produces exactly these
    # four; a fifth AlertType there without a CHECK entry here would silently
    # become an unsupported_event_type counter.
    assert allowed == {
        "price_drop",
        "threshold_crossed",
        "lowest_price_changed",
        "back_in_stock",
    }


def test_alert_events_channel_can_only_claim_a_channel_that_delivered_it():
    """channel is a claim about delivery, so the set is pinned, not free text.

    'in_app' is what this build can deliver; 'push'/'whatsapp' are allowed by
    the CHECK for the day those senders ship, and a row must never be written
    with a channel that did not send anything.
    """
    schema = SCHEMA_SQL.read_text(encoding="utf-8")
    migration = MIGRATION_SQL.read_text(encoding="utf-8")

    assert _quoted_values(schema, "channel") == _quoted_values(migration, "channel")
    assert _quoted_values(schema, "channel") == {"in_app", "push", "whatsapp"}
    assert "channel TEXT NOT NULL DEFAULT 'in_app'" in _normalize(schema)


# --- retention, indexes, trigger ---------------------------------------------


def test_alert_events_user_fk_cascades_and_is_declared_identically():
    """An alert feed is the user's own derived data: CASCADE, not SET NULL.

    The opposite of affiliate_clicks (a click is market KPI data and survives
    user deletion); if this ever flips, deleting an account would leave a
    feed nobody can read and a KPI nobody can attribute.
    """
    for path in (SCHEMA_SQL, MIGRATION_SQL):
        body = _table_body(path.read_text(encoding="utf-8"), "alert_events")
        assert (
            "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE"
            in _normalize(body)
        )
        assert "SET NULL" not in _normalize(body)

    orm_fk = AlertEvent.__table__.columns["user_id"].foreign_keys
    assert len(orm_fk) == 1
    fk = next(iter(orm_fk))
    assert fk.ondelete == "CASCADE"


def test_alert_events_indexes_and_trigger_are_declared_everywhere():
    """The reads the surface performs must have an index in the same name set."""
    expected_indexes = {
        "idx_alert_events_user_time",
        "idx_alert_events_item_time",
        "idx_alert_events_user_opened",
    }
    for path in (SCHEMA_SQL, MIGRATION_SQL):
        text = path.read_text(encoding="utf-8")
        found = set(re.findall(r"CREATE INDEX IF NOT EXISTS (\w+)", text))
        assert (
            expected_indexes <= found
        ), f"{path.name} misses {expected_indexes - found}"
        assert (
            "update_alert_events_updated_at" in text
        ), f"{path.name} must attach the shared updated_at trigger"

    orm_indexes = {index.name for index in AlertEvent.__table__.indexes}
    assert expected_indexes <= orm_indexes


def test_bootstrap_applies_the_alert_events_migration():
    """A deployed tree gets the table only if the bootstrap runs the file."""
    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert "infra/sql/migrations/0013_alert_events.sql" in text
