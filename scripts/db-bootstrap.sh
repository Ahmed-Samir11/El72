#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

: "${DATABASE_URL:?Set DATABASE_URL to the PostgreSQL database}"
: "${TIMESCALE_URL:?Set TIMESCALE_URL to the TimescaleDB database}"

apply_file() {
    local url="$1"
    local file="$2"

    if [[ ! -f "$file" ]]; then
        echo "ERROR: SQL file not found: $file" >&2
        return 1
    fi

    echo "Applying $file"
    psql "$url" \
        --set ON_ERROR_STOP=1 \
        --single-transaction \
        --file "$file"
}

# Canonical schema first, then baseline and monitoring role.
apply_file "$DATABASE_URL" \
    infra/sql/schema/postgres.sql

apply_file "$DATABASE_URL" \
    infra/sql/migrations/postgres/0000_baseline.sql

apply_file "$DATABASE_URL" \
    infra/sql/migrations/postgres/0001_monitor_role.sql

apply_file "$DATABASE_URL" \
    infra/sql/migrations/postgres/0002_payment_history_fk_alignment.sql

apply_file "$DATABASE_URL" \
    infra/sql/migrations/postgres/0003_payment_audit_log_action_events.sql

apply_file "$DATABASE_URL" \
    infra/sql/migrations/postgres/0004_schema_compatibility_repairs.sql

# Top up free accounts created under the old 3-credit allowance to 100.
apply_file "$DATABASE_URL" \
    infra/sql/migrations/postgres/0005_free_tier_100_credits.sql

# Legacy operational migrations (flat numbering, pre-subdirectory layout):
# cash payments, cash audit events, admin dispute/refund, and subscriptions.
# These must run AFTER 0003/0004: 0008 and 0010 widen the payment_audit_log
# action CHECK that 0003 establishes, so ordering preserves the widest set.
apply_file "$DATABASE_URL" \
    infra/sql/migrations/0007_cash_payments.sql

apply_file "$DATABASE_URL" \
    infra/sql/migrations/0008_payment_audit_log_cash_events.sql

apply_file "$DATABASE_URL" \
    infra/sql/migrations/0009_admin_dispute_refunds.sql

apply_file "$DATABASE_URL" \
    infra/sql/migrations/0010_subscriptions.sql

# Chatbot result cache plus stable per-session result ordering.
apply_file "$DATABASE_URL" \
    infra/sql/migrations/0011_chatbot_query_cache.sql

# Same sequence for the independent TimescaleDB instance.
apply_file "$TIMESCALE_URL" \
    infra/sql/schema/timescaledb.sql

apply_file "$TIMESCALE_URL" \
    infra/sql/migrations/timescaledb/0000_baseline.sql

# Advertised-price column + (sku, time) index for the fake-discount detector.
apply_file "$TIMESCALE_URL" \
    infra/sql/migrations/timescaledb/0001_price_history_advertised_price.sql

apply_file "$TIMESCALE_URL" \
    infra/sql/migrations/timescaledb/0002_monitor_role.sql

echo "Canonical database bootstrap completed."
echo "Provision monitoring passwords separately."