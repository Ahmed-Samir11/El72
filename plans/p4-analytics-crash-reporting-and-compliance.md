# Plan: P4 — Analytics Pipeline, Crash Reporting, and Compliance Truth

**Branch:** `feat/app-analytics-and-crash-reporting` (off `main`)
**Date:** 2026-10-29
**Status:** Draft for approval
**Series:** 4 of 5 release-priority plans (P1 affiliate clicks, P2 notifications, P3
free-tracker model, **P4**, P5 activation/trust). P4 consumes P1/P2/P3 call sites, so
MS3+ of this plan lands after those PRs merge; MS1-MS2 are independent.

---

## 1. Goal

Ship the launch year already instrumented, and make the legal/store documents
describe the app that actually ships:

1. **First-party funnel events** for the user journey, so Gates 1-6
   (`Do users activate / return / click merchants / do clicks convert / does contribution
   exceed variable cost`) can be answered from the release cohort instead of reconstructed
   after the fact (report §23 "design analytics before launch rather than attempting to
   reconstruct behavior later", §24 priority 7, §22 "Instrument before optimizing").
2. **Crash reporting**, so field failures on the flows that were recently refactored
   (chat conversation reset, secure storage, 401 re-login, price refresh) are visible
   rather than silent — and so the data-safety answer about crash reports can be honest.
3. **Compliance reconciliation**: privacy policy placeholders filled, both locales
   published, and the deletion claim matched to a real, reachable user action
   (`DELETE /auth/me` exists server-side but nothing in the app can call it).

Non-goals: third-party ad/analytics SDKs (report §7 and store listing rule out ad
SDKs; keep first-party only), ML/model quality metrics (analyzer already owns those),
user-level paid acquisition analysis.

---

## 2. Current State — Evidence

| # | Finding | Evidence |
|---|---|---|
| A1 | No telemetry at all in the client — no analytics, metrics or event calls in `flutter-app/lib` | grep over `flutter-app/lib` for analytics/telemetry/metric → only l10n key `advancedAnalytics` (a *plan tier* string) |
| A2 | No crash reporting (still an open item in the release plan) | `flutter-app/pubspec.yaml` has no `sentry_flutter`/`firebase_crashlytics`; `plans/flutter-android-release.md` "Crash reporting — ⏳ Blocked on H2"; finding D8 in the same plan |
| A3 | The only user-behavior fact in the DB is an affiliate click, and it has no user dimension | `services/api/models.py:166-175` (`AffiliateClick` — no `user_id`), `infra/sql/schema/postgres.sql:314` |
| A4 | The analytical substrate already exists and is TimescaleDB-based; new facts should land next to it, not in a parallel silo | `services/analyzer/analytics.py` ("TimescaleDB analytical fact constellation", conformed dimensions), `services/analyzer/intent_upsert.py` (`retailer_analytics` aggregates), endpoints `services/analyzer/routers/intelligence.py:182-196` (`/analytics/category-trends`, `/metrics/platform`) |
| A5 | The API service already holds a TimescaleDB session, so ingesting a fact from `POST /events` breaks no service boundary | `services/api/dependencies.py:29-31,47-58` (`TimescaleSessionLocal`, `get_timescale_db`), `services/api/routers/public_api.py` uses it |
| A6 | Rate limiting + Prometheus are already in place to protect an ingest endpoint | `services/api/main.py:172-184` (`slowapi.Limiter(key_func=_client_ip)`, `PrometheusMiddleware`), `services/api/monitoring/metrics.py`, `infra/monitoring/prometheus_rules.yml` |
| A7 | Privacy policy is a DRAFT with unfilled mandatory placeholders and no Arabic sibling | `flutter-app/docs/play-store/privacy-policy.md` — `Last updated: [DATE]`, `**[SUPPORT EMAIL / ADDRESS — fill in before publishing]**`, "Ar translation … to be produced by a native Arabic reviewer" |
| A8 | The data-safety form promises a deletion path the user cannot reach | `store-listing.md` §4 "Do you provide a way to delete data? **Yes** — deleting the account removes the associated personal data"; server has `@router.delete("/me")` at `services/api/routers/auth.py:85`, **zero** references to it in `flutter-app/lib` (grep `deleteAccount` → none) |
| A9 | Deletion is anonymization, and behavior facts would outlive the user | `services/api/routers/auth.py:86-105` deletes `Alert` + `TrackedItem` rows and rewrites `phone` to `deleted:<id>`, `status = "DELETED"`; `AffiliateClick` (A3) and any future event fact have no erasure rule |
| A10 | The app talks to more than one base URL already, so an analytics base is not a new pattern | `flutter-app/lib/src/data/config.dart:14-38` (`apiBaseUrl`, `chatbotBaseUrl` via `--dart-define`) |

---

## 3. Approach

### WS1 — Event store (TimescaleDB fact, canonical schema first)

Add to `infra/sql/schema/timescaledb.sql` (append-only time-series; the report's §23
taxonomy is the contract):

```sql
CREATE TABLE IF NOT EXISTS app_events (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
  user_id      TEXT,                 -- operational analytical id, never a phone
  session_id   TEXT NOT NULL,        -- install-scoped, from the client
  event        TEXT NOT NULL,        -- allowlist below
  sku TEXT, store_id TEXT, category TEXT, source TEXT, channel TEXT,
  product_id TEXT, deal_id TEXT, item_id TEXT,
  properties   JSONB                  -- bounded: 20 keys, 1 KB value cap
);
SELECT create_hypertable('app_events', 'ts');
-- indexes: (ts), (event, ts), (user_id, ts), GIN on properties when needed
```

**Event allowlist = the report's taxonomy**, extended with the fields P1-P3 produce:
`search`, `product_view`, `comparison_view`, `track_created`, `track_removed`,
`price_change`, `alert_sent`, `alert_opened`, `merchant_click`, `purchase` (only if a
network ever exposes it — declared, never invented), plus `limit_hit`, `error_observed`.

Ownership statement recorded in `.agents/AGENTS.md`-style docs (from a maintainer session)
and in this plan: **`services/api` owns event *ingestion*, `services/analyzer` owns
rollups and KPI views**. No cross-service imports; the rollups read the same DB.

**Erasure rule (A9)**: extend `delete_account` (`services/api/routers/auth.py:85`) to
`UPDATE app_events SET user_id = NULL WHERE user_id = …` and, after P1 adds
`affiliate_clicks.user_id`, do the same there. Retention: a documented window
(default 180 days) enforced by `infra/sql/` cleanup + a scheduled job recorded in
`infra/monitoring/ALERT_RUNBOOKS.md`, so a deleted user's funnel trail cannot outlive them.

### WS2 — Server ingest + KPI rollups (PR A)

1. `POST /events` on `services/api` (new `services/api/routers/events.py`):
   - accepts a **batch** (`{"events":[…]}`, max 50, max 32 KB) → `202`, returns nothing
     but a count; never echoes user content.
   - validates against the event allowlist + field caps; unknown event type → 400
     (fail fast, per `AGENTS.md` error rule) but a *malformed single row inside a batch*
     is skipped and counted in Prometheus (`el72_events_rejected_total`).
   - auth optional: reuse the P1-style `get_optional_user` (added to
     `services/api/dependencies.py`) so an authenticated session writes `user_id`,
     an anonymous browse session writes only `session_id`.
   - `@limiter.limit(...)` with the existing `_client_ip` key; bounded by Prometheus.
2. **KPI rollups in `services/analyzer`** (new `services/analyzer/funnel_metrics.py`
   + a GET on `services/analyzer/routers/intelligence.py:196`'s neighbourhood, e.g.
   `/metrics/funnel`): per-day/week cohort numbers —
   `QSA` (the report's North Star: search ∪ product_view ∷ comparison ∪ track_created ∪
   merchant_click, definition pinned in code and doc), activation (≥1 search),
   D7/D30/D90 retention, trackers/user, alert_opened rate, `merchant_click` CTR by
   `source`/`store` joined to `affiliate_clicks`, and per-channel contribution joined to
   P2's `alert_events.channel`. **Every number is labelled cohort-level, not market fact**
   (report §1's fact/estimate discipline).
3. Alert rules for the funnel in `infra/monitoring/prometheus_rules.yml`
   (event ingest lag, ingest rejection spike, zero-activity regression).

### WS3 — Client telemetry (PR B)

New files:
```
flutter-app/lib/src/data/services/analytics_client.dart
flutter-app/lib/src/data/services/app_session.dart
flutter-app/lib/src/data/services/crash_reporting.dart
```

1. **`AppSession`**: a random 128-bit id in `SharedPreferences` (never in secure storage:
   it is not a credential), created on first launch, rotated when the account is deleted.
2. **`AnalyticsClient`** (Riverpod provider in `lib/src/data/providers.dart`):
   - buffered queue (max 50), flushes on interval (30 s), on route change and in
     `main.dart` teardown path; **fire-and-forget** — a flush failure re-queues up to one
     batch then drops, never blocks a screen, never surfaces an error to the user;
   - posts to `<ANALYTICS_BASE_URL or apiBaseUrl>/events` via the shared Dio client
     (auth header already injected by `ApiClient`); default to the **same** base URL as
     the API gateway to keep one TLS/CORS surface (`config.dart` pattern already supports
     a second base if the owner prefers analyzer's port);
   - `demoMode` **disables telemetry** (sample data must not pollute KPIs);
   - records `event`, `session_id`, `user_id` server-side, plus ids only —
     **no phone numbers, no free-text queries** (a search *query* is user content;
     log its length and matched category instead of the string).
3. **Call sites** (each is a one-line instrumentation, no behavior change):
   `search` → `chatbot_repository.dart` (search submitted), `product_view`/`comparison_view`
   → tracker & comparison views (P5 adds the comparison view), `track_created`/`track_removed`
   → `create_tracker_sheet.dart` and the delete flow, `limit_hit` → P3's 409/429 branches,
   `merchant_click` → P1's `merchant_link` (shares the `event_id` with
   `affiliate_clicks.event_id` — P1 WS1 already provides the column), `alert_opened` → P2's
   `/alerts/{id}/open`, `error_observed` → `AsyncStateView` error paths (type + status only).
4. **Crash reporting**: `sentry_flutter` initialized in `main.dart` behind
   `--dart-define=SENTRY_DSN=`; if the Firebase project from P2 lands first, **Crashlytics
   is the drop-in alternative** (same H2), documented as a one-line swap table:

   | Provider | Cost | Notes |
   |---|---|---|
   | Sentry (`sentry_flutter`, DSN dart-define, CI secret `SENTRY_DSN`) | account + DSN | no Firebase dependency; recommended default |
   | Firebase Crashlytics | free with the P2 Firebase project | adds `firebase_flutter` + `google-services.json` |

   `beforeSend` must **redact** phone-like strings, the stored token, and any URL query
   (A7/A8 PII posture; `AGENTS.md` "PII: Encrypt with AES-256 before DB write" is the
   analogue — a crash payload must not carry the identifier at all), attach
   `release`, `environment`, `session_id` (not `user_id` prose), and keep
   `sample_rate: 1.0` for v1 (low volume cohort).
5. **Release wiring**: `.github/workflows/ci.yml` `flutter-ci`/`publish-release` steps
   pass `--dart-define=SENTRY_DSN=...` alongside the existing
   `--dart-define=API_BASE_URL="$PROD_API_BASE_URL"` (line ~307), and fail the release
   build if the DSN is missing on a `v*` tag (mirrors the existing
   `RELEASE_VERSION_CODE` guard so a release can't silently ship unobservable).

### WS4 — Compliance and store-readiness reconciliation (PR C)

1. **Privacy policy**: fill `Last updated`, add the real hosted URL and support
   contact (owner input), add the *new* disclosures that accompany this release —
   first-party event logging (what is and is not recorded, retention window, opt-out
   by deleting the account), crash reports to the chosen provider, and a
   "no third-party advertising or analytics SDKs" line that stays true.
   Arabic version produced by a native reviewer (owner), and the EN/AR pair kept in sync.
2. **Data-safety rows** (`docs/play-store/store-listing.md` §4) updated to match the
   shipped build: crash reports now leave the device (declare provider + what is
   redacted), events are first-party (no advertising use), and "way to delete data" is
   backed by the now-reachable in-app action (WS4.3).
3. **Account deletion, made real**: a "Delete my account" confirmation in the Profile
   tab (destructive-action pattern: explicit confirm, typed verification or a second
   tap, and post-deletion routing to the browse state from P5), calling
   `DELETE /auth/me` (which today anonymizes and cascades to `Alert`/`TrackedItem`),
   plus WS1's erasure extension so behavior facts lose the user link. The policy
   sentence then matches observed behavior verbatim (report §4 "How long we keep your
   data").
4. **Content rating + screenshots** (release checklist §5): render the 6 screenshots
   from the *release* feature set (browse/deals/alerts/history/profile, light theme, EN
   and one AR RTL shot).

---

## 4. Files Touched

**New**
```
services/api/routers/events.py
services/api/dependencies.py                  -- get_optional_user (shared with P1)
services/analyzer/funnel_metrics.py
services/api/test_events.py
services/analyzer/test_funnel_metrics.py
flutter-app/lib/src/data/services/analytics_client.dart
flutter-app/lib/src/data/services/app_session.dart
flutter-app/lib/src/data/services/crash_reporting.dart
flutter-app/test/analytics_client_test.dart
flutter-app/test/app_session_test.dart
```
**Modified**
```
infra/sql/schema/timescaledb.sql                     -- app_events hypertable + indexes
infra/sql/cleanup/* , infra/monitoring/ALERT_RUNBOOKS.md   -- retention job + alert rules
services/api/main.py                        -- include events router
services/api/monitoring/metrics.py   -- event ingest counters
services/analyzer/app.py, routers/intelligence.py     -- /metrics/funnel
services/api/routers/auth.py              -- erasure of event/behavior user links
flutter-app/lib/main.dart                         -- crash reporter init, flush on exit
flutter-app/lib/src/data/config.dart           -- ANALYTICS_BASE_URL (optional override)
flutter-app/lib/src/data/providers.dart
flutter-app/lib/src/data/repositories/chatbot_repository.dart (search)
flutter-app/lib/src/ui/common/async_state_view.dart (error_observed)
flutter-app/lib/src/ui/dashboard/dashboard_page.dart  -- Delete-my-account action (PR C)
flutter-app/lib/l10n/app_en.arb + app_ar.arb        -- delete-account copy (owner-supplied AR)
flutter-app/pubspec.yaml                        -- sentry_flutter (or firebase_crashlytics)
.github/workflows/ci.yml                       -- SENTRY_DSN dart-define + release guard
flutter-app/docs/play-store/privacy-policy.md (+ .ar.md)
flutter-app/docs/play-store/store-listing.md
flutter-app/docs/release-checklist.md
```

---

## 5. Test Strategy

| Layer | Test file | Asserts |
|---|---|---|
| Backend ingest | `services/api/test_events.py` | batch caps enforced (51 events → 413/400), unknown event type → 400, one malformed row inside an otherwise valid batch is skipped and counted, unauthenticated batch stores `user_id IS NULL` with a `session_id`, `Retry-After` on limiter trip |
| Backend erasure | `services/api/test_auth_deletion.py` (new/extended) | after `DELETE /auth/me`: alerts + tracked items gone, `app_events.user_id` and `affiliate_clicks.user_id` detached from the deleted user, re-login impossible, tokens rejected |
| Rollups | `services/analyzer/test_funnel_metrics.py` | QSA counts each taxonomy member once per session-day; D30 defined on the pinned session boundaries; CTR joins `merchant_click`↔`affiliate_clicks` on `event_id` and never double-counts |
| Flutter unit | `test/analytics_client_test.dart` | batching ≤50, flush on demand, failures never throw into the caller, `demoMode` disables entirely, no phone-shaped value ever reaches the payload (assert on the serialized body) |
| Flutter unit | `test/app_session_test.dart` | id created once, survives reinstall simulation of other prefs, rotated on account deletion |
| Flutter widget | `test/dashboard_*` | Delete-my-account requires two deliberate actions, calls `DELETE /auth/me`, clears the token and routes to the browse state; cancelled action leaves the session intact |
| Crash reporting | `test/crash_reporting_test.dart` | `beforeSend` returns `null`/scrubbed for a payload containing a phone-shaped string and an Authorization header |
| CI | `flutter-ci` | `flutter test --dart-define=SENTRY_DSN=` with a dummy DSN keeps tests hermetic (no network) |

Run before PR: `pytest services/api/test_events.py services/analyzer/test_funnel_metrics.py
services/api/test_auth_deletion.py -v`, `cd flutter-app && flutter test` (66 green +
new), `flutter analyze`, `dart format --set-exit-if-changed lib test`.

---

## 6. Milestones

| MS | Scope | Depends on | Est. |
|----|-------|-----------|------|
| MS1 | WS1 schema + `POST /events` + Prometheus + erasure extension | — | 1-2 d |
| MS2 | WS3 client session/analytics/crash plumbing + call sites that already exist today (`search`, `track_created`, `track_removed`, `error_observed`) | MS1 | 1-2 d |
| MS3 | WS2 `/metrics/funnel` KPI rollups (QSA, D30, CTR) | MS1, P1 MS1 (`event_id` join) | 1-2 d |
| MS4 | Remaining call sites as P2/P3/P5 land (`alert_opened`, `limit_hit`, `comparison_view`, `merchant_click` source) | P1/P2/P3 | +0.5 d each |
| MS5 | WS4 privacy/data-safety rewrite, in-app account deletion, screenshots, rating | MS2 (provider known), owner inputs | 1-2 d |

---

## 7. Risks & Open Questions

| Risk / Question | Mitigation / Needed decision |
|---|---|
| **H2** — Sentry account/DSN, or Firebase project for Crashlytics | must be created by the owner; CI fails a `v*` release without it (explicit guard, like `RELEASE_VERSION_CODE`) |
| Instrumenting user behavior is a **privacy commitment**, not just code | first-party only, no ad SDKs, retention window, no raw query text, deletion path in-app; report sources cite the Egyptian PDPC — the policy must be written before the event table ships, not after |
| Low-volume cohort makes rates noisy | rollups return cohort-level counts with denominators; every dashboard number labelled ESTIMATE per report §1 |
| Telemetry latency/expense on 2G/3G sessions (report §6: data costs matter in Egypt) | batched, ≤1 request per 30 s, never on the tap path, dropped rather than re-queued unboundedly |
| Analytics could be read as an ad-network foothold | explicit test that the payload host is only `apiBaseUrl`; store listing keeps "no advertising SDKs" true |
| Event table growth | hypertable + documented retention; GIN indexes added only when a query needs them |
| QSA definition drift (report: "exact definition should be finalized once analytics data exists") | the definition is pinned in `funnel_metrics.py` with a docstring and a test, and any change is a reviewed PR, not a comment edit |
| Double-counting affiliate clicks via P1's own logging | one join key (`event_id`), asserted by `test_funnel_metrics.py` |

### ⚠️ Human input required
| # | Item | Why |
|---|---|---|
| H2 | Crash-reporting provider (Sentry DSN or Firebase project + `google-services.json`) | cannot be generated in-repo; also gates P2 MS3 |
| H8 | Support contact + hosted privacy-policy URL, and the Arabic policy/UI strings | legal review + native reviewer; `PI_MODEL=qwen3.8-flash-next-coder-iq1_m` forbids authoring Arabic here (`.agents/AGENTS.md`, Skill 10) — land `app_en.arb` + `app_ar.arb` together on owner-supplied text |
| H9 | Retention window and the erasure policy wording | business/legal decision that the report explicitly asks the team not to overstate |

---

## 8. Definition of Done

- [ ] `app_events` exists in `infra/sql/schema/timescaledb.sql`, is a hypertable, and
      every event written matches the pinned taxonomy allowlist.
- [ ] Each of the funnel steps the app can currently perform emits exactly one event with
      `session_id` and (when authenticated) `user_id` — including taps that lead to P1's
      merchant click row.
- [ ] `/metrics/funnel` reports activation, D7/D30 retention, trackers/user,
      alert-open rate and merchant CTR per store/source, labelled as cohort measurements.
- [ ] Crash reporting is live in release builds, guarded by CI, and provably redacts
      phone numbers and credentials.
- [ ] Privacy policy + data-safety form describe exactly the shipped build (events,
      crash reports, no ad SDKs, deletion path), in both locales, with a real hosted URL.
- [ ] "Delete my account" is reachable in the app, calls `DELETE /auth/me`, and detaches
      behavior facts from the deleted user.
- [ ] Screenshots/content rating reflect the release feature set; review agent shows no
      CRITICAL/WARNING findings.
