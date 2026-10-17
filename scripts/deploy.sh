#!/usr/bin/env bash
#
# Deploy El72 to a single production server.
#
# Prerequisites on the server:
#   - docker + docker compose installed
#   - this repo cloned (the directory containing this script is the repo root)
#   - a .env file with all production secrets (see docs/production-deployment.md)
#   - DNS resolved for PROD_DOMAIN and API_DOMAIN (Caddy provisions TLS via ACME)
#
# Required env (or present in .env):
#   API_DOMAIN — used for the post-deploy health check

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.."
cd "$DIR"

if [ ! -f .env ]; then
  echo "[deploy] .env is missing - copy .env.example and fill in production secrets" >&2
  exit 1
fi

# Read API_DOMAIN from the env file without exporting secrets to the shell
# environment (avoids leaking them into the process list). Strip surrounding
# quotes so values like API_DOMAIN="api.el72.io" are handled correctly.
API_DOMAIN=$(grep '^API_DOMAIN=' .env | cut -d= -f2- | sed 's/^"//;s/"$//')

echo "[deploy] pulling latest main"
git pull --ff-only origin main

echo "[deploy] building and starting the production stack"
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env up -d --build

echo "[deploy] waiting for API health at https://${API_DOMAIN}/health"
for i in $(seq 1 12); do
  if curl -fsS "https://${API_DOMAIN}/health" >/dev/null 2>&1; then
    echo "[deploy] API healthy"
    exit 0
  fi
  sleep 5
done

echo "[deploy] API did not become healthy" >&2
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=50 api >&2
exit 1
