# El72 Project - Copilot Instructions

## 1. Project Context & Architecture
**Mission:** Real-time deal detection SaaS for the Egyptian market (Amazon EG, Noon, local retailers).
**Architecture:** Event-Driven Microservices using **Redis Streams** as the backbone.
**Monorepo Structure:**
- `services/scraper` (Python/Playwright): Producers.
- `services/analyzer` (Python/Scikit): Processors (Consumer Group: `cg_analyzer`).
- `services/notification` (Node.js): Consumers (Consumer Group: `cg_notifier`).
- `services/billing` (Go/Python): Dynamic pricing logic.

## 2. Critical Implementation Patterns
### Messaging (Redis Streams)
* **Strictly use Redis Streams** (`XADD`, `XREADGROUP`, `XACK`). Do NOT use Pub/Sub.
* **Reliability:** Consumers must acknowledge (`XACK`) messages only *after* successful DB commits.
* **Stream Keys:**
    * `stream:price_ingest`: Raw scraped data.
    * `stream:confirmed_deals`: Validated deals ready for alerting.
* **Consumer Groups:** Always ensure groups exist (`XGROUP CREATE ... MKSTREAM`) before consumption.

### Database Strategy
* **Time-Series:** Use **TimescaleDB** hypertables for `price_history`.
    * *Pattern:* `SELECT create_hypertable('price_history', 'time');`
* **Relational:** PostgreSQL for `users`, `subscriptions`, and `retailer_analytics`.
* **B2B Logic:** When a user sets an alert, increment the aggregate counter in `retailer_analytics` (Upsert pattern).

### Scraping & Anti-Bot
* **Stealth:** All scrapers must use `playwright-stealth`.
* **Resilience:** Implement exponential backoff for `403 Forbidden` or `503 Service Unavailable`.
* **Context:** Assume execution via Egyptian Residential Proxies. Hardcode timeouts to >30s due to proxy latency.

## 3. Security & Compliance (Egypt Focus)
* **Payments:** Validate **Paymob** webhooks via HMAC signature *before* processing.
    * *Rule:* Reject requests where `hmac_calc != hmac_header`.
* **PII:** Encrypt sensitive user fields (Phone, Email) at rest using AES-256.
* **Data Minimization:** `RetailerAnalytics` table must NEVER contain `user_id` or PII.

## 4. Coding Standards
* **Python:** Type-hinted (Pydantic), Async (FastAPI/`asyncio`).
* **Node.js:** TypeScript, Zod for validation.
* **Error Handling:** Never swallow exceptions. Log structured JSON errors including `trace_id` and `service_name`.
* **Currency:** Store all prices as `DECIMAL(10,2)` normalized to **EGP**.

## 5. Developer Workflow
* **Docker:** All services run in containers. Use `docker-compose up --build` for local dev.
* **Testing:** Use `pytest` for Python services. Mock Redis interactions in tests.