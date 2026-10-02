# Credits Display & Friendly 402 → Upgrade Flow

## Goal

1. **Show the user's remaining credits in the app** (currently the number is
   invisible; users only discover they're out of credits when a request fails).
2. **Replace the raw `402` error** ("Insufficient credits. Upgrade your plan
   to add more trackers." — developer-facing text) with a **user-friendly
   message**: "You've reached your limit" + a **button that navigates to the
   Plans/Subscription screen**.

## Context / Current State

- Backend endpoint **already exists** (no backend work needed):
  `GET /credits/balance` → `{"balance": <int>, "tier": "<str>"}`
  (`services/api/routers/credits.py`, registered in `main.py`).
- `SubscriptionScreen` already exists and is reachable today via the
  Profile tab "Manage" button (`dashboard_page.dart` `_ProfileTab`).
- The Profile tab **hardcodes** the subtitle `freePlan` — it never shows the
  real balance or tier.
- `TrackedItemsRepository.createFromUrl` converts any non-2xx into a generic
  `Exception(detail)`, so the UI cannot distinguish "out of credits" (402)
  from any other failure; `CreateTrackerSheet` renders it as a plain error
  SnackBar with the raw server string.

## Approach

### 1. Data layer (new)

- **`lib/src/data/models/credit_balance_model.dart`** — small model
  `CreditBalance { final int balance; final String tier; }` with
  `fromJson(Map)` (Google-style docstrings, per coding standards).
- **`lib/src/data/repositories/credits_repository.dart`** —
  `CreditsRepository.getBalance()` calling `GET /credits/balance` via
  `ApiClient`, returning `CreditBalance`. On `DioException`, fall back to a
  neutral balance in demo mode (`DemoData`), else rethrow — same fallback
  convention as the other repositories.
- **`lib/src/data/providers.dart`** — add:
  - `creditsRepositoryProvider` (plain `Provider`)
  - `creditBalanceProvider` (`FutureProvider<CreditBalance>`)

### 2. Distinct 402 signal (repo change)

- **`tracked_items_repository.dart`** — in `createFromUrl`, catch
  `DioException`; if `response.statusCode == 402`, throw a new typed
  exception **`InsufficientCreditsException`** (defined in the same file or a
  small `exceptions.dart`), otherwise keep today's behavior
  (`Exception(detail)`).

### 3. UI changes

- **`create_tracker_sheet.dart`** — in the catch block, special-case
  `InsufficientCreditsException`: show an `AlertDialog` (not a SnackBar):
  - Title: "You've reached your limit"
  - Body: friendly explanation (free plan includes N trackers; upgrade for
    more)
  - Actions: "Upgrade plan" button → `Navigator.push` to
    `SubscriptionScreen`; plus a dismiss ("Not now") action.
  - All other errors keep the existing SnackBar path.
- **`dashboard_page.dart` `_ProfileTab`** — watch `creditBalanceProvider`:
  - Replace hardcoded `freePlan` subtitle with the live balance, e.g.
    "3 trackers left" (localized, pluralized via l10n placeholder).
  - Loading/error: keep current static text (graceful, no spinner needed in a
    list tile).

### 4. Localization

- **`lib/l10n/app_en.arb`** + **`lib/l10n/app_ar.arb`** — new keys:
  - `creditsRemaining` with `{count}` int placeholder
    ("{count} trackers left" / Arabic equivalent)
  - `reachedLimitTitle` ("You've reached your limit")
  - `reachedLimitBody` (friendly explanation mentioning the free allowance)
  - `upgradePlan` ("Upgrade plan")
  - `notNow` ("Not now")
- Regenerate via `flutter gen-l10n` (writes `lib/l10n/app_localizations*.dart`).
  **Keep line endings LF** (the repo is LF; Windows CRLF churn is what left the
  current dirty state).

### 5. Demo mode

- `DemoData`: add a demo `CreditBalance` (e.g. balance 3, tier "free") used
  by `CreditsRepository` when `AppConfig.demoMode` is on and the request
  fails, so offline/demo UI never shows an error state for credits.

## Files Touched

| File | Change |
|------|--------|
| `flutter-app/lib/src/data/models/credit_balance_model.dart` | new |
| `flutter-app/lib/src/data/repositories/credits_repository.dart` | new |
| `flutter-app/lib/src/data/providers.dart` | +2 providers |
| `flutter-app/lib/src/data/repositories/tracked_items_repository.dart` | 402 → `InsufficientCreditsException` |
| `flutter-app/lib/src/ui/create_tracker_sheet.dart` | upgrade dialog on 402 |
| `flutter-app/lib/src/ui/dashboard/dashboard_page.dart` | live balance in Profile tab |
| `flutter-app/lib/l10n/app_en.arb`, `app_ar.arb` | new strings |
| `flutter-app/lib/l10n/app_localizations*.dart` | regenerated (LF!) |
| `flutter-app/test/credits_repository_test.dart` | new |
| `flutter-app/test/create_tracker_sheet_test.dart` | new (402 dialog) |
| `flutter-app/test/dashboard_credits_test.dart` | new (balance display) |

No backend changes. No schema changes.

## Test Strategy

- **Unit (`credits_repository_test.dart`)**:
  - Parses `{balance, tier}` from a faked Dio response.
  - Demo-mode fallback returns demo balance on network failure.
  - `createFromUrl` throws `InsufficientCreditsException` on 402 and a
    generic exception on 500 (fake Dio transport).
- **Widget (`create_tracker_sheet_test.dart`)**:
  - Pump sheet with a repo stub returning 402 → tap "Start tracking" →
    dialog appears with the friendly title + "Upgrade plan" button; tapping it
    navigates to `SubscriptionScreen`.
- **Widget (`dashboard_credits_test.dart`)**:
  - Profile tab shows "3 trackers left" from a stubbed provider.
- **Existing suite must stay green**: `flutter test` (includes
  `l10n_coverage_test.dart`, which enforces every arb key is used — new keys
  must be referenced in code).
- **Manual (emulator)**: log in as an account with 0 credits → add tracker →
  friendly dialog + button lands on Plans screen; Profile tab shows live
  balance.

## Out of Scope

- Payment flow / Paymob integration (already handled by `billing` service +
  `SubscriptionScreen._launchPayment`).
- Changing credit amounts, tiers, or pricing.
- Backend endpoint changes (`/credits/balance` already exists and is
  sufficient).
