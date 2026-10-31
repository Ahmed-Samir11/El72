# Plan: Tracker Deletion, Remote-Safe Tracker List, Chatbot Price Ranges

Stacked on `feat/chatbot-results-and-tracker-fixes` (PR #43).

## Goal

Support using the app from another network (release APK against a public
HTTPS endpoint, e.g. Tailscale Funnel) for the owner and teammates:

1. Trackers can be deleted from the app.
2. The tracker list loads reliably behind a TLS-terminating proxy.
3. Chatbot searches with a price range ("laptops from 40k to 70k") return
   matching products in that range, not unrelated items.

## Root causes found

| Symptom | Cause |
|---------|-------|
| No way to delete a tracker | API had `DELETE /tracked-items/{id}`; the app had no UI or repository call |
| Trackers sometimes missing in the release APK | App requested `/tracked-items` (no slash); the API's 307 redirect pointed to `http://` behind the HTTPS proxy, which a release build refuses; the repository swallowed the error and returned an empty list |
| "Laptops 40k–70k" returned a CPU and a monitor | Intent had no minimum price; store pages pad or replace results with featured items and nothing filtered them; queries were plural ("laptops") |
| No in-range laptops even when stores had them | First results page is sorted by relevance (mostly over budget) and the LLM window started at menu prices; long laptop titles truncated the LLM's JSON |

## Approach

### Flutter
- `TrackedItemsRepository.deleteTrackedItem`; swipe-to-delete with a
  confirmation dialog on the trackers tab (card removed only after the
  backend confirms).
- Request `/tracked-items/` (exact route, no redirect).
- Live mode surfaces load failures (error + Retry) instead of an empty list.
- New strings in `app_en.arb` / `app_ar.arb`.

### Chatbot (`services/chatbot`)
- Intent: `min_price` alongside `max_price` (LLM prompt + English fallback:
  ranges, "over/under", "k" amounts); singular store-search queries.
- Extraction: per-product `relevant` flag; off-topic products dropped.
- Budget-aware input: with a budget, send the LLM only the page text around
  in-budget prices; otherwise the window with the densest prices.
- Salvage complete products from truncated LLM JSON; output budget 2500
  tokens; at most 6 products per store.
- Replies state the range ("between 40000 and 70000 EGP").

## Test strategy
- Chatbot: range/minimum parsing (parametrized), min+max filtering,
  irrelevant products dropped, truncated-JSON salvage, densest-window and
  budget-window selection.
- Flutter: existing suite; test fakes implement `deleteTrackedItem`.
- Manual: release APK on the emulator via the public Funnel URL; real search
  "I want laptops in the range 40k egp to 70k egp" → 9 laptops in range from
  ElBadr, Alfrensia and Sigma; Arabic range intents parsed correctly.

## Known limitations
- A budgeted search takes ~1m45s on the local model; the slowest store can
  hit the 100s deadline and be dropped.
- 2B's price format isn't matched by the price marker, so its first page
  (out of budget) is used.
- ~~Behind Funnel every client shares one source address, so the chatbot's
  10/minute rate limit is shared.~~ Resolved by #45 (merged into this branch):
  `rate_limit_key` buckets by the JWT subject and falls back to the address
  only for requests without a valid token.

## Review round (HGM pilot, confidence 0.78) — verdicts

Before addressing it, `origin/main` (#46, #47, #51) was merged in. Conflicts:
the bootstrap and migration list keep 0011 then 0012, and the dashboard's
`Dismissible` wraps the `TrackerCard` with main's new `productUrl`/`sku`.

| Finding | Verdict | Action |
|---|---|---|
| Ownership checks for delete / add-to-feed untested | Half valid | Code already filters by `user_id`; added `test_delete_refuses_another_users_tracker`. Add-to-feed already had `test_add_to_feed_rejects_a_session_owned_by_another_user`. |
| Truncated JSON recovery needs strict malformed-output tests | Valid, and found a bug | `_salvage_products_json` scanned for `{` past the array's `]`, so a trailing object (pagination) was salvaged as a product and failed schema validation for the whole store. It now stops at the end of the array; added malformed, trailing-object and nested-object tests. |
| Swipe direction may not be "left" in RTL | Comment only | `endToStart` + `AlignmentDirectional` already flip in RTL; the comment now says so. |
| Async delete should guard disposed widget/ref | Already handled | The repository is read before the `await`; every later `context` use checks `context.mounted`. |
| DELETE route proxy/redirect not covered | Not applicable | The redirect came from the collection route without a trailing slash; `/tracked-items/{id}` matches its route exactly. |
| Cache sweep tied to writes | Not a bug | Reads filter `expires_at_epoch > now`; the table only grows on writes, which sweep every `CACHE_SWEEP_EVERY_WRITES`, plus once per process on the first read. |
| `CACHE_MAX_PRODUCTS` bounds count, not bytes | Accepted as is | 40 products per entry, one row per (store, query, window); no change. |
| Rate limiting ineffective behind a shared proxy | Already fixed | Keyed by JWT subject since #45 (see Known limitations). |
| Correlated `NOT EXISTS` in the backfill | Not a problem | Served by `idx_chat_search_results_session_search`; matches nothing on an upgraded database. |
| Index creation not concurrent | By design | Documented in 0011: the bootstrap runs each file with `psql --single-transaction`, where `CONCURRENTLY` is not allowed; the table is small. |
| Plan file in PR body differs | Not reproduced | The body cites `plans/tracker-delete-and-price-ranges.md`, which this PR adds. |
| Known Arabic price-parsing failures remain | Not reproduced | No skipped or xfail tests in `services/chatbot`; the suite passes. |
| Reversed/invalid ranges undefined | Already defined | `_ordered_range` swaps reversed bounds; covered by the `"laptop 70k-40k"` case. |

Found while merging: `0012_affiliate_click_attribution.sql` (from main) had
three comment lines without `--`, so psql would fail the file and roll back the
whole migration. This branch's `test_sql_files_parse_as_postgres` caught it once
0012 was in the tree; the prefixes are restored.

Tests after this round: `pytest services` → 930 passed, 1 skipped, 2 failed.
The 2 failures (`test_seed_data.py::test_database_urls_require_both_connections`,
`test_public_api.py::test_deals_live`) also fail on `origin/main` in a full run
and pass alone (order-dependent). `flutter test` → 289 passed.
