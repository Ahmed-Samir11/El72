# Elhaq Project - Copilot Instructions (v2.0 MVP)

## 1. Architecture & Boundaries
**Type:** Event-Driven Microservices (Monorepo).
**Core Communication:** Redis Streams (`XADD`, `XREADGROUP`, `XACK`). No Pub/Sub.
**Services:**
- `services/api` (New): Gateway for User Auth (JWT), Alerts CRUD, and Frontend API.
- `services/scraper`: Python/Playwright producers.
- `services/analyzer`: Python/FastAPI "Brain" (ML + DB persistence).
- `services/notification`: Node.js/TypeScript "Messenger".
- `services/billing`: Python/FastAPI (Paymob Webhooks + Dynamic Pricing).

## 2. Coding Standards (Strict)
* **Principle:** SOLID, DRY. Use Dependency Injection where possible.
* **Error Handling:** Fail fast. Log with `trace_id`. Do not swallow exceptions.
* **Security:** * Validate ALL webhooks (Paymob HMAC).
    * Encrypt PII (AES-256) before DB write.
    * Never commit secrets; use `os.getenv`.
* **Database:** * TimescaleDB for `price_history`.
    * PostgreSQL for `users` and `alerts`.
    * Redis for Hot State/Streams.

## 3. Critical Patterns
* **Stream Reliability:** Always define Consumer Groups on startup. Always `XACK` after successful processing.
* **ML Persistence:** Load models from disk; do not retrain on every request.
* **Feature Flags:** Use Env Vars to toggle "Simulation Mode" vs "Production Mode" (e.g., `MOCK_WHATSAPP=True`).

## 4. MVP Phase Focus
* Phase 1: Auth, Alert API, Robust Scraping.
* Phase 2: Billing, WhatsApp, E2E Testing.