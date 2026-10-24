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
- Behind Funnel every client shares one source address, so the chatbot's
  10/minute rate limit is shared.
