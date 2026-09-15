# Engineer B - Revenue Engine - Work Status

Branch: `feature/storefront`
Plan reference: `implementation_plan.md` - Engineer B scope
Last updated: 2026-09-15

## Current Status

Engineer B's implementation work is complete on `feature/storefront`. The branch is ready to be pushed or merged into the next working branch.

The remaining work is deployment configuration, database migration, credential configuration, and full-environment integration testing.

## Completed Implementation

### Public Demo API

Implemented and registered in `services/api/main.py`:

- `GET /stats`
- `GET /deals/live`
- `GET /price-history/{sku}`
- `GET /pricing`
- `GET /affiliate/redirect`
- `GET /credits/balance`
- `GET /credits/transactions`

Public endpoints are fail-soft when demo price-history data is unavailable and include rate limiting through `slowapi`.

`/deals/live` now returns tracked affiliate redirect URLs based on the merchant source URL.

### Credit System

Implemented in `services/api/credits.py` and `services/api/models.py`:

- Free allowance: 3 credits.
- Standard package: 10 credits for 30 EGP.
- Premium package: 30 credits for 90 EGP.
- One credit tracks one item for one week.
- Credit deduction is atomic with tracked-item creation.
- Insufficient balance returns HTTP 402.
- Credit grants and deductions are recorded in `credit_transactions`.
- Balance and transaction history endpoints are available.

The tracked-item router is registered in `services/api/main.py` and tracked-item IDs/user references use UUIDs consistent with the canonical schema.

### Paymob Billing

Implemented in `services/billing/main.py` and `services/billing/models.py`:

- Signed webhook validation using `services/common/paymob.py`.
- Invalid signatures and malformed payloads are rejected.
- Package amount validation:
  - Standard: 30 EGP / 10 credits.
  - Premium: 90 EGP / 30 credits.
- Duplicate Paymob order protection.
- Atomic payment log, credit balance, and credit transaction updates.
- Purchase-intent endpoint: `POST /purchase`.
- Canonical UUID user/payment identifiers.
- SQLite-compatible UUID model type for local tests.

### Affiliate Revenue

Implemented in:

- `services/api/affiliate.py`
- `services/api/routers/affiliate.py`
- `services/api/models.py`
- `infra/sql/schema.sql`

Features:

- Amazon Egypt, Noon, and Jumia host allowlisting.
- Store-specific affiliate parameters from environment variables.
- Safe URL parsing and query preservation.
- Click persistence in `affiliate_clicks`.
- Merchant redirect endpoint with open-redirect protection.
- SKU and deal ID attribution fields.

### Security and Configuration

- API/billing production-path `print()` calls replaced with logging.
- Docker database, Paymob, WhatsApp, and application secrets externalized.
- Required variables documented in `.env.example`.
- `slowapi` added to `services/api/requirements.txt`.
- Canonical schema updated with `user_credits`, `credit_transactions`, and `affiliate_clicks`.

## Validation

The focused Engineer B test suite passes in the `dev-ai` environment:

```text
30 passed, 2 warnings
```

Validated areas:

- Public API endpoints.
- Credit balance, deduction, grants, and insufficient-balance behavior.
- Affiliate URL generation and merchant allowlisting.
- Paymob HMAC validation.
- Paymob billing, package validation, duplicate protection, and credit fulfillment.
- Billing and credit models.

Python compilation, `git diff --check`, and Docker Compose configuration validation also pass.

The warnings are SQLAlchemy/Pydantic deprecation warnings and do not currently fail the tests.

## Remaining Operational Work

### 1. Database Migration

Apply `infra/sql/schema.sql` to the target PostgreSQL and TimescaleDB databases. Existing databases must be migrated carefully because SQLAlchemy `create_all()` does not convert legacy integer tables to UUID-based tables.

Before applying in production:

- Back up the database.
- Inspect existing table types and constraints.
- Plan data conversion for legacy integer IDs if required.
- Apply the schema in a staging database first.
- Run API and integration tests against PostgreSQL, not only SQLite.

### 2. Environment Configuration

Configure real values for:

```env
DATABASE_URL=
TIMESCALE_URL=
SECRET_KEY=
PAYMOB_HMAC_SECRET=
PAYMOB_CHECKOUT_URL=
AMAZON_AFFILIATE_TAG=
NOON_AFFILIATE_TAG=
JUMIA_AFFILIATE_TAG=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
```

The Paymob checkout endpoint currently returns a configured checkout URL; the actual Paymob merchant/order API integration still requires valid merchant credentials and endpoint details.

### 3. Credential Rotation

The WhatsApp token previously committed to repository history must be revoked in Meta Business Manager and replaced with a new environment-only token.

### 4. Full Validation

Run after dependencies and infrastructure are available:

```powershell
conda activate dev-ai
cd C:\EL72\El72
pytest services/api -q
pytest services/billing -q
pytest services/common -q
pytest tests -q
docker compose config --quiet
```

## Environment

The `dev-ai` environment now contains the API, billing, and test dependencies:

- FastAPI 0.104.1
- Pydantic 2.5.0
- SQLAlchemy 2.0.23
- python-jose
- passlib/bcrypt
- Redis client
- psycopg2-binary
- slowapi
- pytest, pytest-asyncio, and httpx

Do not install the root `requirements.txt` over this environment without resolving its older FastAPI/Pydantic pins, which target analyzer compatibility.

## Handoff Checklist

- [x] Credit system implemented.
- [x] Credit deduction wired to tracker creation.
- [x] Public demo APIs implemented.
- [x] Paymob HMAC validation implemented.
- [x] Paymob package fulfillment implemented.
- [x] Affiliate generation and click attribution implemented.
- [x] Public API rate limiting implemented.
- [x] Secrets externalized from Compose.
- [x] Focused Engineer B tests passing.
- [ ] Apply database migration to target infrastructure.
- [ ] Configure production credentials.
- [ ] Rotate exposed WhatsApp token.
- [ ] Run full PostgreSQL/Redis integration validation.
