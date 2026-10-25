# Plan: Chatbot Enhancement — Speed, Multi-Turn Intelligence, Platform Integration

## Goal

Take the chatbot from "works, but slow and single-shot" to a real conversational
commerce assistant:

1. **Speed** — a search currently costs 8 crawls + up to 9 LLM round-trips on a
   single-slot local model (~50–65s). Target: **<25s cold, <2s warm**.
2. **Coverage** — Amazon / Noon / Jumia / ElBadr / EgyPrice are blocked today, so
   users see "couldn't find items" for reasons they can't see.
3. **Intelligence** — the bot only understands *search* and *add*. Add
   multi-turn follow-ups, compare, price history, deals, and tracker management.
4. **Integration** — chat searches are invisible to the platform; they should
   feed demand analytics over Redis Streams like every other service.
5. **Correctness** — fix the concrete bugs found while auditing the current code.

Everything below is grounded in the code as it stands on `main`
(`services/chatbot/{main,search_service,arabic_nlp,i18n,models}.py`,
`flutter-app/lib/src/ui/chatbot/`, `flutter-app/lib/src/data/repositories/chatbot_repository.dart`).

---

## Audit Findings (drive the plan)

| # | Finding | Evidence |
|---|---------|----------|
| A | Every message pays an LLM intent call even when the regex parser would do | `search_with_intent()` calls `llm_extract_intent()` first, regex only as fallback |
| B | Every store pays an LLM extraction call; `_llm_semaphore` = 1 serializes them | `LMStudioExtractionStrategy.extract()` is the only extraction path |
| C | Repeat searches re-crawl and re-extract; no cache anywhere | no cache in `search_service.py` |
| D | Crawler is bare: `AsyncWebCrawler(headless=True, verbose=False)` — no UA/locale/country/magic/proxy | `_get_crawler()` |
| E | Chatbot ignores robots.txt while the scraper honours it | `services/scraper/robots_handler.py` has no chatbot counterpart |
| F | A 404/error page containing a price is treated as a product page (known limitation from `plans/chatbot-results-and-tracker-fixes.md`) | `_crawl_page()` never checks HTTP status |
| G | Failed stores are silently dropped; the user can't tell "nothing matches" from "store unreachable" | `_search_one_store()` returns `[]` on any error |
| H | `_active_search_results: dict[UUID, list[dict]]` is an unbounded in-process cache — leaks, and dies on restart | module-level in `main.py` |
| I | Add-to-feed matches results by URL string, not stable id | `_handle_add_to_feed()` `WHERE url = :url` |
| J | `POST /chatbot/add-to-feed` hardcodes `language="en"` — Arabic users get English replies | `add_to_feed()` |
| K | Success vs. failure is signalled by an empty `search_results` array with HTTP 200 | Flutter sniffs `response.searchResults.isEmpty` in `chat_page.dart` |
| L | `GET /chatbot/sessions/{id}` returns hardcoded `created_at: None, updated_at: None` | `get_session()` |
| M | Reusing a session never bumps `updated_at`, so the sessions list goes stale | `_ensure_session()` only INSERTs |
| N | Ranking is token overlap; the final list is then sorted by price, discarding relevance | `_rank_matches()` then `results.sort(key=price)` |
| O | Same product from 3 stores = 3 unrelated cards; no cross-store view | no grouping in `search()` |
| P | Rate limit keyed by IP (`get_remote_address`) while one search = 8 crawls + 9 LLM calls | `limiter.limit("10/minute")` |
| Q | JWT decode is duplicated in the chatbot and the API — drift risk | `verify_jwt_token()` in `main.py` |
| R | `ChatRequest.message` has no model-level bound (length checked in the handler only) | `models.py` |
| S | `ChatMessage.id: int` while the DB column is UUID | `models.py` |
| T | `parse_add_command()` returns `1` for *any* Arabic message containing `أضف` | `arabic_nlp.py` last line |
| U | Follow-ups are impossible: no conversation history reaches intent extraction | `search_with_intent(message)` is single-turn |
| V | Hardcoded UI strings bypass l10n (`'Tracker created for …'`) | `chat_page.dart` |
| W | `getSessions()`/`getSession()` exist in the repository but no UI can resume a conversation | `chatbot_repository.dart` |
| X | Chat searches never reach `retailer_analytics` / demand analytics | no stream producer in the chatbot |

---

## Approach

### PR 1 — Latency, coverage, correctness (`feat/chatbot-speed`)

**1. Deterministic extraction fast path (fixes A, B).**
Static Egyptian stores (2B/Magento, Alfrensia/WooCommerce, Sigma, ElBadr) emit
`application/ld+json` `Product`/`Offer` blocks and predictable card markup.
Add `services/chatbot/extractors.py`:

* `extract_jsonld_products(html)` — parse every `application/ld+json` block,
  map `Product` + `offers`/`aggregateOffer` to `SearchResultItem`.
* `extract_card_products(html)` — anchor + price regex fallback per store profile.
* Only when both yield nothing in-budget does the LLM strategy run, and it
  receives the already-focused window (`_focus_on_budget` / `_focus_on_listings`
  stay as-is).

Result: 0 LLM calls per store on the four static stores; the LLM stays for
JS-heavy Amazon/Noon/Jumia.

**2. Intent fast path (fixes A).**
Invert the order in `search_with_intent()`: run `parse_intent()` first; call
`llm_extract_intent()` only when the regex query is empty, or the message
contains a numeric/currency cue the parser failed to bind. Keep the LLM result
as an override when it returns a non-empty query (it is better at translation).

**3. Cache (fixes C).**
In-process TTL+LRU keyed by `(store_id, query, min_price, max_price)` plus a
Postgres table so warm results survive restarts. The in-process layer is a
dependency-free `TTLLRUCache` in `services/chatbot/cache.py` (no `cachetools`:
the image pins few packages and the cache is ~30 lines), `CACHE_TTL_SECONDS=900`,
`CACHE_MAX_ENTRIES=256`. The key is the SHA-256 of the normalized tuple, so no
store id or query can forge another entry's key by containing a delimiter. An
entry is stored and returned as a detached copy of JSON-safe primitives, capped
at `CACHE_MAX_PRODUCTS=40`, with session-only fields (`result_id`, `position`)
stripped: a cached payload is shared by every later search of that store.

```sql
CREATE TABLE IF NOT EXISTS chat_query_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cache_key TEXT NOT NULL UNIQUE,        -- sha256 of (store,query,min,max,profile)
    store_id TEXT NOT NULL,
    results JSONB NOT NULL,                -- the result list
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at_epoch BIGINT NOT NULL     -- whole seconds; swept past expiry
);
```

Writes upsert on `cache_key` (a repeat search refreshes the row instead of
appending a copy), and expired rows are swept by the service on the first cache
read of a process and every `CACHE_SWEEP_EVERY_WRITES=20` writes — so the table
grows with distinct queries, not with page size or with repeat searches. The
column is an integer with a named non-negative check (`chat_query_cache_expiry_non_negative`), declared identically in both paths, and the cache key
carries a `CACHE_PROFILE_VERSION` tag so a change in crawling or extraction
behavior invalidates every entry at once instead of waiting out the TTL.

Add to `infra/sql/schema/postgres.sql` **and** a new
`infra/sql/migrations/0011_chatbot_query_cache.sql`, registered in
`scripts/db-bootstrap.sh` (guarded by `services/common/test_migration_files.py`,
which fails if a numbered migration is never applied). Negative results (store
returned nothing) are cached too, under `CACHE_NEGATIVE_TTL_SECONDS=120`, so
blocked stores stop being re-crawled; a negative entry read back from the DB
keeps that short expiry instead of gaining the full TTL. The same migration adds
`chat_search_results.position` **and** `search_id` (one id per search: every search restarts at position 0, so several searches in a session would otherwise interleave), the `(session_id, search_id, position)` index the ordinal
lookup needs, and re-ranks pre-existing rows per session, so "أadd رقم 3" against
an old session is not ambiguous. The backfill only writes inside a session in which
nothing is ranked yet, so rerunning it after new inserts cannot shuffle a live
session's positions. It also stamps those rows with one deterministic search id
per session, since the service resolves an ordinal through the search group and
a NULL id would leave an old session unreachable.

**4. Crawler hardening (fixes D, E, F, G).**

* `BrowsingConfig` per store: real user-agent, `country_code="EG"`,
  `locale="en-EG"`, Crawl4AI magic/stealth enabled, and proxy rotation from a
  chatbot-owned `services/chatbot/proxies.json` (env-injected, never committed
  with secrets — mirror the shape of `services/scraper/proxies.json`).
* Verify the installed Crawl4AI version's config surface in the Docker image
  before wiring options (`pip show crawl4ai` in the container); keep options
  behind a helper so an unsupported kwarg degrades instead of crashing.
* Move `robots_handler.py` into `services/common/robots.py` (shared library is
  the one allowed cross-service path) and have both the scraper and the chatbot
  use it. Search pages are checked before crawling, and a declared Crawl-Delay is
  honored *exactly*: a store declaring more than `MAX_CRAWL_DELAY` (10s in compose)
  is reported as `robots_denied` and cooled down rather than crawled faster than it
  asked, which is the honest reading of `ROBOTS_TXT_MODE=strict`.
* `_crawl_page()` returns `(content, status_code, final_url)`; a non-2xx or a
  redirect to a login/challenge page is a store failure, not a product page.
* Per-store failure is recorded, not swallowed: the response gains
  `store_status: [{store_id, state: ok|blocked|timeout|robots_denied, products}]`
  so the UI can say *"searched 4 stores, 4 unreachable"*.
* A health probe `GET /chatbot/stores` + a cooldown window per failing store
  (skip re-crawling a store for `STORE_COOLDOWN_SECONDS` after N failures).

**5. Bug fixes (fixes H–T).**

* Delete `_active_search_results`; read the session's last result set from
  `chat_search_results` (already persisted, already ordered).
* `SearchResult` gains `result_id` (the `chat_search_results.id` UUID);
  `AddToFeedRequest` accepts `result_id` and keeps `product_url` as a
  deprecated alias.
* Every search writes a `search_id`; the ordinal and a reference-less add-to-feed
  resolve against the session's newest group, so a second search no longer
  blends with the first — both searches restart at position 0.
* `add_to_feed` resolves the reply language from the session's last user
  message instead of hardcoding `"en"`.
* `add_to_feed` first checks the named session belongs to the authenticated
  user: the result lookup is scoped by `session_id`, so without that check a
  guessed session uuid would expose (and let anyone track) another user's
  searches. The reply is the plain "nothing to add" one, so it never confirms
  the foreign session exists.
* Add `created: bool` to `ChatResponse` and return **402** (not 200) for
  insufficient credits and **409** for "already tracked", so the Flutter
  client stops inferring failure from an empty array.
* `get_session` returns real `created_at` / `updated_at`; `_ensure_session`
  issues an `UPDATE chat_sessions SET updated_at = NOW()` on reuse.
* `ChatRequest.message` gets `Field(min_length=1, max_length=500)`; drop the
  handler-side length check.
* `ChatMessage.id` → `UUID`.
* `parse_add_command()` returns `None` unless an explicit ordinal (`رقم 3`,
  `الأول`, `التani`) or a target is present — no more silent index 1.
* Move JWT decode + user resolution into `services/common/auth.py`; the API
  and the chatbot both consume it (removes the duplicated `SECRET_KEY`/`sub`
  contract).

**6. Rate limiting (fixes P).**
`key_func` → authenticated user id (fall back to IP when unauthenticated),
`/chatbot/message` at `5/minute`, `/chatbot/add-to-feed` at `10/minute`,
and a per-user in-flight search guard (second concurrent search from the same
user returns 429 with a retry-after).

---

### PR 2 — Conversational intelligence (`feat/chatbot-intents`)

**1. Intent classification.** New `services/chatbot/intents.py`, regex-first
with an LLM fallback, returning `{intent, confidence, slots}`:

| Intent | Trigger examples | Backend call |
|--------|-------------------|--------------|
| `search` | `عايز لaptops under 50k` | existing search path |
| `add_to_feed` | `أضف رقم 2` | existing (`parse_add_command`) |
| `set_target_price` | `warn me when it drops under 30k` | `POST /chatbot/add-to-feed` with `target_price` |
| `compare` | `compare iPhone across stores` | analyzer REST `POST /intelligence/cross-store/{product_id}` |
| `price_history` | `show me the price history of X` | API REST `GET /price-history/{sku}` |
| `deals` | `what's the best deal today` | API REST `GET /deals/live` |
| `remove_tracker` | `stop tracking X` | `DELETE /tracked-items/{id}` (resolve id via `GET /tracked-items/`) |
| `help` | `help`, `what can you do` | static localized capability list |

All cross-service calls are **REST only** (API on 8000, analyzer on 8001) per
the service-isolation rule; base URLs come from `API_BASE_URL` /
`ANALYZER_BASE_URL` env vars.

**2. Multi-turn context (fixes U).**
`search_with_intent()` accepts `history: list[ChatMessage]` (last 6 turns) and
`last_result_set`. Follow-up ellipsis resolves against it: *"أقل من 10 ألف؟"*
reuses the previous query; *"the Samsung one"* narrows it; *"and jumia?"*
restricts the store list. History is read from `chat_messages`, never trusted
from the client.

**3. DB-first answers.** When the DB already knows the product
(`/price-history/{sku}`, `/deals/live`, tracked items), answer from it in
milliseconds and skip crawling entirely; crawl only for genuinely new queries.

**4. Ranking & grouping (fixes N, O).**
Score = token overlap + brand/spec match + deal depth (analyzer
`/intelligence/deal-score`) + historical-low flag; price becomes a sort
*option* (`sort=cheapest|best|deals`) instead of a hard-coded final sort.
Cluster near-identical products across stores into one group
(`product_group_id`) with the cheapest store highlighted — the cross-store
card the app already wants.

---

### PR 3 — Flutter UX (`feat/chatbot-ux`)

1. **Progress feedback** — render `store_status` in the typing indicator
   ("searched 2B, Sigma — 2/8"), and show result cards as they stream in
   rather than all at once at the end.
2. **Cards** — add-to-feed uses `result_id`; add a target-price stepper
   (`ChatbotRepository.addToFeed` already accepts `targetPrice`, the UI never
   sends it); show a price-history sparkline from `/price-history/{sku}`;
   group cross-store duplicates into one card with a "3 stores" chip.
3. **Quick commands** — tappable chips (`أقل من 10 ألف؟`, `compare`,
   `track it`, `stop tracking`) so users don't retype Arabic.
4. **Session resume** — wire the existing `getSessions()` / `getSession()`
   into a "continue conversation" affordance (currently dead code in the
   repository).
5. **l10n (fixes V)** — move `'Tracker created for …'` and every other
   hardcoded string into `app_localizations_en.dart` /
   `app_localizations_ar.dart`.
6. **Errors** — surface `created: false` / 402 / 409 distinctly
   (upgrade prompt vs. already-tracked vs. transient failure).

---

### PR 4 — Platform integration & ops (`feat/chatbot-analytics`)

1. **Redis Streams (fixes X)** — the chatbot produces `stream:chat_intents`
   (`query`, `category`, `price_bucket`, `user_id`, `result_count`,
   `language`, `trace_id`) via `RedisStreamClient` from `services/common/`;
   the analyzer consumes it with `cg_intents` and upserts
   `retailer_analytics` (`intent_upsert.py` already does exactly this shape).
   Must call `ensure_group()` on startup and `XACK` after processing; failures
   go to the existing DLQ. **Streams only — no Pub/Sub.**
2. **Observability** — `/metrics` counters: `chatbot_search_seconds`
   (histogram), `chatbot_store_requests{store,state}`, `chatbot_llm_calls`,
   `chatbot_cache_hits_total`; structured JSON logs with `trace_id` threaded
   through request → search → store → extraction.
3. **Docs** — add `chatbot` to the services map and `stream:chat_intents`
   to the Redis Streams table in `.agents/AGENTS.md`.

---

## Files Touched

### New

| File | Purpose |
|------|---------|
| `plans/chatbot-enhancements.md` | this plan |
| `services/chatbot/extractors.py` | JSON-LD + card fast-path extraction |
| `services/chatbot/intents.py` | intent classification + slot parsing |
| `services/chatbot/cache.py` | TTL/LRU + Postgres-backed query cache |
| `services/chatbot/store_health.py` | per-store failure/cooldown tracking |
| `services/common/auth.py` | shared JWT decode + user resolution |
| `services/common/robots.py` | shared robots.txt / crawl-delay handler |
| `services/chatbot/test_extractors.py` | JSON-LD, card, LLM-fallback tests |
| `services/chatbot/test_intents.py` | intent + slot table-driven tests |
| `services/chatbot/test_cache.py` | TTL, negative cache, key normalization |
| `services/chatbot/test_store_health.py` | cooldown, status reporting |
| `infra/sql/migrations/0011_chatbot_query_cache.sql` | cache table + result position |
| `services/analyzer/test_chat_intents.py` | stream consumer → analytics upsert |

### Modified

| File | Change |
|------|--------|
| `services/chatbot/main.py` | result ids, `created` flag, real 402/409, session timestamps, language fix, user-keyed rate limits, store_status, history loading |
| `services/chatbot/search_service.py` | fast-path extraction, cache, crawler config, robots, status codes, ranking/grouping |
| `services/chatbot/models.py` | `result_id`, `created`, `store_status`, field bounds, UUID ids |
| `services/chatbot/arabic_nlp.py` | strict `parse_add_command`, range/min parsing for Arabic |
| `services/chatbot/i18n.py` | new message keys (compare, history, deals, removed tracker, store-unreachable) |
| `services/chatbot/requirements.txt` | `robotexclusionrulesparser` (shared robots handler) |
| `services/chatbot/Dockerfile` | copy new modules and `services/common/` -> `/app/common` |
| `services/api/main.py` | consume `services/common/auth.py` |
| `services/api/dependencies.py` | `SECRET_KEY` required at startup, shared decoder |
| `services/scraper/robots_handler.py` | compatibility shim over `services/common/robots.py` |
| `services/scraper/crawl4ai_base.py` | consume `services/common/robots.py` |
| `services/analyzer/app.py` | `cg_intents` consumer group for `stream:chat_intents` |
| `infra/sql/schema/postgres.sql` | `chat_query_cache` table, `chat_search_results.position` |
| `docker-compose.yml` | `ANALYZER_BASE_URL`, `REDIS_URL` for chatbot |
| `scripts/db-bootstrap.sh` | register migration 0011 |
| `flutter-app/lib/src/ui/chatbot/chat_page.dart` | progress, quick commands, session resume, l10n |
| `flutter-app/lib/src/ui/chatbot/search_result_card.dart` | grouped cards, sparkline, target-price stepper |
| `flutter-app/lib/src/data/repositories/chatbot_repository.dart` | `result_id`, new endpoints, 409 handling |
| `flutter-app/lib/src/data/models/chat_message_model.dart` | `result_id`, `created`, `store_status` |
| `flutter-app/lib/l10n/app_localizations_{en,ar}.dart` | new strings |
| `.agents/AGENTS.md` | services map + `stream:chat_intents` row |

---

## Test Strategy

**Backend (pytest + pytest-asyncio, in-memory SQLite / mocked Redis & httpx):**

* `test_extractors.py` — JSON-LD product+offer mapping, card fallback, LLM
  invoked **only** when both paths come up empty, malformed JSON-LD tolerated.
* `test_cache.py` — warm hit returns without crawling; negative cache blocks
  re-crawl of a dead store; TTL expiry; key normalization (case, whitespace,
  `40k` vs `40000`); upsert on repeat writes and the expired-row sweep; DB
  payloads detached from the caller and free of session-only fields; bumping
  the cache profile version invalidates every entry.
* `test_intents.py` — parametrized (message → intent, slots) across EN +
  Egyptian Arabic, including the follow-up ellipsis cases.
* `test_main.py` — extended: `result_id` round-trip, 402/409 statuses,
  `created` flag, session `updated_at` bump, real session timestamps, Arabic
  reply language on add-to-feed, `store_status` shape, user-keyed rate limit,
  add-command strictness, add-to-feed rejected for a session owned by another
  user, an ordinal answered from the database against a backfilled session and
  against the newest of two searches in one session.
* `test_search_service.py` — existing 20 tests must keep passing; add
  grouping/dedupe and sort-mode tests, and the crawl-delay pair: a declared
  delay is waited out exactly, a delay past `MAX_CRAWL_DELAY` reports the store
  `robots_denied` instead of crawling faster than asked.
* `services/analyzer/test_chat_intents.py` — mocked stream entry →
  `retailer_analytics` upsert, `XACK` called, DLQ on bad payload.
* `services/common/test_auth.py`, `test_robots.py` — shared helpers.
* Target 80%+ coverage; `pytest services/chatbot/test_*.py -v` green before
  the PR.

**Flutter (`flutter test`):** progress indicator renders with partial
`store_status`; grouped card; target-price stepper posts `target_price`;
session resume loads messages; 409 shows "already tracking"; existing
`chat_page_test.dart` / `chatbot_repository_test.dart` stay green.

**Manual acceptance (local llama-server + docker-compose):**

1. `عايز شاشات 2k بسعر أقل من 12 ألف` → results in <25s, cards grouped by
   product, blocked stores listed as unreachable.
2. Same query again → <2s, "from cache" note.
3. `أقل من 10 ألف؟` → reuses the monitor query (multi-turn).
4. `أضف رقم 2` → tracker created, `created: true`, 402 path when credits run
   out, 409 when re-adding.
5. `compare` and `price history` answers come from the DB without a crawl.
6. `redis-cli XREADGROUP GROUP cg_intents ... STREAMS stream:chat_intents`
   shows the intent, and `retailer_analytics` moves.

---

## Design Decisions

1. **Deterministic before LLM.** The LLM is a fallback, not the default path.
   This is the single biggest latency lever and it also removes the
   single-slot serialization.
2. **Cache in Postgres, not Redis keys.** Redis is reserved for Streams-based
   service communication; a cache table keeps the "Streams only" rule intact
   and survives restarts.
3. **Shared code only via `services/common/`.** JWT and robots handling move
   there rather than being imported across services.
4. **DB-first, crawl-second.** The platform already tracks thousands of
   products; answering from TimescaleDB is faster, cheaper and more reliable
   than fighting anti-bot walls.
5. **Streams for analytics, REST for answers.** Chat → analyzer demand
   analytics uses `stream:chat_intents`; chat → API/analyzer lookups use REST.
6. **Explicit status over empty payloads.** HTTP 402/409 + `created` replace
   the "empty array means failure" contract the Flutter client has to guess at
   today.
7. **Backwards compatibility.** `product_url` stays accepted as an alias;
   `store_status` and `result_id` are additive fields, so an older app build
   keeps working against the new service.

---

## Workflow (per `.agents/PR_WORKFLOW.md`)

1. ✅ Plan (this file) — approved before any code.
2. Branch each PR off `main`: `feat/chatbot-speed`, then
   `feat/chatbot-intents`, `feat/chatbot-ux`, `feat/chatbot-analytics`
   (never commit to `main`; `.github/hooks/block-main.json` enforces it).
3. Implement + tests; `pytest services/chatbot/test_*.py -v` and
   `flutter test` green first.
4. Open PRs via the GitHub REST API (`git credential fill` for the PAT; the
   pip `gh-cli` is not the real CLI).
5. `export GITHUB_TOKEN=…; bash scripts/review-pr.sh Ahmed-Samir11/El72#<N>`
   (ensure LF endings on the script).
6. Address every CRITICAL and WARNING finding, push, re-review.
7. Reviewer merges — **no self-merge** — then `git branch -d feat/<name>`.

PRs 1 and 4 are independent; PR 2 builds on 1; PR 3 depends on 1 and 2.

---

## Success Criteria

| Metric | Today | Target |
|--------|-------|--------|
| Cold search | ~50–65s | <25s |
| Repeat search | ~50–65s | <2s |
| LLM calls per message | up to 9 | 0–2 |
| Stores reachable | 3/8 | ≥5/8, rest reported as unreachable |
| Intents understood | 2 | 8 |
| Follow-up questions | unsupported | supported |
| Unbounded in-process state | `_active_search_results` | none |

## Known Risks

* Crawl4AI's browser-config surface varies by version — verify inside the
  Docker image before wiring options; degrade gracefully.
* Anti-bot walls (Amazon/Noon/Jumia) may stay blocked regardless of headers;
  the DB-first path is the mitigation, and the UI must be honest about it.
* Multi-turn context raises prompt size — cap history at 6 turns and
  summarize the previous result set rather than replaying it.
* `stream:chat_intents` adds an analyzer consumer group; rollout must
  `ensure_group` before the first `XADD` and route bad payloads to the DLQ.
