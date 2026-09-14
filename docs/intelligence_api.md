# Intelligence API

The analyzer registers a dedicated intelligence router in `services/analyzer/app.py`. It does not claim Engineer B's planned `/stats`, `/deals/live`, or `/price-history` routes.

## Endpoints

```text
POST /intelligence/deal-score
POST /intelligence/fake-discount
POST /intelligence/cross-store/{product_id}
POST /analytics/category-trends
POST /analytics/store-movements
POST /metrics/platform
```

These endpoints accept validated JSON payloads and delegate to the pure intelligence modules. They do not fabricate database-backed records. A later adapter can load bounded records from PostgreSQL/TimescaleDB and either call these calculations directly or add read-oriented routes without changing the scoring contracts.

The current API slice is intentionally computation-oriented because the repository's live schema and TimescaleDB initialization are inconsistent. Database-backed product/history routes should be added only after that schema contract is reconciled.
