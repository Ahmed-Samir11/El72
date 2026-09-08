---
name: "el72-skills"
description: "Core development skills for the El72 price tracking platform — scraper development, service wiring, Flutter features, database migrations, and WhatsApp integration."
---

# El72 Development Skills

This document catalogs the **repeatable development patterns** in the El72 codebase. Use these as recipes when building new features.

---

## Skill 1: Add a New Store Scraper

**When to use**: Adding support for a new Egyptian e-commerce store (e.g., B.TECH, Sigma, Jarir, ElBadr).

### Steps

1. **Create the scraper class** in [store_scrapers.py](file:///e:/repos/El72/services/scraper/store_scrapers.py):

```python
class BtechScraper(BaseScraper):
    """Scraper for B.TECH Egypt (btech.com)."""
    store_id = "btech_eg"

    def __init__(self):
        super().__init__(rate_limit_delay=2.0)  # Be polite

    async def extract_price(self, page: Page) -> float:
        el = await page.query_selector(".product-price .current")
        text = await el.inner_text()
        return float(re.sub(r'[^\d.]', '', text))

    async def extract_stock_status(self, page: Page) -> bool:
        btn = await page.query_selector(".add-to-cart-btn")
        return btn is not None

    def get_default_currency(self) -> str:
        return "EGP"
```

2. **Register it** at the bottom of `store_scrapers.py`:
```python
ScraperFactory.register_scraper("btech_eg", BtechScraper)
```

3. **Add store mapping in the database**:
```sql
INSERT INTO tracked_item_stores (tracked_item_id, store_id, store_sku, store_url)
VALUES ('<item-uuid>', 'btech_eg', 'SKU123', 'https://btech.com/product/...');
```

4. **Write tests** in a new `test_btech_scraper.py` or append to `test_store_scrapers.py`. Mock the Playwright `Page` object.

5. **Update store detection** in [main.py](file:///e:/repos/El72/services/api/main.py) `push_to_stream()` function to recognize the new domain.

### Key Files
- [store_scrapers.py](file:///e:/repos/El72/services/scraper/store_scrapers.py) — BaseScraper, ScrapeResult, ScraperFactory
- [price_processor.py](file:///e:/repos/El72/services/scraper/price_processor.py) — Currency conversion & comparison
- [alert_emitter.py](file:///e:/repos/El72/services/scraper/alert_emitter.py) — Alert event emission

---

## Skill 2: Add a New API Endpoint

**When to use**: Exposing new functionality through the FastAPI gateway.

### Steps

1. **Define Pydantic model** for request/response in `services/api/main.py` or a dedicated `schemas.py`:
```python
class TrackedItemCreate(BaseModel):
    canonical_product_id: str
    target_price: float
    store_urls: list[dict]  # [{store_id, store_url, store_sku}]
```

2. **Add the route** — either directly in [main.py](file:///e:/repos/El72/services/api/main.py) or create a new router in `services/api/routers/`:
```python
# services/api/routers/tracked_items.py
from fastapi import APIRouter, Depends
router = APIRouter()

@router.post("/tracked-items")
def create_tracked_item(...):
    ...
```

3. **Register the router** in `main.py`:
```python
from services.api.routers import tracked_items
app.include_router(tracked_items.router, prefix="/tracked-items", tags=["Tracked Items"])
```

4. **Use dependency injection** for DB sessions and auth:
```python
from services.api.dependencies import get_db, get_current_user
```

5. **Push to Redis stream** if the new endpoint needs to trigger async work:
```python
background_tasks.add_task(push_to_stream, url, alert_id)
```

### Key Files
- [main.py](file:///e:/repos/El72/services/api/main.py) — FastAPI app, existing routes
- [dependencies.py](file:///e:/repos/El72/services/api/dependencies.py) — `get_db`, `get_current_user`
- [models.py](file:///e:/repos/El72/services/api/models.py) — SQLAlchemy models (User, Alert)
- [tracked_items_models.py](file:///e:/repos/El72/services/api/tracked_items_models.py) — Tracked item ORM models
- [tracked_items_api.py](file:///e:/repos/El72/services/api/tracked_items_api.py) — Existing tracked items endpoints

---

## Skill 3: Add a New Redis Stream

**When to use**: Introducing a new async event channel between services.

### Steps

1. **Define the stream name** as a constant — follow the `stream:<name>` convention:
```python
STREAM_NAME = "stream:price_alerts"
```

2. **Producer side** — use `RedisStreamClient.xadd()`:
```python
from services.common.redis_client import RedisStreamClient

client = await RedisStreamClient.create(REDIS_URL)
await client.xadd("stream:price_alerts", {"payload": json.dumps(event)})
```

3. **Consumer side** — create consumer group on startup, then `xreadgroup`:
```python
await client.ensure_group("stream:price_alerts", "cg_alert_handler")
messages = await client.xreadgroup(
    "cg_alert_handler", "consumer-1",
    {"stream:price_alerts": ">"},
    count=10, block=5000
)
# Process messages...
await client.xack("stream:price_alerts", "cg_alert_handler", msg_id)
```

4. **Add to docker-compose.yml** — set env vars for stream names if configurable.

5. **Document** in this file and in the stream table in AGENTS.md.

### Key Files
- [redis_client.py](file:///e:/repos/El72/services/common/redis_client.py) — RedisStreamClient (singleton, async)

---

## Skill 4: Database Schema Migration

**When to use**: Adding new tables or columns.

### Steps

1. **Edit the canonical schema**: [schema.sql](file:///e:/repos/El72/infra/sql/schema.sql)

2. **Follow existing conventions**:
   - Use `UUID` primary keys: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`
   - Add `created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()`
   - Add `updated_at` with trigger: `CREATE TRIGGER update_<table>_updated_at BEFORE UPDATE ON <table> FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();`
   - Add appropriate indexes
   - Use `ON DELETE CASCADE` for foreign keys

3. **Update SQLAlchemy models** in the owning service:
   - `services/api/models.py` — User, Alert
   - `services/api/tracked_items_models.py` — TrackedItem, TrackedItemStore, etc.

4. **Apply schema**:
```bash
psql -U elhaq -d elhaq -f infra/sql/schema.sql
# or
docker exec -i el72-postgres-1 psql -U elhaq -d elhaq < infra/sql/schema.sql
```

5. **Create hypertables** for time-series data:
```sql
SELECT create_hypertable('new_time_series_table', 'time');
```

### Key Files
- [schema.sql](file:///e:/repos/El72/infra/sql/schema.sql) — Canonical schema (v1.0)
- [models.py](file:///e:/repos/El72/services/api/models.py) — SQLAlchemy User/Alert
- [tracked_items_models.py](file:///e:/repos/El72/services/api/tracked_items_models.py) — SQLAlchemy TrackedItem/etc.

---

## Skill 5: Add a Flutter Feature Screen

**When to use**: Building a new screen or feature in the mobile app.

### Steps

1. **Create the UI** in `flutter-app/lib/src/ui/<feature>/`:
```
lib/src/ui/deals/
├── deals_screen.dart
├── deal_card.dart
└── deals_view_model.dart
```

2. **Create the data layer** in `flutter-app/lib/src/data/`:
```dart
// data/repositories/deals_repository.dart
class DealsRepository {
  final Dio _dio;
  Future<List<Deal>> getDeals() async { ... }
}
```

3. **Add Riverpod provider** in `flutter-app/lib/src/services/`:
```dart
final dealsProvider = FutureProvider<List<Deal>>((ref) async {
  final repo = ref.read(dealsRepositoryProvider);
  return repo.getDeals();
});
```

4. **Register route** in GoRouter config (`flutter-app/lib/src/routing/`).

5. **Localization**: Add strings to `flutter-app/lib/l10n/`.

### Key Conventions
- Use `IBM Plex Sans` font (bundled in assets)
- State management: Riverpod only
- HTTP: Dio with `flutter_secure_storage` for tokens
- Navigation: GoRouter

### Key Files
- [pubspec.yaml](file:///e:/repos/El72/flutter-app/pubspec.yaml) — Dependencies
- [main.dart](file:///e:/repos/El72/flutter-app/lib/main.dart) — App entry point
- `lib/src/` — App architecture (core, data, routing, services, ui)

---

## Skill 6: Add a New Alert Type

**When to use**: Adding a new condition that triggers user notifications (e.g., "price match across stores", "historical lowest").

### Steps

1. **Define the alert type** as a constant in [alert_emitter.py](file:///e:/repos/El72/services/scraper/alert_emitter.py):
```python
ALERT_HISTORICAL_LOW = "historical_low"
```

2. **Add detection logic** in the `AlertEmitter` class:
```python
async def _check_historical_low(self, tracked_item_id, new_price_usd, ...):
    # Query price_history for all-time low
    # If new_price < historical_min, emit alert
    await self._emit_alert(ALERT_HISTORICAL_LOW, ...)
```

3. **Wire it into the processing pipeline** in [tracked_item_monitor.py](file:///e:/repos/El72/services/scraper/tracked_item_monitor.py).

4. **Add WhatsApp template** (Utility category, neutral language):
```
"Elhaq Alert: {{1}} has reached its lowest-ever price. Current: {{2}} EGP. View: {{3}}"
```

5. **Write tests** covering the new condition.

### Existing Alert Types
- `PRICE_DROP` — Price decreased
- `BACK_IN_STOCK` — Item available again
- `THRESHOLD_CROSSED` — Price below user target
- `LOWEST_PRICE_CHANGED` — Store now has best deal

---

## Skill 7: WhatsApp Message Integration

**When to use**: Sending notifications via WhatsApp Cloud API.

### Critical Rules
- **Template category matters for cost**: Use **Utility** templates for user-triggered alerts (~$0.0036/msg). Marketing templates cost 30x more.
- **Neutral language only**: No promotional words ("Buy now!", "Good news!", "Limited time!"). Meta's ML classifier will auto-reclassify.
- **Rate limiting**: Free-tier users max 1 alert per item per day.

### Steps

1. **Create/update template** in Meta Business Manager (must be approved).

2. **Send via the whatsapp service** — see [sender.py](file:///e:/repos/El72/services/whatsapp/sender.py):
```python
# The sender consumes from stream:confirmed_deals
# It formats and sends via Meta WhatsApp Cloud API
```

3. **Test with mock mode**: Set `MOCK_WHATSAPP=true` in docker-compose.

### Key Files
- [sender.py](file:///e:/repos/El72/services/whatsapp/sender.py) — WhatsApp Cloud API sender
- [docker-compose.yml](file:///e:/repos/El72/docker-compose.yml) — WhatsApp service config
- `services/notification/` — Legacy Node.js notification service (360dialog)

---

## Skill 8: Add a Docker Service

**When to use**: Deploying a new microservice or worker.

### Steps

1. **Create Dockerfile** in the service directory:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

2. **Add to [docker-compose.yml](file:///e:/repos/El72/docker-compose.yml)**:
```yaml
new-service:
  build:
    context: .
    dockerfile: services/new_service/Dockerfile
  depends_on:
    - redis
    - postgres
  environment:
    DATABASE_URL: "postgresql://elhaq:elhaq_pass@postgres:5432/elhaq"
    REDIS_URL: "redis://redis:6379"
  ports:
    - "8003:8000"
  restart: unless-stopped
```

3. **Note**: Use `context: .` (repo root) for services that import from `services/common/`.

---

## Skill 9: Write & Run Tests

**When to use**: Every feature or bugfix.

### Python Tests
```bash
# Single service
pytest services/scraper/test_store_scrapers.py -v

# All scraper tests
pytest services/scraper/test_*.py -v

# With coverage
pytest --cov=services --cov-report=html

# Integration tests
pytest tests/ -v
```

### Mocking Patterns
```python
# Mock Redis
from unittest.mock import AsyncMock, patch

@patch("services.common.redis_client.RedisStreamClient.create")
async def test_alert_emission(mock_redis):
    mock_client = AsyncMock()
    mock_redis.return_value = mock_client
    # ... test logic
    mock_client.xadd.assert_called_once()

# Mock DB with in-memory SQLite
engine = create_engine("sqlite:///./test.db")
```

### Key Config
- [pytest.ini](file:///e:/repos/El72/pytest.ini) — pytest configuration
- [pyproject.toml](file:///e:/repos/El72/pyproject.toml) — Black/Ruff/isort settings
