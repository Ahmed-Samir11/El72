# Scraper Timescale Pool Split

## Goal

Ensure the tracked-item scraper writes operational snapshots to PostgreSQL and
historical `price_history` rows to TimescaleDB.

## Approach

- Add the existing Docker-style `TIMESCALE_URL` environment variable to the
  scraper-monitor service.
- Create separate PostgreSQL and TimescaleDB pools in the monitor entry point.
- Pass both pools to `PriceProcessor`, keeping all current-price and lowest-price
  operations on PostgreSQL and acquiring a TimescaleDB connection for history.
- Close both database pools alongside the existing browser and Redis resources.
- Update focused processor and monitor call-site tests without changing API or
  analyzer wiring.

## Files Touched

- `docker-compose.yml`
- `services/scraper/tracked_item_monitor.py`
- `services/scraper/price_processor.py`
- `services/scraper/test_price_processor.py`
- `services/scraper/test_tracked_item_monitor.py`
- `services/scraper/demo_tracked_items.py`

## Test Strategy

- Verify the processor uses distinct mocked connections for operational SQL and
  `price_history` insertion.
- Run `services/scraper/test_price_processor.py` and relevant monitor tests.
- Compile all modified Python files with `python -m py_compile`.
- Confirm API/analyzer Timescale references remain unchanged by focused source
  inspection/tests; do not stop or restart Docker services.