# Data Architecture Migration

## Goal

Introduce a safe analytical fact constellation across the existing PostgreSQL,
TimescaleDB, and Redis Streams architecture without replacing operational tables,
destroying persistent data, or changing authentication semantics.

## Approach

1. Add an idempotent `analytics` schema to the canonical SQL schema.
2. Add conformed surrogate-key dimensions and the three analytical facts with
   explicit grains, constraints, and query-driven indexes.
3. Backfill dimensions and price observations from existing operational data where
   the source columns are available; preserve the existing TimescaleDB `price_history`
   table as the source for historical observations.
4. Fix analyzer and scraper writes to use the canonical legacy price-history columns
   and project deal evaluations into `analytics.fact_deal` before publishing events.
5. Add notification delivery recording and a deleted-user tombstone workflow while
   keeping operational authentication on `public.users`.
6. Document the final architecture, ERD, Docker mapping, migration safety, and ML
   feature strategy.

## Files Expected To Change

- `infra/sql/schema.sql`
- `services/analyzer/app.py`
- `services/scraper/price_processor.py`
- `services/api/routers/auth.py`
- `services/api/models.py` or a focused analytics repository module
- focused analyzer/API/notification tests
- architecture documentation and ERD under `docs/`

## Test Strategy

- Run the focused schema/analyzer/auth tests first.
- Validate SQL syntax and idempotency against the existing Docker databases.
- Run the complete Python test suite and service-specific TypeScript tests where
  dependencies are available.
- Validate Compose configuration and container health without removing volumes.

## Safety Constraints

- Never run `docker compose down -v`, volume pruning, database drops, or schema
  drops with cascade.
- Do not install PostgreSQL on the host or add a second migration framework.
- Preserve existing operational tables and authentication IDs.