Scraper service (Playwright)
============================

Overview
--------
This service is a Playwright-based producer that loads product pages (using residential proxies when configured), extracts a price and availability, and pushes events into Redis Stream `stream:price_ingest`.

How it works
- Reads `targets.json` (list of objects {sku, url, store}).
- Uses Playwright headless Chromium to fetch pages.
- Extracts price with simple regex heuristics (you should implement store-specific parsers for accuracy).
- Computes `html_hash` and sets `in_stock` boolean.
- Pushes payload to Redis via `services/common/redis_client.py`.
- On repeated failure, appends an entry to Redis list `queue:failed_scrapes`.

Env vars
- `REDIS_URL` – Redis connection string (default `redis://localhost:6379`).
- `PROXY_SERVER` – optional proxy server `host:port` (residential proxy)
- `PROXY_USERNAME` / `PROXY_PASSWORD` – optional proxy credentials
- `SCRAPER_MAX_RETRIES` – retry attempts (default 5)
- `SCRAPER_CONCURRENCY` – parallel browser instances (default 4)

Run locally

```bash
cd services/scraper
pip install -r requirements.txt
python -m playwright install
python scraper.py --targets targets_example.json
```

Docker

```bash
docker build -t elhaq-scraper services/scraper
docker run --rm -e REDIS_URL=redis://host:6379 elhaq-scraper
```

Notes
- Use store-specific extraction functions for robust price detection.
- Residential proxies are required for Egyptian retailers to avoid anti-bot blocks.
- The scraper uses exponential backoff and moves permanently-failed jobs to `queue:failed_scrapes` for later inspection.
