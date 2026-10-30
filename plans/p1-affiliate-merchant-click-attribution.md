# Plan: P1 — Affiliate Merchant-Click Attribution

**Branch:** `feat/affiliate-merchant-click-attribution` (off `main`)
**Date:** 2026-10-29
**Status:** In implementation — MS1 backend: PR #46 (`feat/affiliate-click-attribution`); MS2+MS3 client incl. tracker-card "Open product" + l10n pair: PR #47 (`feat/affiliate-merchant-click-attribution`, blocked on #46); MS4 awaits H1/H5 owner input.
**Series:** 1 of 5 release-priority plans (P1 → P2 notifications, P3 free-tracker model, P4 analytics, P5 activation/trust). See each sibling plan's "Series" note.

---

## 1. Goal

Every departure from the app to a merchant becomes **attributable, monetizable and reliable**:

1. Merchant taps route through the affiliate redirect, so each click writes an
   attributable `affiliate_clicks` row and opens a **tagged** merchant URL.
2. The click carries context — store, sku, deal, source surface, session — so affiliate
   CTR / EPC and the QSA North Star can be computed (report §7, §11).
3. Android can actually open the real merchant hosts (`amazon.eg`, `noon.com`,
   `jumia.com.eg`), not a host that does not exist in this repo.

Non-goals: merchant ranking optimization, category commission tuning, click→purchase
reporting from networks (report §7 lists these as *eventual* variables).

---

## 2. Current State — Evidence

| # | Finding | Evidence |
|---|---|---|
| C1 | Deal card tap opens the raw scraped URL; no affiliate tagging, no click log | `flutter-app/lib/src/ui/widgets/deal_card.dart:29` (`launchUrl(uri)`) |
| C2 | Chat search-result card does the same | `flutter-app/lib/src/ui/chatbot/search_result_card.dart:64` |
| C3 | **Tracker cards have no way to open the product at all** — the highest-intent object in the app generates zero clicks | `flutter-app/lib/src/ui/widgets/tracker_card.dart` (only `onTap`/`onRetry` for price refresh, no launch) |
| C4 | The server endpoint already exists and is unused by the client — the word "affiliate" appears **zero times** in `flutter-app/` | `services/api/routers/affiliate.py:12` (`GET /affiliate/redirect` → logs `AffiliateClick`, 307 to tagged URL); `app.include_router(affiliate_router.router)` at `services/api/main.py:199` |
| C5 | Android declares one launch handler, for a host that exists nowhere else in the repo | `flutter-app/android/app/src/main/AndroidManifest.xml:42` `android:host="www.comsumart.com"`; `grep -ri comsumart` → only the manifest + build intermediates. The real merchants: `services/api/affiliate.py:12-15` `STORE_HOSTS` |
| C6 | `affiliate_clicks` cannot answer any per-user question: no user, no source, no session | `services/api/models.py:166` (`AffiliateClick`: `store_id, sku, deal_id, target_url, affiliate_url, clicked_at`); `infra/sql/schema/postgres.sql:314` |
| C7 | `/affiliate/redirect` is unauthenticated and takes an arbitrary `target_url` bounded only by `store_for_url` | `services/api/routers/affiliate.py:15-24` |
| C8 | Affiliate tagging is silently a no-op when the env var is absent | `services/api/affiliate.py:41-47` (`if not tag: return target_url`) |
| C9 | Tag values are never configured in the dev/prod env contract | `.env.example` has no `AMAZON_AFFILIATE_TAG` / `NOON_AFFILIATE_TAG` / `JUMIA_AFFILIATE_TAG` |

**Business framing** (`presentation/EL72_Team_Business_Strategy_Report.pdf` §7, §11, §24):
revenue is `affiliate clicks → merchant conversion → AOV → commission`; the North Star
is QSA and the KPI set is `affiliate CTR, EPC, merchant conversion, revenue/user`.
§24 lists "Affiliate attribution — required to prove monetization." A v1 shipped as-is
produces **zero attributable clicks**, so Gate 3 ("do users click merchants?") and
Gate 4 ("do clicks convert?") cannot be evaluated in the validation year.

---

## 3. Approach

### WS1 — Server: make the click row answer business questions

1. **Widen `affiliate_clicks`** (canonical schema first, per `infra/sql/schema/postgres.sql`
   rule):
   ```sql
   ALTER/CREATE additions on affiliate_clicks:
     user_id            UUID REFERENCES users(id) ON DELETE CASCADE  -- nullable: web demo clicks
     session_id         TEXT,            -- client install/session id, for CTR per user
     source             TEXT NOT NULL DEFAULT 'unknown',  -- deal_feed | search_result | tracker_card | browse | web
     sku                  (already present, keep)
     category             TEXT,          -- for the report's category-level commission analysis
     event_id             TEXT,          -- joins to app_events (P4)
     created_at           (rename of clicked_at; keep clicked_at as alias in the model for one release)
   CREATE INDEX idx_affiliate_clicks_user_time ON affiliate_clicks(user_id, created_at);
   CREATE INDEX idx_affiliate_clicks_source    ON affiliate_clicks(source, created_at);
   ```
   Update `AffiliateClick` in `services/api/models.py` in the same PR.
2. **Optional-credential attribution**: add `get_optional_user` to
   `services/api/dependencies.py` (parses the bearer token when present, returns `None`
   otherwise — do **not** require auth, the landing page calls it too), and store the
   resolved `user_id`. Never log a phone number; `user_id` only (PII rule).
3. **Trust the client's context, not its URL**: keep `store_for_url(target_url)` as the
   authority for `store_id`, and require the client to pass `sku`/`deal_id` as
   **opaque ids**, not URLs. Add a `category` lookup from `tracked_items`/`deals` when
   `sku` resolves; ignore any client-supplied store id on mismatch (400).
4. **Fail loudly when tagging is unconfigured**: at `main.py` startup, if any
   `*_AFFILIATE_TAG` is unset while `APP_ENV=production`, log a structured WARNING naming
   the store, and expose `GET /affiliate/config` (admin-token only) reporting per-store
   tag presence. Rationale: an untagged click is logged revenue that will never exist
   (C8) — this is the difference between "we measured zero" and "we forgot to configure".
5. **Rate-limit the redirect**: `@limiter.limit(...)` on `/affiliate/redirect` using the
   existing `slowapi` `Limiter(key_func=_client_ip)` already wired in `main.py:172-174`,
   so the endpoint cannot be used as an open redirect multiplier.

### WS2 — Client: one merchant-link component, used by every surface

New files:
```
flutter-app/lib/src/data/repositories/affiliate_repository.dart
flutter-app/lib/src/ui/common/merchant_link.dart
```

1. `AffiliateRepository.resolve({required String targetUrl, String? sku, String? dealId,
   String? category, required String source})` → `String resolvedUrl`:
   - `GET /affiliate/redirect` via the shared `ApiClient` dio with
     `options: {maxRedirects: 0, maxFollowRedirects: 0}` and read the
     `Location` header (do **not** let Dio follow: we need the URL, not the bytes).
   - Returns the resolved (tagged) URL.
   - **Never blocks the user:** on any error (400 unknown host, network failure,
     timeout) return the original `targetUrl` and record the reason for telemetry
     (P4 wires the counter; until then `debugPrint`). Monetization is an optimization
     of the tap, never a precondition for it.
2. `openMerchant(context, ...)` in `merchant_link.dart` is the **only** place that may
   open a web URL from a card:
   - validates with the existing `isHttpUrl` (`lib/src/core/url_guard.dart`) — the
     same rule the chat UI and chatbot repository already share;
   - resolves through `AffiliateRepository`;
   - launches with `launchUrl(uri, method: UriLaunchMethod.externalBrowser)` (Android:
     the merchant app when installed, else browser) and keeps the existing
     `unableToOpen(title)` snackbar fallback.
3. Rewire the three call sites to the shared component:
   - `deal_card.dart` (replace the inline `launchUrl` at line 29),
   - `search_result_card.dart` (line 64; keep the `isLaunchable` gate),
   - **new** `tracker_card.dart` affordance: a labeled "Open product" trailing
     action on every tracker card (highest-intent population in the product).
4. Pass real context at each site: `deal.id` → `dealId`, deal/tracker store + sku from
   `TrackedItem`/`Deal`/`SearchResultModel` (`SearchResultModel.storeId` at
   `chat_message_model.dart:241`), `source` enum string.

### WS3 — Android manifest: allowlist the merchants the app actually shows

1. Replace the single `<queries>` entry with one per supported merchant host, mirroring
   `STORE_HOSTS` in `services/api/affiliate.py`:
   ```
   amazon.eg | noon.com | jumia.com.eg   (+ any store host added to STORE_HOSTS later)
   ```
2. **Anti-drift test, Python side** (new file `services/api/test_affiliate_manifest_sync.py`):
   parse `flutter-app/android/app/src/main/AndroidManifest.xml`, extract every
   `<queries>` `android:host`, and assert the set equals the union of
   `STORE_HOSTS[*]`. This is the only guard that keeps the app's launch handlers and the
   server's merchant allowlist from diverging again (C5 happened because nothing linked
   them).

### WS4 — Release gate + docs

1. `flutter-app/docs/release-checklist.md` §6 physical-device smoke: add explicit rows —
   "tap a deal → the opened URL carries the store's affiliate tag", "tap a tracker →
   Open product works on Amazon.eg / noon / Jumia from a real device".
2. `.env.example`: add `AMAZON_AFFILIATE_TAG=`, `NOON_AFFILIATE_TAG=`, `JUMIA_AFFILIATE_TAG=`
   (empty defaults; secrets are never committed).
3. Business contract note in this plan: which network/program each store's revenue
   actually flows through (report §30 references Amazon Egypt Associates and ArabClicks)
   is an **owner** fact, recorded in `business_research.md`, not assumed here.

---

## 4. Files Touched

**New**
```
services/api/test_affiliate_manifest_sync.py
flutter-app/lib/src/data/repositories/affiliate_repository.dart
flutter-app/lib/src/ui/common/merchant_link.dart
flutter-app/test/affiliate_repository_test.dart
flutter-app/test/merchant_link_test.dart
```
**Modified**
```
infra/sql/schema/postgres.sql                      -- affiliate_clicks columns + indexes
services/api/models.py                               -- AffiliateClick fields
services/api/affiliate.py                    -- tag-presence reporting helper
services/api/routers/affiliate.py            -- optional user, source/category, limiter
services/api/dependencies.py                 -- get_optional_user
services/api/main.py                       -- startup tag-presence warning, /affiliate/config
services/api/test_affiliate.py            -- attribution + limiter + passthrough cases
.env.example                            -- *_AFFILIATE_TAG keys
flutter-app/android/app/src/main/AndroidManifest.xml
flutter-app/lib/src/ui/widgets/deal_card.dart
flutter-app/lib/src/ui/widgets/tracker_card.dart
flutter-app/lib/src/ui/chatbot/search_result_card.dart
flutter-app/lib/src/data/providers.dart
flutter-app/lib/l10n/app_en.arb (+ app_ar.arb)      -- "Open product" label
flutter-app/docs/release-checklist.md
```

---

## 5. Test Strategy

| Layer | Test file | Asserts |
|---|---|---|
| Backend unit | `services/api/test_affiliate.py` | click row stores `user_id`, `session_id`, `source`, `category`; unauthenticated caller still logs (`user_id IS NULL`); unknown host → 400; store mismatch → 400; missing tag → URL passthrough but click still logged; `/affiliate/config` reports presence |
| Backend anti-drift | `services/api/test_affiliate_manifest_sync.py` | manifest hosts == `STORE_HOSTS` union |
| Flutter unit | `test/affiliate_repository_test.dart` (Dio-mocked, pattern of `test/tracked_items_repository_test.dart`) | params serialized correctly; `maxRedirects: 0` honored; on 400/network error returns original URL and never throws |
| Flutter widget | `test/merchant_link_test.dart`, updates to `test/search_result_card_test.dart`, new `test/deal_card_test.dart` / `test/tracker_card_test.dart` | tapping calls the affiliate resolve with the right `source` before launching; non-http urls never launch; snackbar on failure |
| Manual | release checklist §6 | tag visible in the opened URL on a physical device, AR + EN |

Run: `pytest services/api/test_affiliate*.py -v` and `cd flutter-app && flutter test`
(both must be green before PR; 66 Flutter tests currently pass and must stay passing).

---

## 6. Milestones

| MS | Scope | Depends on | Est. |
|----|-------|-----------|------|
| MS1 | Schema + model + router attribution + limiter + startup warning (backend, one PR: `feat/affiliate-click-attribution`) | — | 1-2 d |
| MS2 | Client repository + shared `merchant_link` + three call sites + tracker-card affordance + l10n key | MS1 contract | 1-2 d |
| MS3 | Manifest allowlist + anti-drift test + release-checklist rows | MS2 | 0.5 d |
| MS4 | Tag env config verified against real merchants on a device (needs owner tag values) | H1, owner tags | 0.5 d |

MS1 and MS2 land as two PRs (backend first, so the client is never talking to a
contract that does not exist yet).

---

## 7. Risks & Open Questions

| Risk / Question | Mitigation / Needed decision |
|---|---|
| **H1** — production HTTPS base URL still unset (`plans/flutter-android-release.md`) | blocks device verification of MS4; MS1-MS3 are testable against the emulator endpoint |
| Real affiliate tags for noon / Jumia may not be commission-bearing at all | record per-store economics in `business_research.md`; keep the click *logging* working regardless, so a null tag is visible as "no revenue path", not "no traffic" |
| Dio following the 307 would hide the tagged URL | explicit `maxRedirects: 0` and asserted in unit tests |
| Unauthenticated open-redirect surface grows | existing `store_for_url` allowlist + slowapi limiter + no client-supplied store trust |
| External-browser launch changes "stay in app" UX | acceptable for v1 (in-app WebView would add a browser stack and its own security surface); revisit with a merchant WebView in a later release |
| Adding an "Open product" action to tracker cards invites low-intent taps (report §4: free tracker may attract low-intent users) | keep it a secondary affordance (icon + label, not a full-width button) and measure its CTR separately by `source` |

### ⚠️ Human input required
| # | Item | Why |
|---|---|---|
| H1 | Production `API_BASE_URL` for the release build | needs the real gateway host (owner/backend) |
| H5 | **Affiliate tag / program values per merchant** (`AMAZON_AFFILIATE_TAG`, `NOON_AFFILIATE_TAG`, `JUMIA_AFFILIATE_TAG`) and which network each store's revenue flows through | cannot be derived in-repo; without them the loop logs clicks but earns nothing |

### ⚠️ Localization constraint (hard rule)
The new "Open product" label must land in `app_en.arb` **and** `app_ar.arb` in the same
commit. `PI_MODEL=qwen3.8-flash-next-coder-iq1_m` is active, so per `.agents/AGENTS.md`
the Arabic value **must be supplied by the user**, not authored here; `test/l10n_coverage_test.dart`
enforces the pairing and `test/l10n_hardcoded_strings_test.dart` forbids a hardcoded
English label in the card.

---

## 8. Definition of Done

- [ ] Every merchant tap in the app goes through `merchant_link` → `/affiliate/redirect`
      and produces an `affiliate_clicks` row with `user_id`, `session_id`, `source`,
      `store_id`, `sku`/`deal_id`.
- [ ] The opened URL carries the merchant's affiliate tag on a physical device.
- [ ] Tracker cards offer "Open product"; deal cards and search results keep working.
- [ ] Manifest allowlist matches `STORE_HOSTS`, enforced by `test_affiliate_manifest_sync.py`.
- [ ] A misconfigured tag is loud (startup warning + `/affiliate/config`), not silent.
- [ ] Backend + Flutter test suites green; `flutter analyze` and `dart format` clean.
- [ ] Release checklist §6 updated with the two new device-smoke rows.

---

## 9. Implementation Record (deviations actually shipped)

| Planned | Shipped | Why |
|---|---|---|
| `user_id UUID REFERENCES users(id)` | `user_id INTEGER REFERENCES users(id) ON DELETE CASCADE` | `users.id` is `SERIAL` in this repo (schema + ORM); FK type must match reality |
| Manifest fix + `test_affiliate_manifest_sync.py` in MS3 | Both in PR #46 (MS1 branch) | Every PR must be green; the manifest pair and the test that pins it cannot be split across merge order |
| `Limiter(key_func=_client_ip)` from `main.py` on the route | Module-local `Limiter(key_func=get_remote_address)` in `routers/affiliate.py` (payment.py precedent), limit `"200/minute"` as a module constant read per request | `main.py` cannot be imported from a router (cycle); dynamic limit lets tests dial it down instead of firing 201 requests |
| Dio `RequestConfig(maxRedirects: 0, maxFollowRedirects: 0)` | Dio 5.x `Options(followRedirects: false, maxRedirects: 0)` | `RequestConfig`/`maxFollowRedirects` do not exist in the pinned dio (^5.9); the two knobs that exist are the two that matter |
| `launchUrl(uri, method: UriLaunchMethod.externalBrowser)` | `launchUrl(uri, mode: LaunchMode.externalApplication)` | pinned url_launcher `^6.3.1`; `UriLaunchMethod` is the 7.x API. `externalApplication` = merchant app when installed, else browser |
| `clicked_at` column renamed in every tree | Canonical fresh schema + migration `0012_affiliate_click_attribution.sql` (deployed Postgres) + `create_tables.ensure_columns` rename (in-place upgraded DBs); ORM keeps `clicked_at = synonym('created_at')` | Skill 4: canonical schema, migration and owning model move together |

The "Open product" label landed on owner authorization during implementation: the Arabic value (open + al_product, composed from the file's existing words to avoid invented wording) was supplied by the owner request, and both locales + generated getters landed in one commit; `l10n_coverage_test` guards the pair.

Still open until owner input: MS4 device verification (H1 production `API_BASE_URL`, H5 per-store tag values).
