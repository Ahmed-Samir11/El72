# Plan: Chatbot Implementation — Search & Add-to-Feed

## Goal

Implement a chatbot that lets users search for products using natural language
(e.g. "gaming laptop under 50000 EGP"), shows results across all supported
stores with prices and images, and provides a one-tap **"Add to Feed"** button
that creates a tracked item (price monitor) for the user.

The chatbot ties up with the existing crawler (Crawl4AI + LLM extraction) for
on-demand product search and with the existing API (`/tracked-items/from-url`)
for creating trackers. It follows the project's service-isolation rules: the
chatbot is a new FastAPI service that talks to the API service via REST and
uses Crawl4AI as a library (not an import from the scraper service).

---

## Approach

### 1. New service: `services/chatbot/`

A standalone FastAPI service (port 8003) with these endpoints:

| Endpoint | Method | Purpose |
|---|---|---|
| `POST /chatbot/message` | POST | Send a user message; return bot response + search results |
| `GET /chatbot/sessions` | GET | List the user's chat sessions |
| `GET /chatbot/sessions/{id}` | GET | Get a session with its messages |
| `GET /health` | GET | Health check |

The chatbot service:
- **Receives** a message + user ID (from the Flutter app, which already has the JWT).
- **Parses intent**: extracts the product query and optional price filter using
  a simple keyword/price-regex parser (no external LLM needed for MVP — the
  Crawl4AI LLM extraction handles product matching on the store side).
- **Searches**: for each enabled store scraper, builds a search URL, crawls the
  search page, and extracts results via `Crawl4AIBaseScraper.extract_search_results()`.
  Returns a ranked list of products (title, price, store, URL, image).
- **Adds to feed**: when the user taps "Add to Feed" on a result, the chatbot
  calls the API service's `POST /tracked-items/from-url` (REST, server-to-server)
  with the product URL and optional target price. The tracker then appears in
  the user's Trackers tab.
- **Persists** chat sessions and messages in the operational PostgreSQL DB
  (`chat_sessions`, `chat_messages`) so conversations survive across app restarts.

### 2. Database schema (operational PostgreSQL)

Add to `infra/sql/schema/postgres.sql`:

```sql
CREATE TABLE IF NOT EXISTS chat_sessions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'bot')),
    content TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_search_results (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    store_id TEXT NOT NULL,
    product_title TEXT NOT NULL,
    price_local NUMERIC(10,2) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'EGP',
    url TEXT NOT NULL,
    image_url TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Add `updated_at` trigger pattern (same as other tables).

### 3. Flutter chat UI

New files under `flutter-app/lib/src/ui/chatbot/`:

- `chat_page.dart` — main chat screen with message list + input field.
- `chat_widgets.dart` — message bubbles, search result cards, "Add to Feed" button.
- `search_result_card.dart` — card showing product image, title, price, store, and the Add-to-Feed button.

Integration points:
- Register a new route `/chat` in `app_router.dart`.
- Add `chatbotRepositoryProvider` and `chatbotProvider` in `providers.dart`.
- Add a "Chat" destination to the dashboard bottom navigation (or a floating action button).
- Add localization strings in `app_localizations_en.dart` and `app_localizations_ar.dart`.

### 4. Flutter repository

`flutter-app/lib/src/data/repositories/chatbot_repository.dart`:
- `sendMessage(sessionId, message)` → `POST /chatbot/message`
- `getSessions()` → `GET /chatbot/sessions`
- `getSession(sessionId)` → `GET /chatbot/sessions/{id}`

### 5. Search flow detail

The chatbot service iterates over the known store scrapers (same list as
`services/api/main.py` store detection). For each store:

1. Build search URL via `scraper.get_search_url(query)`.
2. Crawl the page with `Crawl4AIBaseScraper.crawl_page()`.
3. Extract results with `extract_search_results()` using `SearchResultsSchema`.
4. Filter by price if the user specified a budget.
5. Score/rank results by relevance (token overlap, same as `_find_best_match`).

Return results to the Flutter app. Each result includes an "Add to Feed" button.
When tapped, the Flutter app calls the chatbot service's
`POST /chatbot/message` with a special payload like
`{ "action": "add_to_feed", "result_id": <id> }`. The chatbot service then
calls `POST /tracked-items/from-url` on the API service.

### 6. Credits integration

Creating a tracker costs 1 credit (existing behavior in
`tracked_items_api.py`). The chatbot's add-to-flow should:
- Check the user's credit balance before creating (the API already returns 402
  for insufficient credits).
- Surface the 402 as an "upgrade your plan" prompt in the chat UI, consistent
  with the existing `CreateTrackerSheet` flow.

---

## Files Touched

### New files

| File | Purpose |
|---|---|
| `plans/chatbot-implementation.md` | This plan |
| `services/chatbot/main.py` | FastAPI entry point + endpoints |
| `services/chatbot/search_service.py` | Crawl4AI-based product search logic |
| `services/chatbot/models.py` | Pydantic request/response models |
| `services/chatbot/requirements.txt` | Dependencies (fastapi, crawl4ai, httpx, sqlalchemy, etc.) |
| `services/chatbot/Dockerfile` | Docker build for the chatbot service |
| `services/chatbot/test_main.py` | Unit tests for endpoints |
| `services/chatbot/test_search_service.py` | Unit tests for search (mocked Crawl4AI) |
| `infra/sql/schema/postgres.sql` | Add `chat_sessions`, `chat_messages`, `chat_search_results` tables |
| `flutter-app/lib/src/ui/chatbot/chat_page.dart` | Main chat screen |
| `flutter-app/lib/src/ui/chatbot/chat_widgets.dart` | Message bubbles, result cards, Add-to-Feed button |
| `flutter-app/lib/src/ui/chatbot/search_result_card.dart` | Individual search result card |
| `flutter-app/lib/src/data/repositories/chatbot_repository.dart` | API client for chatbot service |
| `flutter-app/lib/src/data/models/chat_message_model.dart` | Chat message model |

### Modified files

| File | Change |
|---|---|
| `docker-compose.yml` | Add `chatbot` service container |
| `services/api/main.py` | (optional) no change needed — chatbot calls API via REST |
| `flutter-app/lib/src/data/providers.dart` | Add `chatbotRepositoryProvider`, `chatbotProvider` |
| `flutter-app/lib/src/routing/app_router.dart` | Add `/chat` route |
| `flutter-app/lib/l10n/app_localizations_en.dart` | Add chat localization strings |
| `flutter-app/lib/l10n/app_localizations_ar.dart` | Add Arabic chat strings |
| `flutter-app/lib/src/ui/dashboard/dashboard_page.dart` | Add Chat to bottom nav or FAB |
| `services/api/routers/` | (no change — chatbot is a separate service) |

---

## Test Strategy

### Backend (pytest)

- `test_main.py`: Test `/chatbot/message` returns a valid response; test
  `/chatbot/sessions` CRUD; test health endpoint.
- `test_search_service.py`: Mock `Crawl4AIBaseScraper.crawl_page` and
  `extract_search_results`; verify search returns ranked results, price filter
  is applied, and unknown stores are skipped.
- Use in-memory SQLite for DB isolation (consistent with existing test pattern).
- Target 80%+ coverage.

### Flutter

- Widget tests for `SearchResultCard` (verify "Add to Feed" button present).
- Widget tests for `ChatPage` (message list renders, input accepts text).
- Mock the Dio client for repository tests.

---

## Feature Suggestions (beyond MVP)

| Feature | Description |
|---|---|
| **Price alert chat** | User says "alert me when this drops below X EGP"; chatbot sets a target_price on the tracker. |
| **Deal of the day** | Chatbot proactively messages users about deep discounts in categories they've searched. |
| **Product comparison** | "Compare iPhone 15 across stores" → shows prices from Amazon, Noon, Jumia side by side. |
| **Price history query** | "What's the price history for X?" → shows chart data from `/price-history/{sku}`. |
| **Voice search** | Speech-to-text input in the Flutter chat page. |
| **Wishlist / saved items** | Bookmark search results without creating a full tracker. |
| **Budget mode** | "Show me everything under 30000 EGP" — applies price filter globally. |
| **WhatsApp chatbot** | Users can message the bot via WhatsApp (using the existing WhatsApp service) for those who prefer it over the app. |
| **Referral earnings** | Show affiliate commission potential for deals found via chat. |
| **Category browse** | "Show me laptop deals" → browses a category page across stores. |
| **Follow-up questions** | "Is it in stock?" / "What's the warranty?" — answered from extracted product metadata. |

---

## Implementation Order (MVP first)

### PR 1: Database Schema + Chatbot Service Backend ✅ COMPLETE

1. ✅ Plan & branch — wrote plan, created `feat/chatbot` branch.
2. ✅ Database schema — added `chat_sessions`, `chat_messages`, `chat_search_results` tables to `postgres.sql`.
3. ✅ Chatbot service — `main.py`, `search_service.py`, `models.py`, Dockerfile.
4. ✅ API integration — chatbot calls `/tracked-items/from-url` via `httpx` in `_handle_add_to_feed`.
5. ✅ Backend tests — `test_main.py` and `test_search_service.py` (22 tests, all passing).

### PR 2: Flutter Integration + API Endpoints

1. **Flutter repository + providers** — `chatbot_repository.dart`, add providers to `providers.dart`.
2. **Flutter UI** — `chat_page.dart`, `chat_widgets.dart`, `search_result_card.dart`.
3. **Routing + localization** — add `/chat` route and strings to `app_localizations_en.dart` and `app_localizations_ar.dart`.
4. **Dashboard integration** — add Chat to bottom nav in `dashboard_page.dart`.
5. **Flutter tests** — widget tests for chat UI.
6. **Docker compose** — add `chatbot` service container.
7. **API service endpoints** — ensure `/tracked-items/from-url` works correctly for chatbot integration.

### PR 3: Polish & Review

1. Address review feedback.
2. Merge PRs.
3. Final verification.

### Key Design Decisions (unchanged)

1. **Separate service, not embedded in API**: Follows the project's service-isolation rule.
2. **Crawl4AI as a library, not via Redis**: On-demand search uses Crawl4AI directly.
3. **REST API for Flutter → chatbot**: Flutter app calls the chatbot service directly via Dio.
4. **Credits checked by the API**: Chatbot calls `/tracked-items/from-url` which deducts 1 credit and returns 402 on insufficiency.

---

## Key Design Decisions

1. **Separate service, not embedded in API**: Follows the project's service-isolation
   rule (no cross-service imports). The chatbot calls the API via REST for
   tracker creation, which is the allowed communication pattern.

2. **Crawl4AI as a library, not via Redis**: The chatbot does on-demand search,
   not continuous monitoring. It uses Crawl4AI directly (same library as the
   scraper service) rather than pushing to `stream:targets` and waiting for
   results, which would add latency to the chat flow.

3. **REST API for Flutter → chatbot**: The Flutter app calls the chatbot service
   directly (via Dio), just as it calls the API service. This keeps the chatbot
   stateless and scalable.

4. **Credits checked by the API**: The chatbot does not re-implement credit
   logic. It calls `/tracked-items/from-url`, which already deducts 1 credit
   and returns 402 on insufficiency. The chatbot surfaces this to the user.

5. **No LLM for intent parsing (MVP)**: The chatbot uses simple regex/keyword
   extraction for price filters. The heavy NLP (product matching) is delegated
   to Crawl4AI's LLM extraction on each store's search page. An LLM-based
   intent parser can be added later via LM Studio (same local setup as the
   scraper).