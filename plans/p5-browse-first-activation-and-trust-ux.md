# Plan: P5 — Browse-First Activation, Deep Links, Comparison View, Trust & Offline UX

**Branch:** `feat/browse-first-activation-and-trust` (off `main`)
**Date:** 2026-10-29
**Status:** Draft for approval
**Series:** 5 of 5 release-priority plans. Interlocks with P4 (call-site events: `product_view`,
`comparison_view`, `merchant_click`) and consumes P1's `merchant_link`.

---

## 1. Goal

Make the first 30 seconds of the app produce a **qualified shopping action** instead of a
form, and make the data the user sees **trust-bearing**:

1. **Browse before you register.** Public data (`/deals/live`, `/stats`,
   `/price-history/{sku}`, `/pricing`) is already unauthenticated server-side, so a new
   visitor can search, compare and read price history before any phone-number entry.
2. **Deep links**: a product page on the marketing domain opens the app on that product —
   the report's #1 acquisition channel (§10 "Product-specific SEO": *"[product] price Egypt"*,
   "is this discount real?") needs a web→app handoff the app currently does not have.
3. **A comparison view**, because the differentiator the report claims is
   *product identity + price history + deal quality + merchant comparison + timing* (§19),
   and the app has no cross-merchant surface today.
4. **Freshness provenance**: label when a price was last verified, so a stale price is
   visible as stale instead of presented as current (report §25: stale prices = Very high
   impact; §24 priority 2 "Price data quality").
5. **Offline resilience**: last-known state renders with an honest staleness label rather
   than an empty list.

Non-goals: SEO content on the web app itself (frontend scope), account-deletion UX (P4 WS4),
notification UX (P2), any new ML.

---

## 2. Current State — Evidence

| # | Finding | Evidence |
|---|---|---|
| B1 | A first-time visitor sees a logo and two buttons: Register / Log In — no product, no deals, no search | `flutter-app/lib/src/ui/common/splash_page.dart:31-38` (no token → `AppRoutes.welcome`), `flutter-app/lib/src/ui/auth/welcome_page.dart` (logo + `register` + `login` buttons only) |
| B2 | "Demo mode to explore before you sign up" is unreachable pre-signup: the toggle lives in the authenticated Profile tab | `flutter-app/lib/src/ui/dashboard/dashboard_page.dart:396-430` (SwitchListTile for `demoMode`); listing claim in `docs/play-store/store-listing.md` §3 "demo mode to explore before you sign up" is therefore false for a new visitor |
| B3 | The public endpoints needed for browse-first already exist, no auth required | `services/api/routers/public_api.py:1-22` docstring + `:164 /price-history/{sku}`, `:193 /deals/live`, `:244 /stats`, `:285 /pricing`; `main.py:193` "Public demo endpoints (no auth) consumed by the landing page and Flutter app" |
| B4 | No deep-link support: launcher-only intent filter, no app association, no link-parsing dependency | `flutter-app/android/app/src/main/AndroidManifest.xml:28-31` (only `action.MAIN`), no `<intent-filter>` with a network host, no `.well-known/assetlinks.json` anywhere in `frontend/`, `pubspec.yaml` has no `app_links`/`deeptools` |
| B5 | Routing is a static map; `go_router` is declared but unused, so path/param-based entry would be bolted on awkwardly | `flutter-app/lib/src/routing/app_router.dart` (`Map<String, WidgetBuilder>` + `AppRoutes` constants), `main.dart:101` `routes: AppRouter.routes`, `pubspec.yaml` `go_router: ^14.6.0` unused (plan finding D10 in `plans/flutter-android-release.md`) |
| B6 | No cross-merchant comparison UI anywhere, even though the computation exists and takes client-supplied prices | grep of `lib/src/ui` → no comparison screen; `services/analyzer/routers/intelligence.py:173` `POST /intelligence/cross-store/{product_id}` accepts `CrossStoreRequest(store_prices, historical_prices_by_store)` and calls `compare_store_prices` (`services/analyzer/cross_store.py`) |
| B7 | Store mappings can be written but never read back | `services/api/tracked_items_api.py:540` `POST /tracked-items/{item_id}/stores` (adds a mapping); no GET counterpart |
| B8 | Price freshness is collected but never displayed | `flutter-app/lib/src/data/models/tracked_item_model.dart:67` `final DateTime? updatedAt` (parsed at `:138`) — **zero** usages in `lib/src/ui/**`; the tracker card offers "Fetching live price..." (`fetchingPrice`) and a retry label but no "last checked" state |
| B9 | No local snapshot: an unreachable backend means an empty dashboard in live mode | `flutter-app/lib/src/data/repositories/tracked_items_repository.dart:44-58` (rethrows in live mode), `lib/src/data/config.dart:41` `SharedPreferences` used only for theme + demo flag; `deals_repository.dart` returns `const []` when not in demo mode |
| B10 | Public marketing infra exists, so deep-link hosting is a small addition | `Caddyfile` (`{env.PROD_DOMAIN}` → `frontend-web:80`, `{env.API_DOMAIN}` → `api:8000`), `frontend/` is a Vite app with `public/` (asset serving) |

**Business framing**: report §26 **Gate 1 is "Do users activate?"** — with B1 the only
activation available is creating an account with a phone number, behind an OTP step
(`lib/src/ui/auth/otp_page.dart`). §10's first acquisition channel is product-specific
search traffic, which lands on a *product*, not a signup form. §19/§5: "the defensible
goal is not 'cheapest price'" — without B6 the app cannot show what the strategy doc says
it owns.

---

## 3. Approach

### WS1 — Browse-first activation (PR A, no new server code)

1. Splash routing becomes three-way: token → `dashboard`, no token → **`browse`**
   (new), and `welcome` is only reached from an explicit "Create an account" CTA.
2. New `lib/src/ui/browse/browse_tab.dart` (+ `browse_card.dart`) built on the **already
   public** endpoints: `GET /deals/live` feed, `GET /stats` market header
   (`market_pulse_header.dart` reuse), and a search field whose results use the
   **existing** chatbot service path *without* requiring a session credit (see §7 risk
   table: verify `POST /chat/*` auth/credit posture; if the chatbot service is credit-gated,
   browse search uses a **public search endpoint** added in WS3 — decision recorded there).
3. Signup moves to the first *action*: tapping "Track this" on a browse card routes
   through the existing register/login/OTP flow and then re-plays the tap, so
   account creation is in service of an action, not a precondition for seeing anything.
   `welcome_page.dart` gains the value copy ("search, compare, track — free").
4. Delete the false listing sentence about demo mode from `store-listing.md`, since browse
   mode now replaces demo mode for new visitors (demo mode stays for dev/offline).
5. Optional first-run onboarding (3 cards, real data, no fake states) rendered *inside*
   browse mode; `splash_page.dart` keeps its real-init behavior (no fake progress).

### WS2 — Deep links + GoRouter adoption (PR B)

1. **Adopt `go_router`** (dependency already present, currently unused) as a
   non-negotiable prerequisite for path/param routing: `AppRouter` becomes
   `GoRouter(routes: [...], onMissing: …)` with the same six screens plus
   `/browse`, `/product/:sku`, `/tracker/:id`. Migration surface: `main.dart`
   (`MaterialApp` → `providerBuilder`/`routes`), every `Navigator.push*` call site
   (`create_tracker_sheet.dart`, `dashboard_page.dart`, `subscription_screen.dart`,
   `payment_flow_screen.dart`, `splash_page.dart`, `chat_page.dart`) → `go(name)` /
   `goWithPath`. Keep the `navigatorKey` wiring for the 401 handler
   (`lib/src/data/services/unauthorized_handler.dart` unchanged contract).
   *Fallback option (if a reviewer blocks the migration in a release PR): keep the
   named-route map and pass a single `?path=` launch argument — recorded as Option B
   with the drawback that param routing, redirects and share-links keep being hacked.*
2. **Android app association**: add to the manifest a network intent filter for the
   marketing host,
   ```xml
   <intent-filter android:autoVerify="true">
     <action android:name="VIEW"/><data android:scheme="https"
       android:host="${PROD_DOMAIN}" android:pathPrefix="/product"/>
   </intent-filter>
   ```
   and serve `/.well-known/assetlinks.json` from `frontend/public/` (Caddy already serves
   that host). A new `scripts/app_asset_verification.py` prints the SHA-256 fingerprint
   of the release keystore (the same keystore CI uses per
   `.github/workflows/ci.yml` and `scripts/verify-release-aab.py`) so the JSON is
   generated, not hand-typed; CI fails a `v*` build if the fingerprint file and the
   keystore disagree.
3. **Client link handling**: add `app_links` and feed initial/coming URIs into the
   router (`/product/{sku}` → product view; `/tracker/{id}` → tracker card, only when
   owned by the signed-in user, else fall back to the browse view — never leak another
   user's tracker). Guard every inbound path with the same `isHttpUrl` posture used in
   `lib/src/core/url_guard.dart`.
4. **Server support for a product entry point**: `GET /product/{sku}` on
   `services/api/routers/public_api.py` returning store list, current prices,
   last-verified timestamps and the deal-score/deal-quality signal from data api already
   holds (price history read via `get_timescale_db`). It is what a deep link needs; it is
   also what the P5 comparison view and P4's `product_view` event need.

### WS3 — Comparison view (PR C, one read endpoint + one client screen)

1. **Read**: `GET /tracked-items/{item_id}/comparison` (auth) — returns the item's store
   mappings (mirror of `POST …/stores` at `tracked_items_api.py:540`) with each store's
   current price, last-verified timestamp and 90-day low/high. For unauthenticated
   visitors, group `/deals/live` rows by `sku` client-side to build the same shape (no
   new endpoint) — browse mode's comparison uses this path.
2. **Verdict**: post that shape to the analyzer's existing
   `POST /intelligence/cross-store/{product_id}` (`routers/intelligence.py:173`) — the
   client already passes `store_prices` and `historical_prices_by_store`, so the report's
   isolation rule holds with zero shared code. Needs a third base URL in `config.dart`
   (`ANALYZER_BASE_URL`, same `--dart-define` pattern as `chatbotBaseUrl` at
   `config.dart:31`) and a new `comparison_repository.dart`.
3. **UI**: `lib/src/ui/product/comparison_view.dart` — one product, one row per store
   (store name, price, stock, "verified {time}"), cheapest flagged, spread highlighted
   ("3 stores, spread 18%"), plus the deal-quality chip. This is the screen the report's
   positioning line ("Don't just find the price. Know if it's a good deal.") is about.
4. Emit `comparison_view` (P4) and route store taps through P1's `merchant_link` with
   `source = comparison_view` so per-surface CTR separates comparison-driven clicks —
   directly feeding the report's §24 "Product-match accuracy / merchant coverage" metrics.

### WS4 — Freshness and offline honesty (PR C)

1. **Freshness label** on every price surface (tracker card, deal card, comparison row):
   `Verified {HH:mm}` / `Last checked {n} min ago` / `Stale — data unavailable since {time}`,
   derived from `TrackedItem.updatedAt` (already parsed) and `GET /price-history/{sku}`
   last point. Keys are ARB-only (owner supplies Arabic).
2. **Snapshot cache**: on a successful read, `tracked_items_repository` and
   `deals_repository` write a compact JSON snapshot to `SharedPreferences`
   (size-capped ~64 KB, pruned by `updatedAt`); on failure in live mode the UI renders
   the snapshot through `AsyncStateView` with the **stale** state rather than an empty
   list. Live-mode rethrow stays (the repository contract in
   `tracked_items_repository.dart:44-58` must not regress into silent demo fallback).
3. **Refresh affordance**: existing `POST /tracked-items/{id}/refresh` + 429 handling from
   P3 → show `Retry in {n}s` instead of an error.
4. **Cache the marketing truth**: prices are advisory — a one-line disclaimer row per
   product view ("prices we last saw at {time}; the store is the authority") which is also
   the affiliate-posture truth the report's §25 stale-price risk demands.

### WS5 — Release docs

`docs/play-store/store-listing.md`: replace the false demo-mode sentence with browse mode,
add a "works offline / shows last-checked times" line, and re-render screenshots from
browse + comparison + alerts. `docs/release-checklist.md` §6 device smoke: add "cold
install, no account → search + compare + read history; web product URL opens the app on that
product (app association verified)".

---

## 4. Files Touched

**New**
```
flutter-app/lib/src/ui/browse/browse_tab.dart
flutter-app/lib/src/ui/browse/browse_card.dart
flutter-app/lib/src/ui/product/product_view.dart
flutter-app/lib/src/ui/product/comparison_view.dart
flutter-app/lib/src/data/repositories/comparison_repository.dart
flutter-app/lib/src/data/services/snapshot_cache.dart
services/api/routers/public_api.py            -- GET /product/{sku}  (new route in this file)
services/api/tracked_items_api.py     -- GET /tracked-items/{id}/comparison
services/api/test_product_endpoint.py, test_comparison_endpoint.py
scripts/app_asset_verification.py
frontend/public/.well-known/assetlinks.json
flutter-app/test/browse_tab_test.dart, test/product_view_test.dart,
flutter-app/test/comparison_view_test.dart, test/snapshot_cache_test.dart
```
**Modified**
```
flutter-app/lib/src/routing/app_router.dart          -- GoRouter routes + params
flutter-app/lib/main.dart                       -- routeConfig / navigatorKey wiring
flutter-app/lib/src/ui/common/splash_page.dart                     -- three-way routing
flutter-app/lib/src/ui/auth/welcome_page.dart                -- CTA + value copy
flutter-app/lib/src/ui/dashboard/dashboard_page.dart              -- tab set
flutter-app/lib/src/ui/widgets/tracker_card.dart                -- freshness label, open-product (P1)
flutter-app/lib/src/ui/widgets/deal_card.dart                      -- freshness label
flutter-app/lib/src/data/repositories/tracked_items_repository.dart (snapshot)
flutter-app/lib/src/data/repositories/deals_repository.dart         (snapshot)
flutter-app/lib/src/data/config.dart                     -- ANALYZER_BASE_URL
flutter-app/lib/src/data/providers.dart                 -- comparison/browse/snapshot providers
flutter-app/pubspec.yaml                          -- app_links (+ go_router now used)
flutter-app/android/app/src/main/AndroidManifest.xml              -- deep-link intent filter
flutter-app/lib/l10n/app_en.arb + app_ar.arb                     -- browse/freshness/disclaimer keys
flutter-app/docs/play-store/store-listing.md
flutter-app/docs/release-checklist.md
frontend/Dockerfile / Caddyfile                     -- `.well-known` served verbatim (verify)
```

---

## 5. Test Strategy

| Layer | Test file | Asserts |
|---|---|---|
| Splash routing | extend `test/system_ui_test.dart` + new `test/splash_routing_test.dart` | token → dashboard; no token → browse; `welcome` reachable only by CTA; deep link `/product/{sku}` → product view; unowned `/tracker/{id}` → browse fallback |
| Browse mode | `test/browse_tab_test.dart` | renders deals + search + market header **with no token in storage**; a Track tap routes to register and replays after auth; light/dark and AR RTL |
| Comparison | `test/comparison_view_test.dart`, `test/comparison_repository_test.dart` | rows carry store, price, `verified at`; cheapest flagged; posts the exact `CrossStoreRequest` shape to the analyzer base; degraded (no mappings) shows single-store state, not a crash |
| Freshness | `test/tracker_card_test.dart`, `test/freshness_label_test.dart` | `updatedAt` renders in locale format (EN + AR-Arabic-numerals path via `lib/src/core/format/price_format.dart` locale pattern); null `updatedAt` → "not yet verified", never a fabricated time |
| Offline | `test/snapshot_cache_test.dart`, widget test for the stale state | successful read writes snapshot; failure + snapshot → stale render; failure + no snapshot → existing error state; snapshot pruned by size/age; live mode still rethrows (no demo leakage) |
| Backend | `test_product_endpoint.py`, `test_comparison_endpoint.py` | `/product/{sku}` public, limiter-tripped on abuse, returns last-verified timestamps; `/comparison` ownership-enforced (404 on another user's item) |
| Deep link | `scripts/app_asset_verification.py` unit test (CI step) | emitted `assetlinks.json` fingerprint == keystore cert fingerprint; malformed `PROD_DOMAIN` fails the build |
| Manual (release checklist §6) | cold install, no account; tap-to-track; web product URL → app on that product; airplane-mode offline launch shows last-known trackers | — |

Run: `cd flutter-app && flutter test` (66 existing tests must pass; the Navigator-based
tests are rewritten to router assertions in the same PR), `flutter analyze`, `dart
format --set-exit-if-changed lib test`, `pytest services/api/test_product_endpoint.py
services/api/test_comparison_endpoint.py -v`.

---

## 6. Milestones

| MS | Scope | Depends on | Est. |
|----|-------|-----------|------|
| MS1 | WS1 browse-first (client only, public endpoints already live) | — | 1-1.5 d |
| MS2 | WS4 freshness labels + snapshot cache (client only, no routing risk) | — | 1 d |
| MS3 | WS3 `/comparison` + `/product/{sku}` read endpoints + comparison view | MS1 (browse) | 1-2 d |
| MS4 | WS2 GoRouter adoption + deep links + asset verification | MS1 (needs `/browse` and `/product` routes) | 2 d |
| MS5 | WS5 store copy, screenshots, checklist rows | MS1-MS4 | 0.5 d |

MS1+MS2 are the cheapest, highest-leverage release items in the whole set: no new
infrastructure, no owner decision, and they directly move Gate 1.

---

## 7. Risks & Open Questions

| Risk / Question | Mitigation / Needed decision |
|---|---|
| GoRouter migration touches 6 screens and every `Navigator.*` call in a release window | sequence it as MS4, after the low-risk MS1/MS2 land; keep behavior identical and the test suite as the safety net. Option B (launch-argument routing) documented above if review rejects the migration |
| Public browse mode widens unauthenticated API exposure | all four endpoints are already public by design (`public_api.py:1-22`); apply `slowapi` limits to `/product/{sku}` and cache responses; no user data involved |
| **Chat search may be credit/session-gated** — browse search could inherit a paywall-shaped failure | verify the chatbot service posture before MS1 merges; if gated, browse search uses the public `/product`-family search added in MS3, and P3's "no payment friction before trust" rule decides it |
| Deep-link host must be final before the manifest bakes it in | `PROD_DOMAIN` is an env-injected Caddy value already (`Caddyfile`); the app build needs it as `--dart-define=APP_HOST=…` + CI guard (fail a `v*` tag when unset), and the **applicationId must be final** (plan §7 of `flutter-android-release.md` allows a `com.el72.elhaq` fallback — deep links make that decision irreversible) |
| Product entry needs `sku` in merchant URLs | `/product/{sku}` resolves from `tracked_item_stores`/scraped product ids; a URL whose sku is unknown falls back to the browse feed with an "not yet in our catalog" line rather than an error |
| Showing staleness can reduce perceived quality | the alternative (B8: unlabeled stale price) is the report's Very-high-impact risk (§25) and destroys trust when discovered; label + "refresh now" affordance converts it into a controllable state |
| Snapshot cache becomes a second source of truth | snapshots are read only on failure, always labeled stale, never written back to the server, never used in demo mode |
| Arabic copy for browse/freshness/disclaimer keys | `PI_MODEL=qwen3.8-flash-next-coder-iq1_m` → owner must supply (`AGENTS.md` hard rule, Skill 10); `test/l10n_coverage_test.dart` enforces the pair, and new strings must not enter `l10n_hardcoded_strings_test.dart`'s allow-list |

### ⚠️ Human input required
| # | Item | Why |
|---|---|---|
| H10 | Final marketing domain (`PROD_DOMAIN`) **and** final `applicationId` | app association is irreversible once published; `plans/flutter-android-release.md` still allows a package-id fallback |
| H11 | Whether the public catalog should expose a search endpoint for browse mode (vs. chat-only search) | product/economics decision (report §19 "start narrow": a narrow, accurate catalog is a business choice) |
| — | Arabic UI values for all new keys | see above; land both locales in one commit |

---

## 8. Definition of Done

- [ ] A cold install with no account can search, read deals, open a product view, compare
      stores and read price history — and only then is it asked to create an account.
- [ ] `welcome_page.dart` is a CTA, not a gate; store listing no longer claims an
      unreachable demo-mode onboarding.
- [ ] `https://{PROD_DOMAIN}/product/{sku}` opens the app on that product on a physical
      device, with `assetlinks.json` generated and fingerprint-verified in CI.
- [ ] A comparison view exists for multi-store products, computed by the analyzer service
      with no cross-service code sharing, and its taps are attributable (P1 `source`).
- [ ] Every price in the UI carries a last-verified label; null timestamps render as "not
      yet verified", never as an implied current price.
- [ ] With no network, the app renders last-known state labeled stale; with no snapshot it
      renders the existing honest error state; live mode never silently shows sample data.
- [ ] GoRouter owns routing; all screens, the 401 handler and tests behave identically.
- [ ] All suites green; PR reviewed before merge.
