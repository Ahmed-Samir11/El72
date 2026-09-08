# El72 (Elhaq) — Agent Rules & Conventions

## Project Identity

El72 (Elhaq) is a **real-time price tracking & deal detection platform** for the Egyptian e-commerce market. It monitors prices across Amazon Egypt, Noon, and Jumia, detects anomalies with ML, and notifies users via WhatsApp.

---

## Architecture — Hard Boundaries

| Principle | Rule |
|-----------|------|
| **Communication** | Redis Streams **only** (`XADD`, `XREADGROUP`, `XACK`). Never use Redis Pub/Sub. |
| **Monorepo layout** | All backend services live under `services/`. The Flutter mobile app lives under `flutter-app/`. Infrastructure under `infra/`. |
| **Service isolation** | Services communicate **exclusively** through Redis Streams or REST APIs. Never import code directly between services — only `services/common/` is a shared library. |
| **Database ownership** | `services/api` owns `users`, `alerts`. `services/scraper` owns `tracked_items`, `current_prices`, `lowest_prices`. `services/analyzer` owns `price_history` (TimescaleDB). `services/billing` owns `payment_logs`. |

### Services Map

```
services/
├── api/           → FastAPI: Auth (JWT), Alerts CRUD, Tracked Items API (port 8000)
├── analyzer/      → FastAPI: ML anomaly detection, analytics (port 8001)
├── billing/       → FastAPI: Paymob webhooks, payment processing (port 8002)
├── common/        → Shared library: RedisStreamClient, Paymob utils
├── notification/  → Node.js/TypeScript: WhatsApp alert delivery via 360dialog
├── scraper/       → Python/Playwright: Store scrapers, price processor, alert emitter, monitor
└── whatsapp/      → Python: WhatsApp Cloud API sender (Meta Business API)
```

### Redis Streams

| Stream | Producer | Consumer Group | Purpose |
|--------|----------|----------------|---------|
| `stream:targets` | `api` | `scraper` | New items to scrape |
| `stream:price_ingest` | `scraper` | `cg_analyzer` | Raw price data for analysis |
| `stream:confirmed_deals` | `analyzer` | `cg_notifier`, `cg_whatsapp` | Verified deals for notification |
| `stream:alerts` | `scraper` (alert_emitter) | Downstream | Price drop / back-in-stock events |
| `stream:scrape_failures` | `scraper` | Monitoring | Failed scrape attempts |

---

## Coding Standards

### Python (all services except notification)

- **Formatter**: Black (`line-length = 88`, `skip-string-normalization = true`)
- **Linter**: Ruff (`select = ["E", "F", "W", "C", "I", "B"]`, `ignore = ["E203"]`)
- **Import sorting**: isort with `profile = "black"`
- **Type hints**: Required on all public functions and class attributes
- **Docstrings**: Required on all public classes and functions (Google style)
- **Async**: Use `async/await` throughout — never block the event loop
- **Logging**: Use `logging` module with structured JSON format. Include `trace_id` where applicable. Never use bare `print()` in production code.

### TypeScript (notification service)

- **Linter**: ESLint
- **Formatter**: Prettier
- **Config**: See `services/notification/.eslintrc.json` and `tsconfig.json`

### Flutter (mobile app)

- **State management**: Riverpod (`flutter_riverpod`)
- **Routing**: GoRouter (`go_router`)
- **HTTP client**: Dio
- **Font**: IBM Plex Sans (bundled in assets)
- **Architecture**: `lib/src/` organized into `core/`, `data/`, `routing/`, `services/`, `ui/`

### Commit Messages

Use **Conventional Commits**: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`

---

## Critical Patterns — Always Follow

### 1. Stream Reliability
```python
# ALWAYS create consumer groups on startup
await redis_client.ensure_group("stream:price_ingest", "cg_analyzer")

# ALWAYS XACK after successful processing
await redis_client.xack(stream, group, message_id)
```

### 2. Database Operations
- Use SQLAlchemy ORM for `services/api` models
- Use raw async queries (asyncpg) for TimescaleDB time-series
- All schema changes go in `infra/sql/schema.sql` — this is the canonical schema
- Use `UUID` primary keys (via `pgcrypto` extension)
- All tables with `updated_at` must use the `update_updated_at_column()` trigger

### 3. Error Handling
- **Fail fast** — do not swallow exceptions
- Log errors with context (service name, trace_id, relevant IDs)
- Scraper failures → emit to `stream:scrape_failures`, continue with next item
- Use `try/except` at the task boundary, not deep in business logic

### 4. Security — Non-Negotiable
- **Secrets**: Always `os.getenv()`. Never hardcode secrets. Never commit `.env`.
- **Webhook validation**: All Paymob webhooks must be HMAC-validated before processing
- **PII**: Encrypt with AES-256 before DB write
- **CORS**: Locked down in production (currently permissive for dev)

### 5. Scraper Extensibility
New stores follow the `BaseScraper` → `ScraperFactory.register_scraper()` pattern:
```python
class NewStoreScraper(BaseScraper):
    store_id = "new_store"
    async def extract_price(self, page): ...

ScraperFactory.register_scraper("new_store", NewStoreScraper)
```

### 6. Feature Flags
Use environment variables to toggle modes:
- `MOCK_WHATSAPP=true` → simulate WhatsApp sends
- `SCRAPER_TARGETS_SOURCE=redis_stream` → read targets from Redis vs DB

### 7. ML Model Lifecycle
- Train models offline using `services/analyzer/train_model.py`
- Load models from disk at startup — never retrain on every request
- Isolation Forest for anomaly detection (`services/analyzer/ml_detector.py`)

---

## Testing Requirements

| What | Where | Framework |
|------|-------|-----------|
| Python unit tests | `services/<svc>/test_*.py` | pytest + pytest-asyncio |
| Python integration tests | `tests/` | pytest |
| TypeScript tests | `services/notification/tests/` | Jest |
| Flutter tests | `flutter-app/test/` | flutter_test |

### Rules
- Every new feature must include unit tests
- Use mocks for external dependencies (Redis, DB, HTTP)
- Use in-memory SQLite for DB isolation in tests
- Run with: `pytest services/<service>/test_*.py -v`
- Target: 80%+ coverage

---

## Environment & Infrastructure

### Docker Services (docker-compose.yml)
```
redis (port 6379) → postgres (port 5434) → timescaledb (port 5433)
api (port 8000) → analyzer (port 8001) → scraper-monitor → scraper → notifier → whatsapp
```

### Required Environment Variables
| Variable | Example |
|----------|---------|
| `DATABASE_URL` | `postgresql://elhaq:elhaq_pass@localhost:5434/elhaq` |
| `REDIS_URL` | `redis://localhost:6379` |
| `TIMESCALE_URL` | `postgresql://elhaq:elhaq_pass@localhost:5433/elhaq_ts` |
| `JWT_SECRET` | (generate securely) |
| `PAYMOB_HMAC` | (from Paymob dashboard) |
| `WHATSAPP_ACCESS_TOKEN` | (Meta Business API token) |

---

## File Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| Service entry point | `main.py` or `app.py` | `services/api/main.py` |
| Models | `models.py` or `*_models.py` | `tracked_items_models.py` |
| Tests | `test_*.py` | `test_store_scrapers.py` |
| Dockerfiles | `Dockerfile` or `Dockerfile.<variant>` | `Dockerfile.monitor` |
| SQL schemas | `infra/sql/*.sql` | `schema.sql` |

---

## Do NOT

- ❌ Use Redis Pub/Sub — use Streams with consumer groups
- ❌ Import between services (except `services/common/`)
- ❌ Add `print()` statements — use `logging`
- ❌ Commit `.env` files or hardcode secrets
- ❌ Skip `XACK` after processing stream messages
- ❌ Retrain ML models at request time
- ❌ Create new database tables without updating `infra/sql/schema.sql`
- ❌ Use synchronous I/O in async services
- ❌ Run `pip install` without user confirmation
