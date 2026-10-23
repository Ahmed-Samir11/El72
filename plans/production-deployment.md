# Plan: Production Deployment Path (TLS + Compose Overlay + Deploy Pipeline)

**Branch:** `feat/production-deployment` (off `main`)
**Goal:** Make El72 deployable as a production stack on a single server:
TLS-terminated reverse proxy, hardened compose overlay that requires all
secrets, and a CI-backed deploy pipeline. No Terraform/k8s — one compose
stack behind Caddy.

## Gap

The app lacks a production deployment path: `docker-compose.prod.yml` is
referenced by the README but does not exist; there is no domain/TLS
termination, no staging, and no backend deploy pipeline (CI only builds the
Flutter AAB). The whole system is a single local compose stack with exposed
DB ports, open CORS, and untrusted rate-limiting keys behind any proxy.

## Approach

1. **`docker-compose.prod.yml`** — production overlay (merged on top of
   `docker-compose.yml`):
   - Every secret required via `${VAR:?...}` (DB passwords, monitor password,
     Grafana password, JWT secret, admin credentials, Paymob/HMAC/checkout,
     WhatsApp token + phone ID, ACME email).
   - `MOCK_WHATSAPP=false`, `DEMO_MODE=false` defaults.
   - redis/postgres/timescaledb have **no host ports** (internal network
     only); api/frontend-web/caddy expose 80/443.
   - Caddy service: automatic HTTPS on `${PROD_DOMAIN}` (landing page) and
     `${API_DOMAIN}` (API); reverse proxy `/` → frontend-web, `/api/*` →
     api. Wait — API is root-path, so use two hosts: `{$PROD_DOMAIN}` serves
     the static landing page, `{$API_DOMAIN}` → api:8000.
   - Log rotation limits; restart policies.
2. **`frontend/Dockerfile`** — multi-stage: build Vite site, serve with nginx.
3. **`Caddyfile`** — auto-HTTPS; `{$PROD_DOMAIN}` → frontend-web static files;
   `{$API_DOMAIN}` → api:8000.
4. **`scripts/deploy.sh`** — server-side: `git pull`, `docker compose -f
   docker-compose.yml -f docker-compose.prod.yml up -d --build`, then poll
   `https://${API_DOMAIN}/health`.
5. **`.github/workflows/deploy.yml`** — on `v*` tags and push to `main`:
   SSH to `${DEPLOY_HOST}` as `${DEPLOY_USER}` (secrets: `DEPLOY_SSH_*`) and
   run `scripts/deploy.sh`.
6. **API hardening** (`services/api/main.py`):
   - Rate limiter key reads `X-Forwarded-For` only when the direct peer is in
     env-configured `TRUSTED_PROXIES` (mirrors `services/api/routers/payment.py`).
   - CORS origins from `ALLOWED_ORIGINS` env (dev fallback keeps current
     localhost list; prod must configure real origins — no `*`).
7. **Billing** (`services/billing/main.py`): add `GET /health` (billing had
   none; README claims all services expose health).
8. **`docs/production-deployment.md`** — runbook: server prerequisites,
   env file, deploy commands, health checks.
9. **CI** (`.github/workflows/ci.yml`): new `compose-config` job validates
   `docker compose -f docker-compose.yml config` and the prod overlay with a
   complete fake env (must pass), and asserts the prod overlay **fails**
   without required secrets. Add `shellcheck` for `scripts/*.sh`.

## Files touched

- [NEW] `plans/production-deployment.md` (this plan)
- [NEW] `docker-compose.prod.yml`
- [NEW] `frontend/Dockerfile`
- [NEW] `frontend/.gitignore`
- [NEW] `Caddyfile`
- [NEW] `scripts/deploy.sh`
- [NEW] `.github/workflows/deploy.yml`
- [NEW] `docs/production-deployment.md`
- [MODIFY] `services/api/main.py` (trusted-proxy rate limit + CORS)
- [MODIFY] `services/billing/main.py` (add /health)
- [MODIFY] `.github/workflows/ci.yml` (compose-config job)

## Test strategy

- `docker compose -f docker-compose.yml config --quiet` with a fake env file
  (passes).
- `docker compose -f docker-compose.yml -f docker-compose.prod.yml config`
  with secrets stripped → must exit non-zero.
- Same with full fake env → passes.
- `pytest services/api/test_main.py` (rate-limiter behaviour unchanged for
  direct peers).
- `bash -n scripts/deploy.sh`; shellcheck if available.

## Verification checklist (prod)

- [ ] `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`
  starts with a complete `.env`.
- [ ] Stack fails to start when any required secret is unset.
- [ ] `https://${API_DOMAIN}/health` returns 200 through Caddy.
- [ ] Rate limiting keys use the real client IP behind Caddy
  (`TRUSTED_PROXIES=${CADDY_IP}`).
- [ ] Deploy pipeline runs on `v*` tag and publishes the release.
