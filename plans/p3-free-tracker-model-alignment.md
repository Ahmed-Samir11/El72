# Plan: P3 — Free-Tracker Model Alignment (retire the credit/paywall UX)

**Branch:** `feat/free-tracker-fair-use-limits` (off `main`)
**Date:** 2026-10-29
**Status:** Approved — MS1 (PR A, backend) implemented on this branch; MS2/MS3
(PR B, Flutter client) follow after PR A merges, and are blocked on owner-supplied
Arabic copy (see §7).
**Series:** 3 of 5 release-priority plans (P1 affiliate clicks, P2 notifications,
**P3**, P4 analytics, P5 activation/trust). P2 is the plan currently in flight
(`feat/push-notifications-and-alert-surface`); P3 branches off `main`, not off it.
**Companion backend branch:** this plan lands as PR A (backend contract) then PR B
(Flutter client), backend first.

---

## 1. Goal

Make the shipped product match the business model the strategy document actually chose,
without deleting the payment machinery:

1. **Tracking is free**, bounded by *fair-use* limits (per-user cap + rate limiting), not
   by a credit purchase (report §2 new hypothesis, §27 final recommendation, §24 priority 9
   "Anti-abuse/rate limiting — protects free tracker economics").
2. **No payment decision is asked of a user before they trust the product** — the release
   APK shows no credit packages, no "Upgrade plan", no Paymob flow.
3. **The rails stay merged and reversible** — the report keeps "potential premium later"
   open (§18 "Do not build yet" column, §19 future directions), so the payment code is
   feature-flagged out of the release build, not deleted.

Non-goals: removing Paymob/webhook code or its tests, deleting the `user_credits` ledger,
pricing changes to any future premium tier, changing scraper/analyzer economics.

---

## 2. Current State — Evidence

| # | Finding | Evidence |
|---|---|---|
| M1 | The client presents a purchasable-credits model: two server-priced packages, one-time EGP payments, wallet/cash rails | `flutter-app/lib/src/ui/subscription_screen.dart` (`CreditPackage.all`, `l10n.egpOnce`, `l10n.buyNow` → `PaymentFlowScreen`), `flutter-app/lib/src/ui/payment/payment_flow_screen.dart` (866 lines: Vodafone Cash / Orange Money / Etisalat Cash / Fawry, wallet OTP, 24-hour cash code) |
| M2 | Exhausting credits is a **paywall-shaped** UX: 402 → "You've reached your limit… **Upgrade plan**" | `flutter-app/lib/src/data/repositories/tracked_items_repository.dart:56-79` (`InsufficientCreditsException`), `flutter-app/lib/src/ui/create_tracker_sheet.dart:113-140` (dialog + `nav.push(SubscriptionScreen)`) |
| M3 | The Profile tab's "account" affordance is a credit counter plus a `Manage` → paywall route | `flutter-app/lib/src/ui/dashboard/dashboard_page.dart:363-405` (`creditsRemaining`, `creditBalanceProvider`, `SubscriptionScreen` push) |
| M4 | Client-side pricing constants and copy encode "3 free credits then buy more" | `flutter-app/lib/src/data/models/payment_models.dart:57` (`CreditPackage.freeCredits = 3`), `app_en.arb`: `freeCreditsDesc` "3 free credits included", `standardPackageDesc` "10 credits…", `premiumPackageDesc`, `subscriptionPlans`, `proPlan`, `businessPlan` |
| M5 | **The server is already closer to the free model than the client is**: the free tier starts at 100 credits, i.e. 100 trackers before any payment | `services/api/credits.py:19-22` (`TIER_STARTING_CREDITS = {"free": 100}`), `services/api/credits.py:55-70` (`deduct` raises 402 only at zero), call sites `tracked_items_api.py:243` and `:966` (`deduct(..., reason="tracker_created")`) |
| M6 | Payment + subscription routers are always exposed on the release backend | `services/api/main.py:205-208` (`payment_router`, `subscription_router` unconditionally included) |
| M7 | The model conflict is documented on both sides, so nobody is sure which is current | report §2 ("Old model: paid credits after free allowance / Payment friction suppresses adoption") vs §27 (**FREE SHOPPING INTELLIGENCE + FREE TRACKING + AFFILIATE MONETIZATION**); `.agents/instructions.md` still states "Revenue model: Freemium — credit-based tracking…", and that file is guarded by `scripts/check_agents.py` |
| M8 | Store assets inherit the friction and the payment surface | `flutter-app/docs/play-store/store-listing.md` ("Yours to control… demo mode…", no payment claims today, but §4 data-safety and screenshots must be re-checked against the shipped feature set once payments disappear) |

**Why it is release-priority:** the strategy document's own §2 risk column names the
old model's failure mode as *"payment friction suppresses adoption"*, and its recommendation
is explicit: *"Keep basic tracking free, but use fair-use limits and rate limiting to prevent
abuse. Do not turn limits into artificial payment friction during the validation year."*
Shipping M1-M4 means shipping the superseded model: the release measures nothing about the
hypothesis it was built to test, and it adds payment-rail, refund and data-safety surface
to v1 for no measured gain.

---

## 3. Approach

### WS1 — Server: fair-use limits instead of credit deduction (PR A)

1. **Introduce the enforcement mode** in `services/api/credits.py`, env-driven
   (feature-flag convention already used for `DEMO_MODE` / `MOCK_WHATSAPP` in
   `docker-compose.yml`):
   ```
   CREDITS_ENFORCEMENT = fair_use (default) | on | off
   ```
   - `fair_use`: tracker creation does **not** call `deduct`. Instead enforce
     (a) a per-user **active tracker cap** `FAIR_USE_MAX_TRACKERS` (default 100, mirroring
     today's effective free-tier ceiling in M5), and (b) a **creation rate limit**
     (minimum 3 s between creations, `slowapi` already wired at `services/api/main.py:172-174`).
   - Cap exceeded → `409 Conflict` (or `422`) with a structured detail
     `{code: "fair_use_cap", active_trackers, cap}`. Rate exceeded → `429` **with
     `Retry-After` seconds** (the client needs a countdown, and the current code only
     documents 429 in a comment — `tracked_items_repository.dart:96`).
   - `on`: today's behavior (credits + 402). `off`: no limits at all (dev/tests).
2. **Add the observability endpoint** `GET /usage/limits` (auth):
   `{active_trackers, cap, created_last, retry_after_seconds, enforcement}` — the client
   chip and the KPI rollups both read this, and it replaces "credits remaining" in the
   Profile tab. Keep `GET /credits/balance` untouched for the dormant payment path.
3. **Register payment/subscription routers behind the flag** in `services/api/main.py`:
   include them only when `CREDITS_ENFORCEMENT == "on"` or an explicit
   `PAYMENTS_ENABLED=true`. A default release backend then exposes no Paymob surface
   (M6 → smaller attack surface, honest store listing, no financial-transaction claims).
4. **No schema change**: `user_credits` / `credit_transactions` stay as-is (ledger kept
   for a future premium model). Document that in the plan, not in a migration.
5. **Tests updated deliberately**: `services/api/test_credits.py` keeps the `on` cases and
   adds `fair_use` cases; `services/api/test_tracked_items_api.py` gets
   `cap → 409`, `rate → 429 + Retry-After`, and the old 402 case retained under
   `CREDITS_ENFORCEMENT=on`.

### WS2 — Client: remove the paywall UX, add fair-use UX (PR B)

1. **Compile-time feature flag** in `flutter-app/lib/src/data/config.dart`:
   ```dart
   static const bool paymentsEnabled =
       bool.fromEnvironment('ENABLE_PAYMENTS', defaultValue: false);
   ```
   Default **false** ⇒ the release APK (`flutter build appbundle`, and CI's
   `flutter-ci`/`publish-release` jobs in `.github/workflows/ci.yml`) contains no
   payment UI. Dev builds pass `--dart-define=ENABLE_PAYMENTS=true` to keep the
   screens testable. Nothing is deleted, so P3 is one revert away from being undone.
2. **Profile tab**: replace `creditsRemaining` + `Manage → SubscriptionScreen`
   (`dashboard_page.dart:398-405`) with the fair-use state from `/usage/limits`
   ("Tracking {n} of up to {cap} products at once") and no route to a purchase screen
   when `paymentsEnabled == false`. `creditBalanceProvider` and
   `credits_repository.dart` stay for the flagged path.
3. **Creation error handling** in `create_tracker_sheet.dart`:
   - remove the `InsufficientCreditsException → "Upgrade plan"` branch behind the flag;
   - add a **cap** branch (409): explain the ceiling, offer to delete a tracker (the
     delete flow already exists per `plans/tracker-delete-and-price-ranges.md`) or to wait,
     and a **rate** branch (429): countdown from `Retry-After` reusing the existing
     `AsyncStateView` retry affordance (`lib/src/ui/common/async_state_view.dart`) and the
     `retry` label already in the ARB.
   - Map the new statuses in `tracked_items_repository.dart` as typed exceptions
     (`FairUseCapException`, `RateLimitedException`), mirroring the existing
     `InsufficientCreditsException` pattern so the UI never shows a raw server string.
4. **Tracker card chip** (optional, cheap): a "Tracking {n}" count in the dashboard header
   region rather than a scarcity message — the report's framing is *free usage at scale*,
   not scarcity.
5. **ARB keys** — see §7 (owner-supplied Arabic). New keys must land in `app_en.arb`
   **and** `app_ar.arb` together; `test/l10n_coverage_test.dart` enforces it and
   `test/l10n_hardcoded_strings_test.dart`'s allow-list must **shrink** when the paywall
   strings stop being referenced. Keys that become unused in a flagged build are deleted
   from both locales in the same PR (dead copy in a shipped listing is a review hazard).

### WS3 — Store assets and documentation reconciliation (PR B, same branch)

1. `docs/play-store/store-listing.md`: state "free to track" as the value proposition,
   remove/​avoid any payment claim, and re-audit §4 data-safety rows (with payments out
   of v1 there are no financial transactions to describe; the phone-number, tracked-items
   and crash-report rows stay as they are in P4's scope).
2. `docs/release-checklist.md` §5 store assets: add "no payment screens in the release
   screenshots" (screenshots must be rendered from the release feature set).
3. **Doc conflict** — `.agents/instructions.md` says "Freemium — credit-based tracking".
   Editing `.agents/` requires a maintainer session (`scripts/check_agents.py`); so this
   PR records the supersession in `plans/p3-free-tracker-model-alignment.md` +
   `business_research.md`, and the `.agents` line is corrected by the maintainer (tracked
   as a follow-up, not silently worked around).

### WS4 — Keep the free model *economically* defensible

The report's warning (§2 "Why free tracking can fail": inactive trackers, notification
cost, low-intent users) is handled here, not later:

1. Cap + rate limit (WS1) bound scraper fan-out and notification volume.
2. Expose `active_trackers` per user to the KPI pipeline (P4) so "trackers/user" and
   "dormant trackers" become measurable, and the §13 break-even math stays computable.
3. Do **not** add artificial scarcity (no "save your credits" messaging).

---

## 4. Files Touched

**New**
```
services/api/usage_limits.py                  -- cap/rate checks + /usage/limits payload
services/api/test_usage_limits.py
```
**Modified (backend, PR A)**
```
services/api/credits.py                     -- enforcement modes, fair-use checks
services/api/tracked_items_api.py      -- cap/rate checks at :243 and :966, drop deduct in fair_use
services/api/main.py            -- flag-gated payment/subscription routers, /usage/limits route
services/api/test_credits.py
services/api/test_tracked_items_api.py
docker-compose.yml, .env.example   -- CREDITS_ENFORCEMENT, FAIR_USE_MAX_TRACKERS, PAYMENTS_ENABLED
business_research.md                 -- supersession record
```
**Modified (Flutter, PR B)**
```
flutter-app/lib/src/data/config.dart                          -- paymentsEnabled flag
flutter-app/lib/src/data/repositories/tracked_items_repository.dart  -- typed cap/rate exceptions
flutter-app/lib/src/ui/create_tracker_sheet.dart     -- cap/rate dialogs, flag-gated upgrade path
flutter-app/lib/src/ui/dashboard/dashboard_page.dart     -- fair-use chip instead of credits
flutter-app/lib/src/ui/subscription_screen.dart          -- flag-gated entry point
flutter-app/lib/src/data/repositories/credits_repository.dart (kept, flagged use)
flutter-app/lib/src/data/models/payment_models.dart
flutter-app/lib/src/data/providers.dart
flutter-app/lib/l10n/app_en.arb + app_ar.arb
flutter-app/docs/play-store/store-listing.md
flutter-app/docs/release-checklist.md
flutter-app/test/dashboard_credits_test.dart, test/credits_repository_test.dart,
flutter-app/test/create_tracker_sheet_test.dart
```

---

## 5. Test Strategy

| Layer | Test file | Asserts |
|---|---|---|
| Backend | `test_usage_limits.py`, `test_credits.py`, `test_tracked_items_api.py` | `fair_use`: no credit row change, 101st tracker → 409 with `{code, active_trackers, cap}`, rapid creations → 429 **with** `Retry-After`; `on`: legacy 402 path still intact; `off`: unlimited |
| Backend router | `test_tracked_items_api.py` + `test_main.py` | payment/subscription routes are absent (404) under the default release configuration |
| Flutter unit | `test/tracked_items_repository_test.dart` | 409 → `FairUseCapException`, 429 → `RateLimitedException(retryAfter)`; 402 still maps under the legacy mode |
| Flutter widget | `test/create_tracker_sheet_test.dart` | cap dialog offers Delete/Not now; 429 shows a countdown + Retry; **no** "Upgrade plan" route when `ENABLE_PAYMENTS` is false (run `flutter test --dart-define=ENABLE_PAYMENTS=false`), and the existing upgrade route test runs under `=true` |
| Flutter widget | `test/dashboard_credits_test.dart` updated | Profile shows "Tracking n of cap" and no purchase affordance in release config |
| i18n | `test/l10n_coverage_test.dart`, `test/l10n_hardcoded_strings_test.dart` | both locales carry every new key; allow-list strictly shrinks |
| CI | `.github/workflows/ci.yml` | add `ENABLE_PAYMENTS=false` to the release build step so the shipped artifact is provably paywall-free |

Run before PR: `pytest services/api/test_credits.py services/api/test_tracked_items_api.py
services/api/test_usage_limits.py -v`; `cd flutter-app && flutter test` (all 66 existing
tests still pass, with the deliberate updates above) + `flutter analyze` + `dart format`.

---

## 6. Milestones

| MS | Scope | Depends on | Est. |
|----|-------|-----------|------|
| MS1 | WS1 backend: enforcement mode, cap/rate checks, `/usage/limits`, gated routers, tests (PR A) | — | 1-2 d |
| MS2 | WS2 client: flag, Profile change, cap/rate dialogs, typed exceptions, ARB keys (PR B) | MS1 | 1-2 d |
| MS3 | WS3 store assets, screenshots re-audit, release-checklist row, doc-supersession record | MS2 | 0.5 d |
| WS4 hooks into P4's KPI work (tracker counts per user) | MS1, P4 MS2 | — | — |

Total ≈ 3 days across two PRs. Both PRs must be reviewed (no self-merge) and PR B must
land after PR A merges.

---

## 7. Risks & Open Questions

| Risk / Question | Mitigation / Needed decision |
|---|---|
| The free-tracker economics are **explicitly unproven** (report §27: "the free tracker should not be treated as proven") | P4 measures trackers/user and clicks/user from launch; P1 makes the revenue leg measurable. If affiliate revenue per MAU is too low, the flagged payment rails return in a later release — that is the §9-12 "Scenario B" response, prepared, not improvised |
| Deleting the paywall touches tests that pin it (`test/dashboard_credits_test.dart`, `test/credits_repository_test.dart`, 402 cases in `test_tracked_items_api.py`) | update them deliberately in the same PR with the mode matrix, so a reviewer sees intent rather than silent weakening |
| Cap value (100) is an assumption | env-configurable; chosen to match today's *actual* effective free-tier ceiling (M5), so the change cannot reduce anyone's current capability |
| Users tracking hundreds of dormant items → cost (report §2/§25) | cap + rate limit + P4 "dormant tracker" KPI; consider auto-pausing inactive trackers in a later release (not this PR) |
| Server and client drift on the cap message | cap payload is structured (`{active_trackers, cap}`); the client never parses prose, and the 429 countdown comes from `Retry-After` |
| A reviewer may read flagging as dead code | the flag is the report's "do not build yet" mechanism made explicit; PR body states that `ENABLE_PAYMENTS=true` keeps all payment tests live |
| `.agents/instructions.md` conflict | maintainer-only edit; recorded here and in `business_research.md` |

### ⚠️ Human input required
| # | Item | Why |
|---|---|---|
| H6 | Confirm the **launch economic model** is "free tracking + fair-use caps" (and the cap number) for the store release | it is a business decision that changes revenue, not a code detail |
| H7 | Whether `.agents/instructions.md` and `business_research.md` get rewritten now (maintainer session) | agent-dir edits are blocked outside maintainer sessions |
| — | Arabic values for all new/changed keys | `PI_MODEL=qwen3.8-flash-next-coder-iq1_m` → per `.agents/AGENTS.md` and Skill 10, do not author or retype Arabic; ask the owner and land both locales in one commit. Also: the *deletion* of paywall keys must touch both files |

---

## 8. Definition of Done

- [x] Default backend: `CREDITS_ENFORCEMENT=fair_use`, tracker creation never deducts,
      cap → 409, rate → 429 with `Retry-After`, and **no** Paymob routes registered.
      (MS1 — see §9 Implementation Record)
- [ ] Default Flutter release build (`ENABLE_PAYMENTS=false` in CI) contains no credit
      package, no "Upgrade plan", no wallet/cash payment screen — verified by CI build
      flag and widget tests.
- [ ] Profile tab communicates fair use ("Tracking n of cap"), not scarcity or payment.
- [ ] Legacy credit/payment code + tests remain green under `on` / `ENABLE_PAYMENTS=true`.
- [ ] Store listing, data-safety rows, screenshots and release checklist describe the
      free-tracker feature set.
- [ ] Supersession of the "freemium credit" wording is recorded in `business_research.md`
      (and flagged for a maintainer to fix `.agents/instructions.md`).
- [ ] All suites green; both PRs reviewed by another party before merge.

---

## 9. Implementation Record

### MS1 — PR A (backend contract), this branch

Landed as three commits off `main` (`eb317bd`):
`usage_limits.py` + creation-route enforcement → the mount gate in `main.py` → the
test matrix. `pytest services -q --ignore=services/chatbot` is green (the chatbot
collection error — `from arabic_nlp import …` — and the `tests/test_mobile_e2e.py`
live-server failures are pre-existing on `main`, not introduced here; CI's gate is
`pytest services -q`).

The mode matrix, as pinned by tests:

| Mode | Tracker creation | Refusal shape | Payment routers |
|---|---|---|---|
| `fair_use` (default) | never touches the ledger | 409 `{code: "fair_use_cap", active_trackers, cap}` / 429 + `Retry-After` + `{code: "creation_rate_limit", retry_after_seconds}` | not mounted |
| `on` | one credit per tracker, same session/transaction | 402 (unchanged prose) | mounted |
| `off` | unlimited | none | mounted only if `PAYMENTS_ENABLED=true` |

Deviations from §3, deliberate and worth a reviewer's attention:

1. **The enforcement mode lives in `services/api/usage_limits.py`, not `credits.py`.**
   One module owns mode resolution, the cap, the rate window and the
   `/usage/limits` payload; `credits.py` documents that it is the `on` path and
   stays mode-blind (pinned by a test so the flag cannot defang the ledger).
2. **`main.py` gained `mount_routers(app, *, payment_surface: bool)`.** The payment
   decision is one auditable call rather than six `include_router` lines a later
   edit can silently un-gate, and both postures are testable without re-importing
   `main` (which would rebuild its engine). `tests/test_main.py` asserts the release
   build mounts no `/payment`, `/subscription` or `/admin` route and answers 404.
3. **Rate limiting is a per-user process-local window, not a slowapi per-IP rule.**
   The cap is per-user, so the throttle keys on the same identity; the plan's
   `Retry-After` contract needs an exact countdown, which slowapi does not own here.
   Same single-instance assumption `tracked_items_api._refresh_attempts` documents.
   Enforcement runs **before** any insert, so a refusal writes nothing.
4. **`tests/test_mobile_e2e.py` was updated in this PR** (not in §4). It pinned
   "3 free credits" and "a tracker deducted a credit"; both now read the mode from
   the live server (`GET /usage/limits`) and assert the matching contract, and two
   rows were added: 429 + `Retry-After` on rapid creation, and 404 on every Paymob
   route of a fair-use backend. A suite that documents the old model is drift.
5. **Test harness posture:** `services/api/conftest.py` sets
   `CREDITS_ENFORCEMENT=off` (the mode §1 reserves for dev/tests) and
   `PAYMENTS_ENABLED=true` *before* any test module imports `main`, because the
   payment routers mount at import. The release posture is therefore asserted
   explicitly (point 2 above), never inherited from the environment.
6. **Env:** `CREDITS_ENFORCEMENT`, `FAIR_USE_MAX_TRACKERS`, `PAYMENTS_ENABLED`
   documented in `.env.example` and written explicitly in the compose `api` block.
   No schema change: `user_credits` / `credit_transactions` stay as-is.

**Interim state to note in the PR body:** between PR A merging and PR B landing,
the shipped app maps a cap 409 through its generic error path (its "Upgrade plan"
dialog only triggers on 402, which fair use never sends). No release build should
ship PR A without PR B.

**Still open (PR B, and owner input):** MS2/MS3 (client flag, Profile chip,
cap/rate dialogs, ARB keys in both locales, store assets), and H6/H7/Arabic from
§7.
