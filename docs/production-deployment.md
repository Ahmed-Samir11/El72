# Production Deployment Runbook

El72 is deployed as a single-server Docker Compose stack with automatic
HTTPS termination by Caddy. There is no Kubernetes/Terraform dependency.

## 1. Server prerequisites

- Ubuntu/Debian server with **docker** and **docker compose** installed.
- DNS entries resolving `PROD_DOMAIN` and `API_DOMAIN` to the server's IP
  (Caddy provisions TLS certificates via ACME, port 80 must be reachable).
- The repo cloned at `/opt/el72` (or wherever `scripts/deploy.sh` lives).

## 2. Environment file

Copy `.env.example` to `.env` and fill in every value marked `:?` in
`docker-compose.prod.yml`:

```env
# Databases
POSTGRES_PASSWORD=<strong>
DB_MONITOR_PASSWORD=<strong>
GRAFANA_ADMIN_PASSWORD=<strong>

# Application
SECRET_KEY=<strong>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<strong>
ADMIN_SECRET_KEY=<strong>

# Payments
PAYMOB_HMAC_SECRET=<strong>
PAYMOB_CHECKOUT_URL=https://...
PAYMOB_API_KEY=<strong>

# Notifications (whatsapp service — Meta Cloud API)
WHATSAPP_ACCESS_TOKEN=<strong>
WHATSAPP_PHONE_NUMBER_ID=<strong>

# Caddy / TLS
ACME_EMAIL=admin@example.com
PROD_DOMAIN=el72.io
API_DOMAIN=api.el72.io

# Hardening (optional)
TRUSTED_PROXIES=<caddy container IP>
ALLOWED_ORIGINS=https://el72.io
MOCK_WHATSAPP=false
DEMO_MODE=false
```

`TRUSTED_PROXIES` makes the API rate limiter honor `X-Forwarded-For` from
Caddy. Without it, all requests arrive from Caddy's socket peer and the
per-IP limit becomes a shared global quota.

## 3. Deploy

```bash
# On the server
cd /opt/el72
git pull --ff-only origin main
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Or use the CI pipeline: push to `main` or tag a release `v*` — the
`deploy` workflow SSHs into the server (`DEPLOY_HOST`, `DEPLOY_USER`,
`DEPLOY_SSH_PRIVATE_KEY` secrets) and runs `scripts/deploy.sh`, which pulls,
builds, starts the stack, and polls `https://API_DOMAIN/health`.

## 4. Health checks

```bash
curl -fsS https://API_DOMAIN/health          # API
curl -fsS https://PROD_DOMAIN/               # landing page
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

## 5. What changed for production

| Item | Change |
|------|--------|
| `docker-compose.prod.yml` | Overlay: all secrets `:?`, DBs internal-only, Caddy TLS, static frontend, legacy notifier disabled |
| `Caddyfile` | Automatic HTTPS on `PROD_DOMAIN` (landing) and `API_DOMAIN` (API) |
| `frontend/Dockerfile` | Builds the Vite landing page, serves with nginx |
| `services/api/main.py` | Rate-limit key trusts `X-Forwarded-For` only from configured peers; CORS from `ALLOWED_ORIGINS` allowlist |
| `services/billing/main.py` | Added `GET /health` |
| `.github/workflows/deploy.yml` | CI-deployed to the server on `main` pushes and `v*` tags |
| CI `compose-config` job | Validates dev + prod compose; asserts prod fails without secrets |

## 6. Secrets rotation

The WhatsApp token and Paymob credentials must be rotated if ever leaked
(git history is public). Rotate in the provider dashboard, update `.env`,
and redeploy: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`.
