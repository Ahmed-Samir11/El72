Elhaq — Real-time Price Tracking & Deal Detection
===============================================

Overview
--------
Elhaq is a microservices monorepo for real-time price scraping, anomaly detection ("True Deals"), and user alerts (WhatsApp). It's designed for the Egyptian market and follows an event-driven architecture using Redis Streams and Consumer Groups for reliability.

High-level components
- `services/scraper` — Playwright-based producers that push scrape results to `stream:price_ingest`.
- `services/analyzer` — FastAPI Python service (consumer group `cg_analyzer`) that normalizes data, persists price history (TimescaleDB), runs an IsolationForest anomaly detector, and writes aggregated intent events into Postgres (`retailer_analytics`). It publishes confirmed deals to `stream:confirmed_deals`.
- `services/notification` — Node.js/TypeScript notifier (consumer group `cg_notifier`) that reads `stream:confirmed_deals`, deduplicates via Redis keys `alert_sent:{user_id}:{sku}`, and dispatches via 360dialog WhatsApp API.
- `services/billing` — Billing and auth (not scaffolded fully) that validates Paymob/Fawry webhooks and computes dynamic pricing using `config:demand_multiplier` in Redis.

Quick start (local)
1. Copy `.env.example` -> `.env` and adjust values.
2. Start infrastructure and services via Docker Compose:

```bash
docker-compose up --build
```

3. Run analyzer locally (alternative):

```bash
cd services/analyzer
pip install -r requirements.txt
uvicorn services.analyzer.app:app --reload
```

4. Run notifier locally (alternative):

```bash
cd services/notification
npm ci
npm run start
```

Documentation
-------------

Build the Sphinx documentation locally after installing the pinned Python dependencies:

```bash
pip install -r requirements.txt
pip install -r requirements.txt  # ensures sphinx and theme are installed
sphinx-build -b html docs docs/_build/html
```

Open `docs/_build/html/index.html` in your browser to view the generated API docs.

Notes
-----
- A top-level `requirements.txt` is provided with pinned versions used for local development.
- For docs generation, ensure `sphinx` and `sphinx-rtd-theme` are installed (they are included in the top-level requirements).

Key files
- `.github/copilot-instructions.md` — AI agent guidance for working in this repo.
- `services/common/redis_client.py` — Async Redis Streams singleton wrapper used by services.
- `services/analyzer/app.py` — Analyzer FastAPI app with consumer loop, DB pools, ML integration.
- `services/analyzer/ml_detector.py` — IsolationForest scoring helper.
- `services/analyzer/intent_upsert.py` — Upsert logic to `retailer_analytics` (no PII).
- `infra/sql/ddl.sql` — PriceHistory hypertable and `retailer_analytics` DDL and view.
- `infra/sql/alerts.sql` — Alerts table DDL + example rows for testing.
- `docker-compose.yml` — Local dev orchestrator (Redis, Postgres, Timescale, services).
- `.github/workflows/ci.yml` — CI (lint, build, tests placeholder).

How events flow
1. Scraper XADD -> `stream:price_ingest` (payload JSON: sku, store, price, timestamp, html_hash, in_stock).
2. Analyzer XREADGROUP from `stream:price_ingest` (group `cg_analyzer`), persists to timeseries, scores with ML, upserts aggregated retailer analytics (if alert exists), XADD confirmed deals to `stream:confirmed_deals`.
3. Notifier XREADGROUP from `stream:confirmed_deals` (group `cg_notifier`), dedupes and sends WhatsApp alerts.

Security & compliance notes
- Redis must be internal-only and password protected; use `REDIS_URL` env.
- PII must be encrypted at rest (AES-256). `retailer_analytics` must NOT contain user_id or raw PII.
- Paymob/Fawry webhooks must be verified via HMAC before acting.

CI & linting
- GitHub Actions runs Python and Node jobs; `lint-and-tests` job runs `ruff`, `black`, `pytest` (if tests exist) and a TypeScript build check.
- `pyproject.toml` contains `black`/`ruff` config. `services/notification` contains `tsconfig.json` and `.eslintrc.json`.

What the project is missing (before adding features)
These are the high-priority gaps you should address before building additional features so work scales safely and is auditable:

1. Secrets & config management
- Move secrets out of `.env` into a secrets manager (Vault/KeyVault/Secrets Manager) or GitHub Secrets for CI. Ensure `REDIS_URL` and DB credentials are not committed.

2. Production-grade Redis/Postgres/Timescale configuration
- TLS, auth, private networking, capacity sizing, persistence and backups.
- Redis ACLs and user-level credentials.

3. Observability
- Structured logging (JSON) with `trace_id` and `service_name` per request/event.
- Metrics (Prometheus) and health/readiness endpoints for each service.
- Error/reporting pipeline (Sentry or similar).

4. Testing
- Unit tests for `services/common/redis_client.py`, `ml_detector`, and analyzer loop (mock Redis and DB).
- Integration tests using `docker-compose.test.yml` or Testcontainers to validate end-to-end stream processing.

5. ML lifecycle
- Model training pipeline, versioned model artifacts, and a persistence/loading mechanism (do not retrain in-memory each run).
- Offline evaluation and threshold tuning; CI checks for model drift.

6. Message retry & dead-letter handling
- Better handling for messages that repeatedly fail: move to a dead-letter stream/list and alert operators.

7. Data privacy & encryption
- Implement PII encryption at the application layer before DB writes.
- Data retention policies and deletion procedures per PDPL.

8. Authentication & Authorization
- Secure internal APIs, ensure service-to-service auth (mTLS or tokens), and harden public endpoints.

9. CI/CD & release process
- Release pipelines for building, tagging, and deploying images to staging and production.
- Automated DB migrations (Flyway, Alembic, or similar).

10. Service scaffolding gaps
- `services/scraper` producer scaffolding (Playwright + residential proxies + exponential backoff) is missing.
- `services/billing` (billing endpoints, webhook validators wired to user entitlement changes) needs implementation.

11. Monitoring & alerting runbooks
- Define SLOs, set alerts for stream backlog, error rates, message processing latency, and DB connection saturation.

Redis targets & proxy rotation (scraper)
- The scraper now supports pulling targets from Redis streams or lists as an alternative to files. Configure via `SCRAPER_TARGETS_SOURCE`:
	- `file` — default, use `targets_example.json`.
	- `redis_stream` — consume from `SCRAPER_TARGETS_STREAM` (`stream:targets`) with consumer group `cg_scraper`.
	- `redis_list` — consume from `SCRAPER_TARGETS_LIST` (`queue:targets`) using `BLPOP`.

- Proxy rotation: supply a proxy pool via `PROXIES_FILE` (JSON) or `PROXY_SERVER` for a single proxy. The scraper uses a `ProxyPool` that randomly rotates proxies and temporarily blacklists failing proxies to reduce repeated blocking. For production, integrate a managed proxy pool and health checks.

Quick next steps I can implement now
- Add DB migration scripts and example `users` test data.
- Add unit tests for `ml_detector` and `intent_upsert` with mocks.
- Implement dead-letter processing pattern for the analyzer consumer.

Contact / contribution
- Open issues or PRs in this repo. Ask for an architecture walkthrough or request a specific service implementation to prioritize.


---
File locations recap (open in editor):
- `README.md` (this file)
- `services/common/redis_client.py`
- `services/analyzer/app.py`
- `services/analyzer/ml_detector.py`
- `infra/sql/ddl.sql`
- `infra/sql/alerts.sql`

If you want, I can now scaffold tests and DB migrations, or implement the scraper producer with Playwright and residential proxy settings. Which should I do next?