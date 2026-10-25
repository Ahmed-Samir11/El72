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
- `ChatResponse.tracker_created` (default `false`) says explicitly whether a
  tracker was created, so the client never infers success from the presence of
  `search_results`.

### API (`services/api`)
- Save the fetched page title in `tracked_items.specs.title`; return `title`
  from list/detail endpoints.
- Store detection: add `elbadrgroupeg.store`, `sigma-computer.com`,
  `2b.com.eg`; SKU from Amazon's slug before `/dp/` and from `?id=`.
- Price fetcher: Amazon main image (`#landingImage`), skip tracking beacons,
  title from `#productTitle` / `<title>`; the markup fallback only accepts a
  plausible product name and drops bot-wall, site-name and oversized leftovers.
- Migration `0005_free_tier_100_credits.sql`: idempotent top-up of existing
  free accounts to a 100 allowance (registered in `scripts/db-bootstrap.sh`).
  The allowance subtracts transactions whose reason `IS DISTINCT FROM
  'free_tier_100'`, so a row with an unexpected reason still counts as a
  real credit movement.

### Flutter (`flutter-app`)
- Fix result list layout; rebuild `SearchResultCard` on `ProductImage`.
- Only `http`/`https` product urls are opened or offered for "Add to Feed":
  `SearchResultModel.isLaunchable` gates both, because `result.url` comes from
  scraped third-party pages.
- Use `_dio.get/post` with auth `Options` for all chatbot calls; show the
  chatbot's message when add-to-feed did not create a tracker, keyed on
  `ChatResponseModel.trackerCreated`.
- `ChatConversation` (`ChangeNotifier`) in `chatConversationProvider` holds
  messages, results, draft and session; invalidated on login/register/demo.
  `reset()` also clears the sending flag and bumps a `revision` counter, and
  every in-flight reply is dropped when the revision it was sent under no longer
  matches — a cleared chat is not repopulated by a request the user abandoned.
  History is capped at `maxMessages` so a long session cannot grow without
  bound. `ChatPage` watches the provider and `_ChatPageBody` re-attaches its
  listener in `didUpdateWidget`, so a replaced (invalidated) conversation is
  picked up instead of the stale instance being kept.
- `ChatbotRepository` validates the session id against a UUID shape before
  interpolating it into `/chatbot/sessions/<id>`; the value can come back from
  the server, so it must not be able to change the route.
- `TrackedItem.title`; `displayName` prefers it, else the slug without the
  `store:` prefix.

## Review response (PR #43 re-review, 12 findings, 1 CRITICAL)

| # | Finding | Fix | Test |
|---|---------|-----|------|
| C | `search_result_card.dart` opened `result.url` with no scheme check — a scraped page can carry `file:`/`data:`/custom schemes, which `launchUrl` hands to another program | `SearchResultModel.isLaunchable` (absolute http/https only) gates the tap, and `launchUrl` failures/exceptions show `unableToOpen` | `search_result_card_test.dart`: https opens, `file:`/`data:`/empty do not, and "Add to Feed" is disabled with them |
| W | add-to-feed success inferred from empty `searchResults` | server sets `ChatResponse.tracker_created`; client branches on `trackerCreated` | `services/chatbot/test_main.py` asserts `tracker_created` true on the create path, false on "no results" and API failure; chat page widget test drives both |
| W | `reset()` left `isSending` set and an in-flight reply could repopulate a cleared chat | `reset()` clears sending and bumps `revision`; replies whose captured revision changed are dropped | `chat_page_test.dart`: send → reset mid-flight → reply ignored, chat stays empty |
| W | chat page kept the old conversation after `chatConversationProvider` was invalidated | `ref.watch` in `ChatPage.build`, listener re-attached in `didUpdateWidget` (old listener removed, controller re-seeded from the new draft) | `chat_page_test.dart`: invalidate then assert the new empty conversation is rendered |
| W | `addToFeed` exception handling | already present (`UnauthorizedException`, `InsufficientCreditsException`, generic) — verified, now also covered by tests | `chat_page_test.dart`: 402 surfaces the credits message |
| W | "Add to Feed" enabled with an empty/invalid url | same `isLaunchable` predicate drives the button | covered by the card test above |
| W | `0005_free_tier_100_credits.sql` used `reason <> 'free_tier_100'`, which drops rows whose reason is NULL from the allowance sum | `IS DISTINCT FROM`; the migration was also missing from the bootstrap list in `test_migration_files.py`, so the single-transaction guard never covered it | `services/common/test_migration_files.py`: 0005 registered, and asserted to compare reasons null-safely |
| W | `<title>` fallback could pick a bot wall, the bare site name or a 10 KB blob | `_is_plausible_title`: length bounds, challenge phrases, site-name-only, no-letter checks | `test_price_fetcher.py`: wall title, site-only title and oversized title rejected; `productTitle` still accepted |
| I | session id interpolated into a URL path unvalidated | `_sessionPathSegment` requires a UUID shape before the request is built (the id the server echoes back overwrites the client's) | `chatbot_repository_test.dart`: `''`, `session/../../x`, a non-hex uuid, `?x=1` and `#frag` all raise before any transport is reached |
| I | chat history unbounded | `ChatConversation.maxMessages` keeps the most recent messages | `chat_conversation_test.dart`: the cap drops the oldest first and keeps the newest |
| I | Arabic scale words: `alef-lam-feh` ("and something") after a number was not multiplied, and hamza-alef spellings of the scale words were unreachable | input folds hamza-alef onto bare alef and the number-word table is folded the same way; a captured scale word extends to the whole word | `services/chatbot/test_arabic_nlp.py` (already on the branch, failing before the fix): `12 alef-lam-feh` = 12000, `alefineh` = 2000 |
| I | `plans/chatbot-demo-monitors.md` committed internal dev addresses | addresses replaced with `<dev-host>:<port>` placeholders | — |

## Test strategy
- API: link parsing (parametrized), title persisted and exposed (incl.
  non-dict `specs`), Amazon image/title extraction, beacon skipping; credit
  tests aligned with the 100 allowance.
- Chatbot: existing suite.
- Flutter: chat page renders result cards without layout errors; chat
  survives leaving/returning; `displayName` fallbacks; add-to-feed success and
  the credits/402 path; reset mid-request; provider replacement; the card
  refuses non-http urls.
- Manual: end-to-end searches (English and Egyptian Arabic) against the local
  LLM; migration applied twice (second run a no-op) and on a simulated
  3-credit account.

## Known limitations
- Amazon/Jumia anti-bot, Noon HTTP2 errors and EgyPrice's dead domain still
  block those stores in chatbot search.
- A search takes ~50–65s on the current local model.
- The browser fetch fallback does not check HTTP status, so a 404 page that
  contains a price is treated as a product page (pre-existing).
