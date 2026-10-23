#!/usr/bin/env bash
set -eu

docker compose exec -T postgres \
  psql -U elhaq -d elhaq \
  -c "SELECT current_user, current_database();"

docker compose exec -T timescaledb \
  psql -U elhaq -d elhaq_ts \
  -c "SELECT current_user, current_database();"