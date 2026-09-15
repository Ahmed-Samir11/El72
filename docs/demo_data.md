# Demo Data Pipeline

The analyzer includes a deterministic Egyptian e-commerce dataset for investor demonstrations. It is separate from live scraping and uses the canonical `tracked_items`, `tracked_item_stores`, `current_prices`, `lowest_prices`, and `price_history` tables.

The default dataset contains 12 products, four stores, and 90 days of observations (4,320 historical rows) from 2025-09-01 through 2025-11-29. It includes normal, genuine-deal, historical-low, suspicious-discount, cross-store, seasonal, recovery, inflation, volatile, and stable scenarios.

## Generate or Regenerate

The current repository has a schema split that must be reconciled before database seeding: the running Postgres container uses legacy integer-ID tables, while the canonical schema includes TimescaleDB-specific objects and the running TimescaleDB container is not initialized with `price_history`. Prepare compatible core tables in Postgres and the `price_history` hypertable in TimescaleDB first. Then configure both URLs and run:

```bash
source ~/hilton/bin/activate
python -m services.analyzer.seed_data generate \
  --database-url "$DATABASE_URL" \
  --timescale-url "$TIMESCALE_URL"
```

`generate` and `regenerate` both refresh only the demo namespace before inserting. They do not clear unrelated application data.

Until that schema prerequisite is completed, the generator and its pure tests are reproducible, but the database integration test remains intentionally skipped.

```bash
source ~/hilton/bin/activate
python -m services.analyzer.seed_data regenerate \
  --database-url "$DATABASE_URL" \
  --timescale-url "$TIMESCALE_URL"
```

To explicitly remove the generated records:

```bash
source ~/hilton/bin/activate
python -m services.analyzer.seed_data reset \
  --database-url "$DATABASE_URL" \
  --timescale-url "$TIMESCALE_URL"
```

The seed, start date, and period can be changed explicitly, for example `--seed 9001 --days 90 --start-date 2025-09-01`.

## Verification

Pure generator tests run without a database:

```bash
source ~/hilton/bin/activate
python -m pytest services/analyzer/test_seed_data.py -q
```

The database test is skipped unless `DEMO_TEST_DATABASE_URL` and `DEMO_TEST_TIMESCALE_URL` are set. It inserts a short dataset, queries `price_history`, verifies the row count, and removes only those demo records.
