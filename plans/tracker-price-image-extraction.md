# Plan: Fix tracker price/image extraction from product URLs

**Branch:** `fix/tracker-price-image-extraction` (off `main`)
**Date:** 2026-10-02
**Status:** Phase 1 implemented — PR open for review

---

## 1. Goal

When a user adds a tracker from a product link (`POST /tracked-items/from-url`),
the backend must reliably extract **the item's price and its image** from the
linked page — both of which are clearly present on real product pages — and the
app must give **visible feedback** when a link is not extractable (non-secure
URL, bot-blocked page, or a non-purchasable link such as a portfolio or
homepage) instead of leaving the tracker stuck in "fetching" forever.

Per owner instruction: **start with the easy, deterministic solutions
(automation/parsing)**. Only if those fail the fixture-based unit tests do we
escalate to a small ML solution. **No LLM/agent is used for this task** — it is
a bounded extraction problem.

## 2. Current State — Evidence-Based Findings

| # | Finding | Evidence |
|---|---------|----------|
| E1 | **The Docker API image cannot run the JS fallback at all.** `services/api/Dockerfile` is `python:3.11-slim` + `pip install -r requirements.txt`; `requirements.txt` has **no `playwright`** (and no `requests`, which `price_fetcher.py` lazy-imports). `_fetch_html_playwright` therefore always returns `None` ("Playwright not installed") in the deployed container. | `services/api/Dockerfile`, `services/api/requirements.txt`, `price_fetcher.py:_fetch_html_playwright` |
| E2 | **Bot-protected/JS stores fail on the plain-HTTP path.** A `requests` fetch of Alfrensia returns a ~7 KB block/challenge page with **zero** JSON-LD blocks; the real page (Playwright dump) contains the product markup. Without E1 fixed, such stores never resolve in Docker. | `search_debug/alfrensia_real.html` (6.8 KB, no `ld+json`) vs `search_debug/alfrensia_browser.html` |
| E3 | **Image extraction is too narrow.** Only JSON-LD `image` and `og:image` meta are consulted. No `og:image:secure_url` / `twitter:image` / `<img>` fallback. Shopify pages (e.g. Compumarts) also emit the real image only as `og:image:secure_url` on some paths. | `price_fetcher.py:_extract_from_html`, `search_debug/compumarts_price.html` |
| E4 | **Relative / protocol-relative image URLs are stored as-is.** JSON-LD/OG often emits `/cdn/...` or `//cdn.shop/...`; the app's `Image.network` then fails. No `urljoin` against the page URL anywhere. | `price_fetcher.py:_first_image_url`, `_extract_meta` |
| E5 | **Product JSON-LD discovery misses common layouts.** Only top-level objects and one level of `@graph` are scanned; `mainEntity` (Bootstrap schema) and `@graph`-inside-`@graph` are missed. | `price_fetcher.py:_jsonld_product` |
| E6 | **No WooCommerce price-marker fallback.** Stores like Alfrensia render prices as `<span class="woocommerce-Price-amount amount">` + a currency symbol span — not matched by the current visible-text regex unless the EGP marker is adjacent in text. | `search_debug/alfrensia_browser.html` (classes present) |
| E7 | **Failures are invisible.** The background fetch retries 3× then logs and gives up. No status/reason is persisted or returned, so a tracker from a portfolio link looks identical to a transient network failure; the card shows the hourglass "fetching" state forever. | `tracked_items_api.py:_persist_fetched_price`, `tracker_card.dart` (`hasPrice` only) |
| E8 | **`http://` (non-secure) links are accepted but never upgraded.** A redirect to HTTPS may be dropped by some sites; there is no explicit upgrade attempt, and failure is silent (see E7). | `tracked_items_api.py:TrackedItemByUrl.validate_url` |

## 3. Approach

### Phase 1 — Deterministic automation (primary; expected to be sufficient)

**A. Fetch infrastructure (fixes E1, E2, E8)**
1. `services/api/requirements.txt`: add `requests` (explicit) and `playwright`.
2. `services/api/Dockerfile`: `pip install playwright` + `playwright install --with-deps chromium` so the JS fallback actually exists in the deployed container. (Image grows ~400–500 MB — accepted trade-off for reliable extraction on JS stores.)
3. `fetch_price`: for `http://` URLs, attempt the **HTTPS upgrade first**, then fall back to the original scheme. Keep the requests→Playwright ladder.
4. Playwright wait strategy: instead of a blind 3 s sleep, wait (up to ~8 s total) for any of a small set of price indicators (JSON-LD product block, `og:price`, `woocommerce-Price-amount`, `[class*="price"]`), then continue.

**B. Extraction hardening (fixes E3, E4, E5, E6)** — all pure functions in `price_fetcher.py`, unit-testable:
1. **Image cascade:** JSON-LD `image` → `og:image` → `og:image:secure_url` → `twitter:image` → `<img>` scan (skip obvious logos/icons/flags/spacer images by URL/attribute heuristics; prefer `srcset`'s largest entry when present).
2. **URL normalization:** resolve relative and protocol-relative image/title URLs to absolute via `urljoin(page_url)`; upgrade `http://` images to `https://` when the page itself is HTTPS.
3. **Product JSON-LD discovery:** also accept `mainEntity` on WebPage nodes and one additional `@graph` nesting level.
4. **Price cascade:** JSON-LD offer → meta price tags → **WooCommerce markup** (`woocommerce-Price-amount` + adjacent `woocommerce-Price-currencySymbol`) → existing visible-text EGP regex (kept as last resort).
5. **Classification instead of bare `None`:** `fetch_price` returns a result carrying `status` ∈ `ok | no_price_found | blocked | fetch_failed` plus a short `reason`:
   - `blocked`: HTTP 403/429/5xx, or a very small page with none of the product indicators (bot-wall heuristic),
   - `no_price_found`: page fetched fine but every price pass failed (the portfolio/homepage case),
   - `fetch_failed`: network-level failure after both fetch methods.

**C. Visible status (fixes E7)**
1. Schema (`infra/sql/schema.sql`, canonical) + ORM (`tracked_items_models.py`):
   - `tracked_item_stores.last_fetch_status TEXT NULL` (`ok|no_price_found|blocked|fetch_failed`) + `last_fetch_error TEXT NULL` — set by the background task on every run (success or final failure).
   - `current_prices.image_url TEXT NULL` + `lowest_prices.image_url TEXT NULL` — the image travels with the price row so the list/detail endpoints no longer depend on the best-effort `price_history` lookup (that lookup stays as a fallback for older rows).
2. `create_tables.py`: dialect-aware `ADD COLUMN IF NOT EXISTS` for the new columns so existing dev SQLite DBs upgrade in place (Postgres supports `IF NOT EXISTS` natively).
3. API responses: `GET /tracked-items` and `GET /tracked-items/{id}` include `fetch_status` + `fetch_error` (item level = worst store status; store level in `all_prices`).
4. Flutter (minimal): `TrackedItem` model parses the two fields; `TrackerCard` distinguishes *fetching* (hourglass, as today) from *failed* — "Couldn't fetch price — tap to retry" (wires the existing `POST /{id}/refresh`) and *not a product page* ("This page doesn't look like a product — check the link") for `no_price_found`. New strings go to the ARB files (ar + en).

**D. Edge cases (owner's list, explicit)**
- **Non-secure link (`http://`):** HTTPS upgrade attempt (A3); if both schemes fail → `fetch_failed` with the reason surfaced in-app.
- **Non-purchasable link (portfolio, homepage, social):** fetches fine, no price → `no_price_found`; app tells the user the link doesn't look like a product. The tracker row still exists (user may fix the link later) but is never mistaken for "fetching".
- **Missing/broken image:** empty `image_url` → existing `ProductImage` placeholder (already in place).

### Phase 2 — ML fallback (contingency only)

Triggered **only if** Phase 1 fails its fixture-based unit tests on the saved real
pages (i.e. deterministic parsing genuinely cannot extract price/image where a
human sees them on the page):

1. Build a labeled set from saved product-page fixtures (which DOM node holds
   the price, which image is the product image).
2. Train a small offline model (e.g. a lightweight classifier over
   text/attribute features of candidate nodes) via an offline script
   (`services/api/train_price_locator.py`), committed under
   `services/api/models/`, loaded at startup — **never** trained at request
   time (per AGENTS.md §7).
3. Keep Phase 1 deterministic parsing as the first pass; the model only
   adjudicates pages where parsing found nothing.

Explicitly **not** in scope: LLM/agent-based extraction (owner decision: not
needed for this task).

## 4. Files Touched

```
services/api/price_fetcher.py            ← cascade, normalization, classification,
                                            https upgrade, playwright wait
services/api/tracked_items_api.py        ← persist + surface fetch status/error
services/api/tracked_items_models.py     ← new columns (ORM)
services/api/create_tables.py            ← in-place dev-DB column migration
services/api/requirements.txt            ← + requests, + playwright
services/api/Dockerfile                  ← playwright + chromium install
services/api/test_fixtures/              ← NEW: real saved pages
    compumarts_product.html              (copied from search_debug/)
    alfrensia_homepage.html              (copied; non-product fixture)
    relative_og_image.html               (hand-made fixture)
    woocommerce_product.html             (hand-made fixture)
infra/sql/schema.sql                     ← canonical: new columns
flutter-app/lib/l10n/app_en.arb, app_ar.arb   ← 2 new status strings
flutter-app/lib/src/data/models/tracked_item_model.dart  ← fetch_status/fetch_error
flutter-app/lib/src/ui/widgets/tracker_card.dart         ← failed vs fetching state
flutter-app/lib/src/ui/dashboard/dashboard_page.dart     ← pass status + retry
flutter-app/test/…                       ← model parse + card state tests
plans/tracker-price-image-extraction.md  ← this plan
```

## 5. Test Strategy

| Layer | What | How |
|-------|------|-----|
| Unit (fetcher) | Each extraction pass on real saved fixtures: Compumarts (Shopify: JSON-LD + og) yields price + absolute image; Alfrensia homepage yields `no_price_found`; WooCommerce fixture yields price via markup pass; relative-`og:image` fixture yields absolute URL; `http://` fixture exercises upgrade ordering | `pytest services/api/test_price_fetcher.py -v` (mocked fetchers — no network in tests) |
| Unit (normalization) | `urljoin` behavior for relative / protocol-relative / already-absolute; http→https image upgrade | same file |
| Endpoint | `from-url` + mocked `fetch_price_sync`: success writes price+image rows and `last_fetch_status='ok'`; final failure writes `no_price_found`/`blocked`/`fetch_failed` + reason; list/detail responses include the fields | `pytest services/api/test_tracked_items_api.py -v` (in-memory SQLite) |
| Flutter | Model parses `fetch_status`/`fetch_error` (absent + present); card shows retry state vs fetching state; retry tap calls refresh | `flutter test` |
| CI | Existing Python + Flutter gates in `.github/workflows/ci.yml` cover the new tests automatically | — |

Definition of done for Phase 1: all fixture tests green (especially the real
Compumarts product page extracting price **and** image), analyze/format clean,
dev DB upgrades in place, app shows an actionable message for non-product and
failed links. If the Compumarts/WooCommerce fixture tests fail despite the
passes above → proceed to Phase 2.

## 6. HGM Review Responses (round 1, 2026-10-02 — 10 findings, all addressed)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | CRITICAL | SSRF: user-supplied URLs fetched without egress control | Added `_validate_public_url` (http/https only; every resolved IP must be public — loopback/private/link-local incl. 169.254.169.254 metadata/multicast/reserved/unspecified refused; DNS resolved so obfuscated hosts are caught) enforced before fetch, on **every redirect hop** (requests follows redirects manually, validating each `Location`), and in the Playwright route guard (navigations to non-public URLs aborted). New status path: rejected URLs → `blocked` with a fixed reason; redirect-to-internal → `blocked`. Tests: private/loopback/metadata/IPv6 literals, bad schemes, no-fetch assertion, redirect-to-internal. |
| 2 | WARNING | Retry failures silently swallowed | Retry tap now shows a localized SnackBar (`priceRefreshFailed`, en+ar) when the refresh request itself fails (429/offline); card stays in its failure state. |
| 3 | WARNING | Headless Chromium in a root container may fail (sandbox) | Playwright launches with `--no-sandbox --disable-dev-shm-usage` (documented in the function: the API image runs as root). |
| 4 | INFO | img fallback ignores srcset (plan said prefer largest) | `_best_srcset_url` parses `w`/`x` descriptors; the largest declared entry wins over `src`; falls back to `src` when absent/unparseable. Tests cover width, density, and fallback. |
| 5 | INFO | Uppercase `HTTP://` not upgraded | Scheme checks in `_absolutize` and `_url_candidates` are now case-insensitive; test added. |
| 6 | WARNING | `data:` URIs could be persisted as image URLs | `_absolutize` and `_first_image_url` reject `data:`/`javascript:` URLs (next cascade level or placeholder wins); the `<img>` scan already skipped them. Tests: JSON-LD list with data: first, meta data: → img fallback. |
| 7 | INFO | Bot-wall heuristic too broad (generic "product"/"price") | Challenge markers (cf-chl/turnstile/captcha/Just a moment/access denied/Error 521/Web server is down/…) now win outright; strong product markers (JSON-LD, OG image/price, WooCommerce, price__current, EGP/جنيه) clear the page; the legacy word check remains as a last resort so mislinked plain pages (portfolio) still surface as `no_price_found`, not `blocked`. Tests: wall quoting "price", CF 521, markerless page, portfolio page. |
| 8 | WARNING | fetch_error exposure/sanitization | `_safe_fetch_error` (200-char cap, control chars stripped) is the single persistence boundary for `last_fetch_error`; reasons were already short fixed strings (HTTP codes / exception class names, no raw messages or URLs). Tests for truncation/stripping/None. |
| 9 | INFO | Column migration only ran from the script | `_ensure_columns(engine)` now runs at API import/startup (fail-soft, logged) so upgraded DBs get the columns automatically; the script still works standalone. |
| 10 | INFO | Hardcoded fetch-status strings in Dart | New `FetchStatus` constants class in the model layer (mirrors the Python FETCH_* constants) with `isRetryable`; card uses it. |

**Also:** trimmed the Compumarts fixture from ~400KB to the markup the
pipeline consumes (values verbatim, including the `http://` og:image +
`secure_url` quirk) so the PR diff stays reviewable; extraction results
unchanged. Phase 2 (ML) remains a contingency only — Phase 1 fixture tests
pass.

## 7. HGM Review Responses (round 2, 2026-10-02 — 9 findings, all addressed)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | CRITICAL | DNS-rebinding TOCTOU (validate resolves once; fetch resolves again) | Closed at the moment of connection: the requests path runs inside `_connect_time_ssrf_guard`, which wraps `socket.getaddrinfo` so **every** resolution during the fetch is re-checked and a blocked IP fails the connection (`_BlockedAddressError` → `blocked` status). The Playwright browser (separate process) is protected by pinning the target host's DNS to its validated IP via `--host-resolver-rules=MAP host ip` (skipped for IP-literal hosts), in addition to the existing route guard. Test: `test_dns_rebinding_at_connect_time_is_blocked` (public on validation, private at connect → `blocked`). |
| 2 | WARNING | Module-level engine in create_tables (import side effect) | create_tables.py is now import-safe: no engine/SessionLocal at import time; `_ensure_columns(engine)` takes the caller's engine; the standalone script builds its own from `DATABASE_URL`. |
| 3 | WARNING | Fail-soft migration can leave the API without required columns | The startup migration is now fail-HARD: the tracked-items endpoints query these columns, so booting without them would surface as confusing 500s — a boot failure is the honest signal. |
| 4 | WARNING | Chromium `--no-sandbox` blast radius in a root container | The API now runs as an unprivileged `appuser` (uid 10001) in the Dockerfile; Playwright browsers install to the shared `/opt/playwright-browsers` path. `--no-sandbox` is retained (Chromium in a container still requires it) but a compromised browser process is no longer root. |
| 5 | INFO | Migration log noisy when columns already exist | `_ensure_columns` now inspects existing columns first and only ALTERs + logs columns actually added; already-upgraded DBs produce no migration log lines. |
| 6 | INFO | Model parsing assumes string fetch_status/fetch_error | `fromJson` now checks `is String` before casting (non-string → null) instead of throwing on contract drift. |
| 7 | INFO | Retry handler only caught DioException | Broadened to `catch (_)` — any failure from the refresh request shows the SnackBar; nothing escapes the tap handler. |
| 8 | INFO | Retryable failure + null onRetry made the card untappable | `onTap: _retryableFailure ? (onRetry ?? onTap) : onTap` — falls back to the normal tap. Widget test added. |
| 9 | INFO | Malformed ports/URLs raised unclassified | `_validate_public_url` now catches `ValueError` from `urlsplit`/`getaddrinfo` (invalid port, unterminated IPv6 bracket) and reports it uniformly as a rejected URL. Tests: `https://8.8.8.8:abc/x`, `http://[::1/x`, `http://:80/x`. |

**Also from missed_tests:** IPv4-mapped IPv6 handling added to `_is_blocked_ip`
(`::ffff:127.0.0.1` blocked, `::ffff:8.8.8.8` allowed — Python marks the
whole `::ffff:0:0/96` range private, so the mapped IPv4 address is judged
directly) with param cases.
