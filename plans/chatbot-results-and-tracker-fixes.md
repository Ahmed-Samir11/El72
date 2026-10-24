# Plan: Chatbot Results, Add-to-Tracker, and Tracker Display Fixes

## Goal

Make the chatbot usable end-to-end in the Flutter app and make trackers show
correct product names, stores and images:

1. Searches return products instead of always "couldn't find items".
2. Results show as cards (image, title, store, price) with a working
   "Add to Feed" button.
3. The chat survives switching tabs.
4. Every free account has a 100-tracker allowance.
5. Trackers show the real product name and store, and Amazon trackers show
   the product image.

## Root causes found

| Symptom | Cause |
|---------|-------|
| Every search: "couldn't find items" | Local LLM (reasoning model, 1 server slot) spent its token budget "thinking" and timed out at 60s; 4 parallel requests queued on 1 slot; client retries added load; text prices (`"9,000"`) failed float validation |
| Few matches | ElBadr used a dead domain; 2B search URL dropped the query; Alfrensia missing; page menus filled the LLM's 8000-char window; only 1 product kept per store |
| No result cards | `ListView` inside a `Column` with unbounded height threw a layout error |
| Add to Feed failed | Client used a bare `RequestOptions` (no host); chatbot read `result_id` but the app sends `product_url`; chatbot called the API without the user's token |
| Chat wiped on tab switch | Dashboard rebuilds tabs; all chat state lived in the page's `State` |
| Old accounts limited to 3 trackers | Free allowance raised 3 → 100 only for accounts without a credits row |
| "Unknown:" / "Amazon Eg:ref=…" names, no Amazon image | Title derived from the URL; scraped title never saved; store domain list outdated; Amazon's first `<img>` is a tracking beacon |

## Approach

### Chatbot service (`services/chatbot`)
- Disable reasoning (`chat_template_kwargs.enable_thinking=false`), serialize
  LLM calls (`LLM_MAX_CONCURRENCY`, default 1), no retries, 120s timeout,
  100s overall search deadline returning partial results.
- Coerce text prices; ask for ≤10 relevant products with numeric prices.
- Fix ElBadr/2B search URLs, add Alfrensia, start the LLM window at the first
  price on the page, return the top 3 matches per store within budget.
- Accept `product_url` for add-to-feed; forward the caller's `Authorization`
  header to the API.

### API (`services/api`)
- Save the fetched page title in `tracked_items.specs.title`; return `title`
  from list/detail endpoints.
- Store detection: add `elbadrgroupeg.store`, `sigma-computer.com`,
  `2b.com.eg`; SKU from Amazon's slug before `/dp/` and from `?id=`.
- Price fetcher: Amazon main image (`#landingImage`), skip tracking beacons,
  title from `#productTitle` / `<title>`.
- Migration `0005_free_tier_100_credits.sql`: idempotent top-up of existing
  free accounts to a 100 allowance (registered in `scripts/db-bootstrap.sh`).

### Flutter (`flutter-app`)
- Fix result list layout; rebuild `SearchResultCard` on `ProductImage`.
- Use `_dio.get/post` with auth `Options` for all chatbot calls; show the
  chatbot's message when add-to-feed did not create a tracker.
- `ChatConversation` (`ChangeNotifier`) in `chatConversationProvider` holds
  messages, results, draft and session; invalidated on login/register/demo.
- `TrackedItem.title`; `displayName` prefers it, else the slug without the
  `store:` prefix.

## Test strategy
- API: link parsing (parametrized), title persisted and exposed (incl.
  non-dict `specs`), Amazon image/title extraction, beacon skipping; credit
  tests aligned with the 100 allowance.
- Chatbot: existing suite.
- Flutter: chat page renders result cards without layout errors; chat
  survives leaving/returning; `displayName` fallbacks.
- Manual: end-to-end searches (English and Egyptian Arabic) against the local
  LLM; migration applied twice (second run a no-op) and on a simulated
  3-credit account.

## Known limitations
- Amazon/Jumia anti-bot, Noon HTTP2 errors and EgyPrice's dead domain still
  block those stores in chatbot search.
- A search takes ~50–65s on the current local model.
- The browser fetch fallback does not check HTTP status, so a 404 page that
  contains a price is treated as a product page (pre-existing).
