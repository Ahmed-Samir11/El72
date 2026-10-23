#!/usr/bin/env bash
set -uo pipefail

# Read-only audit: no migrations, no writes, no service restarts.
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || exit 1

PASS=0
WARN=0
FAIL=0

ok()   { printf '  [PASS] %s\n' "$1"; PASS=$((PASS + 1)); }
warn() { printf '  [WARN] %s\n' "$1"; WARN=$((WARN + 1)); }
fail() { printf '  [FAIL] %s\n' "$1"; FAIL=$((FAIL + 1)); }
section() { printf '\n========== %s ==========\n' "$1"; }

# Parse .env without sourcing it. Values are not printed.
declare -A ENVVARS=()
if [[ -f .env ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" != *=* ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    key="$(printf '%s' "$key" | xargs)"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    if [[ ${#value} -ge 2 ]]; then
      if [[ "$value" == \"*\" ]]; then
        value="${value:1:${#value}-2}"
      elif [[ "$value" == \'*\' ]]; then
        value="${value:1:${#value}-2}"
      fi
    fi
    [[ -n "$key" ]] && ENVVARS["$key"]="$value"
  done < .env
else
  fail ".env not found in repository root"
fi

DB_URL="${ENVVARS[DATABASE_URL]:-}"
TS_URL="${ENVVARS[TIMESCALE_URL]:-}"

if [[ -z "$DB_URL" ]]; then
  fail "DATABASE_URL missing from .env"
fi
if [[ -z "$TS_URL" ]]; then
  fail "TIMESCALE_URL missing from .env"
fi

# Execute read-only catalog queries. SQL identifiers and checks are fixed here.
pg_query() {
  psql "$1" -X -q -A -t -v ON_ERROR_STOP=1 -c "$2" 2>/dev/null
}
pg_file_query() {
  psql "$1" -X -q -A -t -v ON_ERROR_STOP=1 -f "$2" 2>/dev/null
}
has_object() {
  local url="$1" sql="$2" label="$3" result
  if ! result="$(pg_query "$url" "$sql")"; then
    fail "$label: query failed"
  elif [[ "$result" == "t" || "$result" == "1" ]]; then
    ok "$label"
  else
    fail "$label"
  fi
}

section "1. Tooling and live database connectivity"

if command -v psql >/dev/null 2>&1; then
  ok "psql installed"
else
  fail "psql not installed"
fi

if command -v docker >/dev/null 2>&1; then
  ok "Docker CLI installed"
  # Read-only container state inspection.
  for c in el72-postgres-1 el72-timescaledb-1; do
    state="$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || true)"
    if [[ "$state" == "running" ]]; then
      ok "$c is running"
    elif [[ -n "$state" ]]; then
      fail "$c state is $state"
    else
      warn "$c container not found by that name"
    fi
  done
else
  warn "Docker CLI unavailable; container state skipped"
fi

if [[ -n "$DB_URL" ]] && pg_query "$DB_URL" "SELECT current_database()"; then
  ok "PostgreSQL connection works"
else
  fail "PostgreSQL connection failed"
fi

if [[ -n "$TS_URL" ]] && pg_query "$TS_URL" "SELECT current_database()"; then
  ok "TimescaleDB connection works"
else
  fail "TimescaleDB connection failed"
fi

section "2. PostgreSQL schema and constraints"

if [[ -n "$DB_URL" ]] && pg_query "$DB_URL" "SELECT 1" >/dev/null; then
  for spec in \
    "users:status" \
    "users:deleted_at" \
    "alerts:sku" \
    "alerts:store_id" \
    "alerts:category" \
    "alerts:desired_price_egp" \
    "alerts:target_price_bucket" \
    "alerts:notify_channel" \
    "tracked_item_stores:last_fetch_status" \
    "tracked_item_stores:last_fetch_error" \
    "current_prices:image_url" \
    "lowest_prices:url" \
    "lowest_prices:image_url" \
    "payment_logs:paymob_order_id" \
    "card_payments:user_id" \
    "wallet_payments:user_id" \
    "payment_audit_log:detail"
  do
    table="${spec%%:*}"
    column="${spec#*:}"
    has_object "$DB_URL" \
      "SELECT EXISTS (
         SELECT 1 FROM information_schema.columns
         WHERE table_schema='public'
           AND table_name='$table' AND column_name='$column'
       )" \
      "public.$table.$column exists"
  done

  has_object "$DB_URL" \
    "SELECT EXISTS (
       SELECT 1 FROM pg_constraint
       WHERE conrelid='public.users'::regclass
         AND conname='users_status_check' AND convalidated
     )" \
    "users_status_check exists and is validated"

  has_object "$DB_URL" \
    "SELECT EXISTS (
       SELECT 1 FROM pg_indexes
       WHERE schemaname='public' AND indexname='idx_users_status'
     )" "idx_users_status exists"

  has_object "$DB_URL" \
    "SELECT EXISTS (
       SELECT 1 FROM pg_indexes
       WHERE schemaname='public' AND indexname='idx_alerts_sku'
     )" "idx_alerts_sku exists"

  has_object "$DB_URL" \
    "SELECT EXISTS (
       SELECT 1 FROM pg_indexes
       WHERE schemaname='public' AND indexname='idx_alerts_notify_channel'
     )" "idx_alerts_notify_channel exists"

  has_object "$DB_URL" \
    "SELECT EXISTS (
       SELECT 1 FROM pg_constraint
       WHERE conrelid='public.payment_audit_log'::regclass
         AND conname='payment_audit_log_action_check'
         AND pg_get_constraintdef(oid) LIKE '%wallet_payment_created%'
         AND pg_get_constraintdef(oid) LIKE '%webhook_duplicate%'
         AND pg_get_constraintdef(oid) LIKE '%staging_rejected%'
     )" "audit action constraint includes current payment events"

  for spec in \
    "card_payments:user_id:users" \
    "wallet_payments:user_id:users" \
    "payment_logs:user_id:users" \
    "manual_payments:user_id:users" \
    "manual_payments:resolved_by:admins" \
    "payment_audit_log:actor_id:admins" \
    "payment_audit_log:target_user_id:users"
  do
    table="${spec%%:*}"
    rest="${spec#*:}"
    column="${rest%%:*}"
    target="${rest#*:}"
    has_object "$DB_URL" \
      "SELECT EXISTS (
         SELECT 1
         FROM pg_constraint c
         JOIN pg_class t ON t.oid=c.conrelid
         JOIN pg_namespace n ON n.oid=t.relnamespace
         WHERE n.nspname='public' AND t.relname='$table'
           AND c.contype='f'
           AND pg_get_constraintdef(c.oid) LIKE
               ('FOREIGN KEY (' || '$column' || ') REFERENCES ' || '$target' || '(id)%')
           AND pg_get_constraintdef(c.oid) LIKE '%ON DELETE SET NULL%'
       )" "$table.$column FK to $target uses ON DELETE SET NULL"
  done

  printf '\n  PostgreSQL key table counts (informational):\n'
  for table in users alerts tracked_items current_prices lowest_prices \
               payment_logs card_payments wallet_payments payment_audit_log; do
    count="$(pg_query "$DB_URL" "SELECT count(*) FROM public.$table" 2>/dev/null || true)"
    if [[ "$count" =~ ^[0-9]+$ ]]; then
      printf '    %-24s %s\n' "$table" "$count"
    else
      warn "Could not count public.$table"
    fi
  done
else
  warn "PostgreSQL catalog checks skipped because connection failed"
fi

section "3. TimescaleDB objects and hypertables"

if [[ -n "$TS_URL" ]] && pg_query "$TS_URL" "SELECT 1" >/dev/null; then
  for spec in \
    "public:price_history" \
    "analytics:dim_channel" \
    "analytics:dim_date" \
    "analytics:dim_product" \
    "analytics:dim_retailer" \
    "analytics:dim_time" \
    "analytics:dim_user" \
    "analytics:dim_promotion" \
    "analytics:fact_price_history" \
    "analytics:fact_deal" \
    "analytics:fact_notification"
  do
    schema="${spec%%:*}"
    table="${spec#*:}"
    has_object "$TS_URL" \
      "SELECT EXISTS (
         SELECT 1 FROM information_schema.tables
         WHERE table_schema='$schema' AND table_name='$table'
       )" "$schema.$table exists"
  done

  has_object "$TS_URL" \
    "SELECT EXISTS (
       SELECT 1 FROM timescaledb_information.hypertables
       WHERE hypertable_schema='public' AND hypertable_name='price_history'
     )" "public.price_history is a hypertable"

  has_object "$TS_URL" \
    "SELECT EXISTS (
       SELECT 1 FROM timescaledb_information.hypertables
       WHERE hypertable_schema='analytics' AND hypertable_name='fact_price_history'
     )" "analytics.fact_price_history is a hypertable"

  printf '\n  TimescaleDB table counts (informational):\n'
  for spec in public.price_history analytics.fact_price_history \
              analytics.fact_deal analytics.fact_notification \
              analytics.dim_channel analytics.dim_product \
              analytics.dim_retailer analytics.dim_date; do
    schema="${spec%%.*}"
    table="${spec#*.}"
    count="$(pg_query "$TS_URL" "SELECT count(*) FROM \"$schema\".\"$table\"" 2>/dev/null || true)"
    if [[ "$count" =~ ^[0-9]+$ ]]; then
      printf '    %-32s %s\n' "$spec" "$count"
      if [[ "$count" == "0" && "$table" != "dim_channel" ]]; then
        : # Empty tables are reported, not assumed broken.
      fi
    else
      warn "Could not count $spec"
    fi
  done

  printf '\n  Continuous aggregates:\n'
  caggs="$(pg_query "$TS_URL" \
    "SELECT count(*) FROM timescaledb_information.continuous_aggregates" 2>/dev/null || true)"
  if [[ "$caggs" =~ ^[0-9]+$ ]]; then
    printf '    %s registered\n' "$caggs"
    [[ "$caggs" == "0" ]] && warn "No continuous aggregates registered; confirm this is intentional"
  else
    warn "Could not query continuous aggregates"
  fi
else
  warn "TimescaleDB catalog checks skipped because connection failed"
fi

section "4. Bootstrap wiring and migration files"

required_files=(
  infra/sql/schema/postgres.sql
  infra/sql/schema/timescaledb.sql
  infra/sql/migrations/postgres/0000_baseline.sql
  infra/sql/migrations/postgres/0001_monitor_role.sql
  infra/sql/migrations/postgres/0002_payment_history_fk_alignment.sql
  infra/sql/migrations/postgres/0003_payment_audit_log_action_events.sql
  infra/sql/migrations/postgres/0004_schema_compatibility_repairs.sql
  infra/sql/migrations/timescaledb/0000_baseline.sql
  infra/sql/migrations/timescaledb/0001_monitor_role.sql
  scripts/db-bootstrap.sh
)

for f in "${required_files[@]}"; do
  if [[ -s "$f" ]]; then
    ok "$f exists and is non-empty"
  else
    fail "$f missing or empty"
  fi
done

if [[ -f scripts/db-bootstrap.sh ]]; then
  for f in \
    infra/sql/schema/postgres.sql \
    infra/sql/migrations/postgres/0000_baseline.sql \
    infra/sql/migrations/postgres/0001_monitor_role.sql \
    infra/sql/migrations/postgres/0002_payment_history_fk_alignment.sql \
    infra/sql/migrations/postgres/0003_payment_audit_log_action_events.sql \
    infra/sql/migrations/postgres/0004_schema_compatibility_repairs.sql \
    infra/sql/schema/timescaledb.sql \
    infra/sql/migrations/timescaledb/0000_baseline.sql \
    infra/sql/migrations/timescaledb/0001_monitor_role.sql
  do
    if grep -Fq "$f" scripts/db-bootstrap.sh; then
      ok "bootstrap references $f"
    else
      fail "bootstrap does not reference $f"
    fi
  done

  if grep -Eq 'ON_ERROR_STOP=1' scripts/db-bootstrap.sh; then
    ok "bootstrap stops on SQL errors"
  else
    fail "bootstrap does not enable ON_ERROR_STOP"
  fi
  if grep -Eq -- '--single-transaction| -1([[:space:]]|$)' scripts/db-bootstrap.sh; then
    ok "bootstrap wraps each SQL file in a transaction"
  else
    warn "Could not confirm per-file transaction wrapping from script text"
  fi
else
  fail "scripts/db-bootstrap.sh missing"
fi

section "5. Rerun-safety scan (static, not execution)"

# Flag suspicious statements for review. This is a heuristic, not a SQL parser.
scan_files=(
  infra/sql/schema/postgres.sql
  infra/sql/schema/timescaledb.sql
  infra/sql/migrations/postgres/0000_baseline.sql
  infra/sql/migrations/postgres/0001_monitor_role.sql
  infra/sql/migrations/postgres/0002_payment_history_fk_alignment.sql
  infra/sql/migrations/postgres/0003_payment_audit_log_action_events.sql
  infra/sql/migrations/postgres/0004_schema_compatibility_repairs.sql
  infra/sql/migrations/timescaledb/0000_baseline.sql
  infra/sql/migrations/timescaledb/0001_monitor_role.sql
)

found_risks=0
for f in "${scan_files[@]}"; do
  [[ -f "$f" ]] || continue
  matches="$(grep -nEi \
    '^[[:space:]]*(CREATE (TABLE|INDEX|ROLE|USER|SCHEMA|EXTENSION)|ALTER TABLE .* ADD CONSTRAINT|DROP TABLE|DROP SCHEMA|TRUNCATE|DELETE FROM|UPDATE [^;]+;|INSERT INTO)' \
    "$f" 2>/dev/null || true)"
  if [[ -n "$matches" ]]; then
    printf '\n  Review statements in %s:\n%s\n' "$f" "$matches"
    found_risks=$((found_risks + 1))
  fi
done

if [[ "$found_risks" -eq 0 ]]; then
  ok "no obvious DDL/DML patterns flagged by static scan"
else
  warn "static scan flagged statements for manual idempotency review; flags are not proof of a problem"
fi

section "6. Git whitespace and final summary"

if git diff --check; then
  ok "git diff --check passed"
else
  fail "git diff --check reported whitespace errors"
fi

printf '\n========== SUMMARY ==========\n'
printf 'PASS: %s\nWARN: %s\nFAIL: %s\n' "$PASS" "$WARN" "$FAIL"
printf '\nNo migrations were executed by this audit.\n'
printf 'A zero exit code means no checks failed; warnings may still need review.\n'

[[ "$FAIL" -eq 0 ]]
