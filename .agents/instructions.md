# El72 (Elhaq) — Development Instructions

## What This Project Is

El72 is a **price tracking platform for the Egyptian market**. Users track products across Amazon Egypt, Noon, and Jumia. The system scrapes prices every 30 seconds, detects anomalies with ML, and sends WhatsApp alerts when deals hit.

**Target market**: Egyptian consumers buying electronics, phones, GPUs, and high-ticket items.  
**Revenue model**: Freemium — credit-based tracking, priority notifications, and affiliate commissions (see `business_research.md` for all models under consideration).

---

## How the System Works (End-to-End Flow)

```
User adds item via API or Flutter app
        ↓
API service (FastAPI) → saves to `tracked_items` DB + pushes to `stream:targets`
        ↓
Scraper Monitor → every 30s, fetches active tracked items from DB
        ↓
Store Scrapers → Playwright scrapes Amazon/Noon/Jumia (concurrent, rate-limited)
        ↓
Price Processor → converts currencies, compares with previous prices
        ↓
DB Updates → current_prices, price_history (TimescaleDB), lowest_prices
        ↓
Alert Emitter → checks for price_drop / back_in_stock / threshold_crossed / lowest_price_changed
        ↓
Redis Stream (stream:alerts / stream:confirmed_deals)
        ↓
WhatsApp Sender → sends Utility-category template via Meta Cloud API
        ↓
User gets WhatsApp notification
```

---

## Development Setup

### Prerequisites
- Docker & Docker Compose
- Python 3.11+
- Node.js 18+ (notification service)
- Flutter SDK 3.9+ (mobile app)
- Playwright browsers: `python -m playwright install`

### Quick Start
```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env with your values

# 2. Start infrastructure
docker-compose up -d redis postgres timescaledb

# 3. Apply database schema
psql -U elhaq -h localhost -p 5434 -d elhaq -f infra/sql/schema.sql

# 4. Run everything
docker-compose up --build

# 5. Verify
curl http://localhost:8000/health
curl http://localhost:8001/health
```

### Running Individual Services (Development)
```bash
# API Gateway
cd services/api && uvicorn main:app --reload --port 8000

# Analyzer
cd services/analyzer && uvicorn app:app --reload --port 8001

# Scraper Monitor (tracked items)
python -m services.scraper.tracked_item_monitor

# Notification (Node.js)
cd services/notification && npm install && npm run dev

# Billing
cd services/billing && uvicorn main:app --reload --port 8002
```

---

## Project Structure — What Lives Where

```
El72/
├── .agents/                    ← Agent rules and skills (THIS DIR)
├── .github/                    ← CI/CD workflows
│   ├── copilot-instructions.md ← Legacy Copilot instructions
│   ├── prompts/
│   └── workflows/
├── backend/                    ← Legacy backend modules (cart, checkout, crawler, ranking)
│   ├── models/
│   └── modules/
├── flutter-app/                ← Flutter mobile app (elhaq_tracker)
│   ├── lib/
│   │   ├── main.dart           ← App entry point
│   │   ├── l10n/               ← Localization
│   │   └── src/
│   │       ├── core/           ← Constants, theme, utils
│   │       ├── data/           ← Repositories, models
│   │       ├── routing/        ← GoRouter config
│   │       ├── services/       ← Riverpod providers
│   │       └── ui/             ← Screens and widgets
│   └── pubspec.yaml
├── frontend/                   ← Web frontend (static, minimal)
│   └── public/
├── infra/                      ← Infrastructure
│   ├── monitoring/             ← Prometheus, Alertmanager configs
│   └── sql/
│       └── schema.sql          ← ★ CANONICAL DATABASE SCHEMA ★
├── services/                   ← ★ CORE MICROSERVICES ★
│   ├── api/                    ← FastAPI gateway (auth, alerts, tracked items)
│   ├── analyzer/               ← ML anomaly detection + analytics
│   ├── billing/                ← Paymob payment processing
│   ├── common/                 ← Shared library (RedisStreamClient, Paymob)
│   ├── notification/           ← Node.js WhatsApp notifier (360dialog)
│   ├── scraper/                ← ★ BIGGEST SERVICE ★ — scrapers, monitor, alerts
│   └── whatsapp/               ← Python WhatsApp sender (Meta Cloud API)
├── tests/                      ← Integration & E2E tests
├── docker-compose.yml          ← All services orchestration
├── docker-compose.override.yml ← Local dev overrides
├── requirements.txt            ← Root Python dependencies
├── pyproject.toml              ← Black/Ruff/isort config
└── business_research.md        ← Revenue model research & WhatsApp cost analysis
```

---

## Key Technical Decisions

### Why Redis Streams (not Pub/Sub)?
- **Durability**: Messages persist until acknowledged. If a consumer crashes, it picks up where it left off.
- **Consumer Groups**: Multiple consumers can share workload with guaranteed exactly-once delivery.
- **Backpressure**: Built-in with `XREADGROUP COUNT`.

### Why Playwright (not requests/BeautifulSoup)?
- Egyptian e-commerce sites are heavily JavaScript-rendered (React/Vue SPAs).
- Anti-bot protections require real browser fingerprints.
- Playwright handles dynamic content, lazy-loaded prices, and cookie walls.

### Why TimescaleDB for price_history?
- Price data is time-series by nature.
- Hypertables give automatic partitioning and compression.
- Native PostgreSQL compatibility (same connection, same ORM).

### Why Two WhatsApp Services?
- `services/notification/` — Original Node.js implementation using 360dialog API
- `services/whatsapp/` — Newer Python implementation using Meta Cloud API directly
- The Python one (`whatsapp/sender.py`) is the active one. The Node.js one is kept for backward compatibility.

---

## Database Quick Reference

### Core Tables

| Table | Owner Service | Purpose |
|-------|---------------|---------|
| `users` | api | User accounts (phone, password, tier) |
| `alerts` | api | User-defined price alerts |
| `tracked_items` | api/scraper | Products being monitored |
| `tracked_item_stores` | api/scraper | Store URLs/SKUs per tracked item |
| `current_prices` | scraper | Latest price snapshot per item per store |
| `lowest_prices` | scraper | Cached best deal per item |
| `price_history` | analyzer | TimescaleDB hypertable — all price points |
| `payment_logs` | billing | Paymob payment records |
| `retailer_analytics` | analyzer | Aggregated B2B metrics |

### UUID Everywhere
All primary keys are `UUID` generated by `pgcrypto.gen_random_uuid()`. This is critical for distributed system compatibility.

---

## WhatsApp Business API — Cost Rules

> **This directly affects profitability. Read carefully.**

| Category | Use Case | Cost/Message |
|----------|----------|-------------|
| **Utility** | User-triggered alerts ("Your tracked item dropped to X EGP") | ~$0.0036 (~0.17 EGP) |
| **Authentication** | OTP codes | ~$0.0036 |
| **Marketing** | Promotional broadcasts | ~$0.1073 (~5.20 EGP) — **30x more!** |
| **Service** | User-initiated conversation | **FREE** (24h window) |

### Golden Rule
All alert templates **must** use neutral, informational language to qualify as Utility:
- ✅ `"Elhaq Alert: {{1}} has entered your requested price range. Current: {{2}} EGP. View: {{3}}"`
- ❌ `"Good news! Buy now before stock runs out!"`

---

## Current State & Roadmap

### ✅ Completed (MVP Phase 1)
- User auth (JWT) + alerts API
- Store scrapers: Amazon Egypt, Noon, Jumia
- 30-second scrape cycle with browser pooling
- ML anomaly detection (Isolation Forest)
- Price comparison engine with currency conversion
- 4 alert types → Redis Stream
- WhatsApp notification pipeline
- Docker Compose deployment
- Comprehensive test suite (97%+ coverage)

### 🔄 In Progress (Phase 2)
- Billing & Paymob payment integration
- Flutter mobile app (Riverpod + GoRouter)
- Advanced analytics dashboard

### 📋 Planned (Future)
- More stores: B.TECH, Sigma, Jarir, ElBadr Group
- Dynamic exchange rate API integration
- Spec-based product matching (ML)
- Adaptive scrape intervals
- Installment brokering integration
- Aggregated demand data feed (B2B)
- Multi-region deployment

---

## Common Development Tasks

### Adding a tracked item manually
```sql
INSERT INTO tracked_items (user_id, canonical_product_id, target_price)
VALUES ('<user-uuid>', 'rtx-5080-gpu', 78000.00) RETURNING id;

INSERT INTO tracked_item_stores (tracked_item_id, store_id, store_sku, store_url)
VALUES ('<item-uuid>', 'amazon_eg', 'B0XXXXXX', 'https://amazon.eg/dp/B0XXXXXX/');
```

### Checking system health
```bash
# API
curl http://localhost:8000/health

# Redis streams
redis-cli XLEN stream:alerts
redis-cli XLEN stream:scrape_failures
redis-cli XINFO GROUPS stream:confirmed_deals

# Recent prices
psql -c "SELECT * FROM current_prices ORDER BY last_updated DESC LIMIT 10;"
```

### Running the full test suite
```bash
# Python
pytest -v
pytest --cov=services --cov-report=html

# TypeScript
cd services/notification && npm test

# Flutter
cd flutter-app && flutter test
```

### Debugging scraper issues
```bash
# Check failures
redis-cli XREVRANGE stream:scrape_failures + - COUNT 5

# Run single scrape manually
python services/scraper/demo_tracked_items.py

# Check Playwright browsers
python -m playwright install --with-deps chromium
```

---

## Important Files to Know

| File | Why It Matters |
|------|---------------|
| [schema.sql](file:///e:/repos/El72/infra/sql/schema.sql) | **Source of truth** for all database tables |
| [redis_client.py](file:///e:/repos/El72/services/common/redis_client.py) | Shared Redis Streams wrapper used by all Python services |
| [store_scrapers.py](file:///e:/repos/El72/services/scraper/store_scrapers.py) | BaseScraper + all store implementations + ScraperFactory |
| [tracked_item_monitor.py](file:///e:/repos/El72/services/scraper/tracked_item_monitor.py) | Main orchestrator — the heart of the scraping pipeline |
| [price_processor.py](file:///e:/repos/El72/services/scraper/price_processor.py) | Currency conversion, price change detection, DB updates |
| [alert_emitter.py](file:///e:/repos/El72/services/scraper/alert_emitter.py) | Alert condition checking and Redis event emission |
| [main.py (api)](file:///e:/repos/El72/services/api/main.py) | FastAPI gateway — auth, alerts, stream push |
| [app.py (analyzer)](file:///e:/repos/El72/services/analyzer/app.py) | ML processing, anomaly detection endpoints |
| [sender.py](file:///e:/repos/El72/services/whatsapp/sender.py) | WhatsApp Cloud API message sender |
| [docker-compose.yml](file:///e:/repos/El72/docker-compose.yml) | Full system orchestration |
| [business_research.md](file:///e:/repos/El72/business_research.md) | Revenue models, WhatsApp cost analysis, market research |
