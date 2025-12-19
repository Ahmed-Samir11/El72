# Tracked Item Price Monitoring System

## Overview

The Tracked Item Price Monitoring System is a production-ready, event-driven pipeline that monitors user-selected products across multiple Egyptian and global stores in real-time.

### Key Features

- ✅ **User-Specific Tracking**: Only scrapes items explicitly tracked by users (MVP Scope)
- ✅ **Multi-Store Support**: Scrapes same item across Amazon Egypt, Noon, Jumia, and more
- ✅ **Real-Time Monitoring**: Re-checks tracked items every 30 seconds
- ✅ **Price Change Detection**: Detects price drops and maintains complete price history
- ✅ **Lowest Price Resolution**: Automatically determines which store has the best deal
- ✅ **Smart Alerts**: Emits events for price drops, stock changes, and threshold crossings
- ✅ **Idempotent Processing**: Avoids duplicate price history entries
- ✅ **Production-Ready**: Async/await, structured logging, error handling, rate limiting

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Tracked Item Monitor (Main Service)             │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ Every 30 seconds:                                            │   │
│  │ 1. Fetch active tracked items from DB                        │   │
│  │ 2. For each item, scrape all associated stores               │   │
│  │ 3. Process prices (convert, detect changes, update DB)       │   │
│  │ 4. Determine lowest price across stores                      │   │
│  │ 5. Emit alert events when conditions met                     │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
           │                        │                         │
           ▼                        ▼                         ▼
    ┌─────────────┐         ┌──────────────┐        ┌──────────────┐
    │  Database   │         │ Price History│        │ Redis Stream │
    │  (Postgres) │         │ (TimescaleDB)│        │   (Alerts)   │
    └─────────────┘         └──────────────┘        └──────────────┘
```

## Components

### 1. Database Models (`services/api/tracked_items_models.py`)

**TrackedItem**: Core model representing a user's tracked product
- `canonical_product_id`: Unified identifier across stores
- `specs`: JSONB for spec-based tracking (e.g., "RTX 4060, 16GB RAM")
- `target_price`: Optional user-defined alert threshold
- `is_active`: Enable/disable tracking

**TrackedItemStore**: Links tracked items to specific stores
- Maps one item to multiple store URLs/SKUs
- Supports disabling specific store mappings

**CurrentPrice**: Materialized view of latest prices per store
- Stores both USD (normalized) and local currency prices
- Tracks stock status
- Updated on every scrape

**LowestPrice**: Denormalized cache of best deal
- Fast API reads without complex queries
- Updated automatically when prices change

### 2. Store Scrapers (`services/scraper/store_scrapers.py`)

**BaseScraper**: Abstract interface for all store scrapers
- Enforces rate limiting per store
- Standardized output format (`ScrapeResult`)
- Error handling and retries

**Implemented Scrapers**:
- `AmazonEgyptScraper`: Amazon.eg with 2s rate limit
- `NoonScraper`: Noon.com (Egypt/UAE)
- `JumiaScraper`: Jumia Egypt

**ScraperFactory**: Easy registration of new stores
```python
# Add new store:
class MyStoreScraper(BaseScraper):
    store_id = "mystore"
    # ... implement methods

ScraperFactory.register_scraper("mystore", MyStoreScraper)
```

### 3. Price Processor (`services/scraper/price_processor.py`)

**Responsibilities**:
- Currency conversion to USD (base currency)
- Price change detection (idempotent checks)
- Price history insertion (TimescaleDB)
- Lowest price calculation across stores

**Key Methods**:
- `process_scrape_result()`: Main entry point
- `convert_to_usd()`: Currency normalization
- `_update_lowest_price()`: Cross-store comparison

### 4. Alert Emitter (`services/scraper/alert_emitter.py`)

**Alert Types**:
1. `PRICE_DROP`: Price decreased since last check
2. `BACK_IN_STOCK`: Item became available again
3. `THRESHOLD_CROSSED`: Price went below user's target
4. `LOWEST_PRICE_CHANGED`: This store now has the best deal

**Output**: Redis Stream `stream:alerts`
- Does NOT send notifications directly
- Downstream notification service consumes events

### 5. Tracked Item Monitor (`services/scraper/tracked_item_monitor.py`)

**Main Orchestration Service**:
- Runs scraping cycles every 30 seconds
- Manages browser pool for efficiency
- Handles concurrency with semaphores
- Graceful shutdown on SIGTERM/SIGINT

## Database Schema

### Tracked Items

```sql
-- Core tracked item
CREATE TABLE tracked_items (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  canonical_product_id TEXT NOT NULL,
  specs JSONB,
  target_price NUMERIC(10,2),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Store mappings
CREATE TABLE tracked_item_stores (
  id SERIAL PRIMARY KEY,
  tracked_item_id INTEGER NOT NULL REFERENCES tracked_items(id) ON DELETE CASCADE,
  store_id TEXT NOT NULL,
  store_sku TEXT NOT NULL,
  store_url TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Current prices (snapshot)
CREATE TABLE current_prices (
  tracked_item_id INTEGER NOT NULL REFERENCES tracked_items(id),
  store_id TEXT NOT NULL,
  price_usd NUMERIC(10,4) NOT NULL,
  price_local NUMERIC(10,2) NOT NULL,
  currency TEXT NOT NULL,
  in_stock BOOLEAN NOT NULL DEFAULT TRUE,
  last_updated TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tracked_item_id, store_id)
);

-- Lowest price cache
CREATE TABLE lowest_prices (
  tracked_item_id INTEGER PRIMARY KEY REFERENCES tracked_items(id),
  store_id TEXT NOT NULL,
  price_usd NUMERIC(10,4) NOT NULL,
  price_local NUMERIC(10,2) NOT NULL,
  currency TEXT NOT NULL,
  url TEXT NOT NULL,
  last_updated TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## Configuration

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql://elhaq:elhaq_pass@localhost:5432/elhaq

# Redis
REDIS_URL=redis://localhost:6379

# Scraping
SCRAPE_INTERVAL=30                    # Seconds between scrape cycles
MAX_CONCURRENT_SCRAPES=10             # Max concurrent scraping tasks
BROWSER_POOL_SIZE=5                   # Number of browser instances

# Rate Limiting (per store, configured in scraper classes)
# Amazon: 2s, Noon: 1.5s, Jumia: 1.5s
```

## Running the System

### 1. Setup Database

```bash
# Apply schema
psql -U elhaq -d elhaq -f infra/sql/ddl.sql

# Or using Docker Compose
docker-compose up -d postgres timescaledb
```

### 2. Start Monitor Service

```bash
# Install dependencies
pip install -r services/scraper/requirements.txt
python -m playwright install

# Run monitor
python -m services.scraper.tracked_item_monitor
```

### 3. Docker Deployment

```bash
# Build and run
docker-compose up --build scraper-monitor
```

**Dockerfile** (add to `services/scraper/Dockerfile.monitor`):
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY services/scraper/requirements.txt ./
RUN pip install -r requirements.txt && python -m playwright install --with-deps
COPY . /app
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "services.scraper.tracked_item_monitor"]
```

## Usage Examples

### Add Tracked Item (API)

```python
# Example: User wants to track a laptop across multiple stores

# 1. Create tracked item
tracked_item = TrackedItem(
    user_id=123,
    canonical_product_id="lenovo-legion-5-rtx4060",
    specs={"brand": "Lenovo", "gpu": "RTX 4060", "ram": "16GB"},
    target_price=45000.00,  # EGP
    is_active=True
)
db.add(tracked_item)
db.flush()

# 2. Add store mappings
stores = [
    TrackedItemStore(
        tracked_item_id=tracked_item.id,
        store_id="amazon_eg",
        store_sku="B0C9L8XYZ",
        store_url="https://amazon.eg/dp/B0C9L8XYZ"
    ),
    TrackedItemStore(
        tracked_item_id=tracked_item.id,
        store_id="noon",
        store_sku="N123456",
        store_url="https://noon.com/egypt-en/product/N123456"
    )
]
db.add_all(stores)
db.commit()
```

### Monitor Will Automatically:

1. **Scrape** both Amazon and Noon every 30 seconds
2. **Convert** prices to USD for comparison
3. **Detect** price changes:
   - Amazon: EGP 48,000 → EGP 45,500 ✅ Price drop!
   - Noon: EGP 46,000 → EGP 46,000 (no change)
4. **Determine** lowest price: Noon (EGP 45,500 after drop)
5. **Emit** alerts:
   - `PRICE_DROP` for Amazon
   - `THRESHOLD_CROSSED` (below 45,000 target)
   - `LOWEST_PRICE_CHANGED` (Amazon now cheapest)

### Query Lowest Price (API)

```python
# Get best deal for a tracked item
processor = PriceProcessor(db_pool)
lowest = await processor.get_lowest_price_for_item(tracked_item_id=1)

# Returns:
{
    "store_id": "amazon_eg",
    "price_usd": 1456.00,
    "price_local": 45500.00,
    "currency": "EGP",
    "url": "https://amazon.eg/dp/B0C9L8XYZ",
    "last_updated": "2025-12-19T14:30:00"
}
```

## Alert Event Format

### Redis Stream: `stream:alerts`

```json
{
    "alert_type": "price_drop",
    "tracked_item_id": 1,
    "user_id": 123,
    "store_id": "amazon_eg",
    "canonical_product_id": "lenovo-legion-5-rtx4060",
    "url": "https://amazon.eg/dp/B0C9L8XYZ",
    "new_price_usd": 1456.00,
    "new_price_local": 45500.00,
    "currency": "EGP",
    "old_price_usd": 1536.00,
    "target_price": null,
    "timestamp": "2025-12-19T14:30:15.123Z",
    "metadata": {
        "drop_percentage": 5.21
    }
}
```

## Reliability & Safety

### Error Handling
- **Scrape Failures**: Logged and emitted to `stream:scrape_failures`
- **Rate Limiting**: Per-store delays enforced automatically
- **Timeouts**: Configurable navigation timeouts (default 20s)
- **Retries**: Handled at scraper level with exponential backoff

### Idempotency
- **Price History**: ON CONFLICT DO NOTHING for (time, sku, store_id)
- **Current Prices**: Upsert with conflict resolution
- **Lowest Prices**: Recalculated on every change

### Logging
```python
# Structured logging with context
logger.info(
    f"Successfully scraped {store_id} for item {canonical_id}: "
    f"price={result.price} {result.currency}, in_stock={result.in_stock}"
)
```

### Graceful Shutdown
- SIGTERM/SIGINT handlers
- Completes current scrape cycle
- Closes browser pool, DB connections, Redis cleanly

## Performance Tuning

### Concurrency
```bash
# Increase concurrent scrapes (adjust based on resources)
MAX_CONCURRENT_SCRAPES=20

# Browser pool size (more browsers = more memory)
BROWSER_POOL_SIZE=10
```

### Database
```sql
-- Add indexes for common queries
CREATE INDEX CONCURRENTLY idx_tracked_items_active 
    ON tracked_items(is_active) WHERE is_active = TRUE;

CREATE INDEX CONCURRENTLY idx_current_prices_in_stock 
    ON current_prices(in_stock) WHERE in_stock = TRUE;
```

### Monitoring
- Track scrape cycle duration
- Monitor failed scrape rate
- Alert on consistently failing stores

## Future Enhancements

1. **Dynamic Exchange Rates**: Fetch from API (e.g., exchangerate-api.com)
2. **Spec-Based Matching**: ML model to match specs across stores
3. **Smart Intervals**: Adjust scrape frequency based on price volatility
4. **Historical Analytics**: Price trends, best time to buy
5. **More Stores**: B.TECH, Sigma, Jarir, etc.

## Testing

### Unit Tests
```bash
pytest services/scraper/test_store_scrapers.py
pytest services/scraper/test_price_processor.py
pytest services/scraper/test_alert_emitter.py
```

### Integration Test
```python
# Test full pipeline
async def test_full_pipeline():
    # Setup: Create tracked item in DB
    # Run: Single scrape cycle
    # Assert: Prices updated, alerts emitted
    pass
```

## Production Checklist

- [ ] Configure exchange rate API
- [ ] Set up monitoring/alerting for service health
- [ ] Configure proxy pool for Egyptian retailers
- [ ] Set up Redis cluster for high availability
- [ ] Configure TimescaleDB retention policies
- [ ] Implement circuit breakers for failing stores
- [ ] Add rate limit metrics per store
- [ ] Set up log aggregation (ELK/Datadog)
- [ ] Configure backup strategy for tracked items
- [ ] Add health check endpoint

## Support

For issues or questions:
- GitHub Issues: [Your Repo]
- Documentation: This file
- Code: See inline comments and docstrings
