# EL72 Price Monitoring - Quick Reference

## 🚀 Quick Start Commands

```bash
# 1. Setup database
psql -U elhaq -d elhaq -f infra/sql/ddl.sql

# 2. Install dependencies
pip install -r services/scraper/requirements.txt
python -m playwright install

# 3. Start monitor (local)
export DATABASE_URL="postgresql://elhaq:elhaq_pass@localhost:5432/elhaq"
export REDIS_URL="redis://localhost:6379"
python -m services.scraper.tracked_item_monitor

# 4. Start monitor (Docker)
docker-compose up -d scraper-monitor

# 5. Run demo
python services/scraper/demo_tracked_items.py

# 6. Run tests
pytest services/scraper/test_*.py -v
```

## 📦 Component Overview

| Component | File | Purpose |
|-----------|------|---------|
| **Database Models** | `services/api/tracked_items_models.py` | SQLAlchemy ORM models |
| **Store Scrapers** | `services/scraper/store_scrapers.py` | Amazon, Noon, Jumia scrapers |
| **Price Processor** | `services/scraper/price_processor.py` | Currency, comparison logic |
| **Alert Emitter** | `services/scraper/alert_emitter.py` | Event emission to Redis |
| **Main Orchestrator** | `services/scraper/tracked_item_monitor.py` | 30s scheduler |

## 🗄️ Database Quick Reference

### Add Tracked Item

```sql
-- 1. Create tracked item
INSERT INTO tracked_items (user_id, canonical_product_id, target_price)
VALUES (123, 'product-name', 5000.00)
RETURNING id;

-- 2. Add store mapping
INSERT INTO tracked_item_stores (tracked_item_id, store_id, store_sku, store_url)
VALUES (1, 'amazon_eg', 'SKU123', 'https://amazon.eg/dp/SKU123/');
```

### Query Prices

```sql
-- Current prices for an item
SELECT * FROM current_prices WHERE tracked_item_id = 1;

-- Lowest price
SELECT * FROM lowest_prices WHERE tracked_item_id = 1;

-- Price history
SELECT * FROM price_history 
WHERE sku = 'SKU123' 
ORDER BY time DESC 
LIMIT 10;
```

## 🔔 Alert Stream

### Redis Commands

```bash
# Read latest alerts
redis-cli XREVRANGE stream:alerts + - COUNT 10

# Monitor alerts in real-time
redis-cli XREAD BLOCK 0 STREAMS stream:alerts $

# Check scrape failures
redis-cli XREVRANGE stream:scrape_failures + - COUNT 5
```

### Alert Types

- `PRICE_DROP` - Price decreased
- `BACK_IN_STOCK` - Item available
- `THRESHOLD_CROSSED` - Below target price
- `LOWEST_PRICE_CHANGED` - Best deal changed

## 🛠️ Configuration

### Environment Variables

```bash
# Required
DATABASE_URL=postgresql://user:pass@host:port/db
REDIS_URL=redis://host:port

# Optional (defaults shown)
SCRAPE_INTERVAL=30              # Seconds between cycles
MAX_CONCURRENT_SCRAPES=10       # Concurrent scraping tasks
BROWSER_POOL_SIZE=5             # Playwright browser instances
```

## 🏗️ Architecture Layers

```
┌─────────────────────────────────────────┐
│   tracked_item_monitor.py               │  ← Main orchestrator
│   (Scheduler + Coordinator)             │
└─────────────┬───────────────────────────┘
              │
              ├──→ store_scrapers.py       ← Store-specific scraping
              ├──→ price_processor.py      ← Currency + comparison
              └──→ alert_emitter.py        ← Event emission
                           │
                           ↓
                  ┌────────────────┐
                  │ Redis Stream   │  → Downstream services
                  │ (stream:alerts)│
                  └────────────────┘
```

## 🧪 Testing

```bash
# Run all tests
pytest services/scraper/ -v

# Run specific test
pytest services/scraper/test_store_scrapers.py::test_amazon_scraper_extract_price -v

# With coverage
pytest services/scraper/ --cov=services.scraper --cov-report=html
```

## 🐛 Troubleshooting

### Monitor not starting

```bash
# Check logs
docker-compose logs -f scraper-monitor

# Verify connections
psql $DATABASE_URL -c "SELECT 1"
redis-cli -u $REDIS_URL PING
```

### No prices updating

```bash
# Check tracked items
psql -c "SELECT * FROM tracked_items WHERE is_active = TRUE"

# Check scrape failures
redis-cli XLEN stream:scrape_failures

# View failure details
redis-cli XRANGE stream:scrape_failures - + COUNT 5
```

### Playwright issues

```bash
# Reinstall browsers
python -m playwright install --with-deps chromium

# Check browser pool
# Increase BROWSER_POOL_SIZE if seeing timeouts
```

## 📊 Monitoring Queries

```sql
-- Active tracked items count
SELECT COUNT(*) FROM tracked_items WHERE is_active = TRUE;

-- Stores being monitored
SELECT DISTINCT store_id FROM tracked_item_stores WHERE is_active = TRUE;

-- Recent price updates
SELECT 
    ti.canonical_product_id,
    cp.store_id,
    cp.price_local,
    cp.last_updated
FROM current_prices cp
JOIN tracked_items ti ON cp.tracked_item_id = ti.id
ORDER BY cp.last_updated DESC
LIMIT 20;

-- Items with price drops today
SELECT 
    sku,
    store_id,
    price_egp,
    time
FROM price_history
WHERE time >= CURRENT_DATE
ORDER BY time DESC;
```

## 🔧 Common Tasks

### Add New Store

```python
# In store_scrapers.py

class NewStoreScraper(BaseScraper):
    store_id = "new_store"
    
    def __init__(self):
        super().__init__(rate_limit_delay=1.5)
    
    async def extract_price(self, page):
        # Implementation
        return price
    
    async def extract_stock_status(self, page):
        # Implementation
        return in_stock
    
    def get_default_currency(self):
        return "EGP"

# Register
ScraperFactory.register_scraper("new_store", NewStoreScraper)
```

### Disable Item Tracking

```sql
UPDATE tracked_items SET is_active = FALSE WHERE id = 1;
```

### Disable Store for Item

```sql
UPDATE tracked_item_stores 
SET is_active = FALSE 
WHERE tracked_item_id = 1 AND store_id = 'noon';
```

## 📈 Performance Tips

```bash
# More concurrency (if you have resources)
MAX_CONCURRENT_SCRAPES=20
BROWSER_POOL_SIZE=10

# Faster cycles (be careful with rate limits)
SCRAPE_INTERVAL=15

# Add database indexes
psql -c "CREATE INDEX CONCURRENTLY idx_current_prices_updated ON current_prices(last_updated DESC);"
```

## 🔗 Related Files

- **Main README**: [`services/scraper/TRACKED_ITEMS_README.md`](services/scraper/TRACKED_ITEMS_README.md)
- **Implementation Summary**: [`IMPLEMENTATION_SUMMARY.md`](IMPLEMENTATION_SUMMARY.md)
- **Database Schema**: [`infra/sql/ddl.sql`](infra/sql/ddl.sql)
- **Demo Script**: [`services/scraper/demo_tracked_items.py`](services/scraper/demo_tracked_items.py)

## 💡 Pro Tips

- **Start Small**: Test with 1-2 items before scaling
- **Monitor Logs**: Watch for rate limit violations
- **Check Failures**: Regularly review `stream:scrape_failures`
- **Adjust Intervals**: Balance freshness vs. load
- **Use Proxies**: For production Egyptian sites
- **Set Alerts**: Monitor cycle duration and success rate

## 🆘 Support

- Check logs: `docker-compose logs -f scraper-monitor`
- Review tests: `pytest services/scraper/ -v`
- Read docs: `services/scraper/TRACKED_ITEMS_README.md`
- Run demo: `python services/scraper/demo_tracked_items.py`
