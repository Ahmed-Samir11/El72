# Paymob Cash Payments (Feature 3) — Implementation Plan

Part of `plans/paymob-integration.md` (Feature 3). Depends on Features
0/1/2/4/5 (all merged). Per-feature approval document for the branch
`feat/paymob-cash-payments`.

## Goal

Cash payment flow: the user picks a cash channel (Fawry / bank), receives a
random single-use payment code with a 24 h expiry, pays at a cash point, and
credits are granted by the existing webhook (Feature 4) when Paymob detects
the deposit. The Flutter payment flow gains a method-selection step and a
cash branch with code display.

## Backend

### Schema (`infra/sql/schema.sql` + migrations `0007`/`0008`)
- `cash_payments`: `id SERIAL PK`, `user_id` FK CASCADE, `paymob_payment_id
  VARCHAR(255) UNIQUE`, `payment_code VARCHAR(32) UNIQUE` (random, non-
  sequential, 8 unambiguous chars), `cash_type CHECK IN ('fawry','bank')`,
  `package`/`amount_egp`/`status` CHECK constraints (`pending|succeeded|
  failed|canceled`), `expires_at TIMESTAMPTZ NOT NULL` (created_at + 24 h),
  `created_at`. Index `(user_id, created_at)`.
- Widen `payment_audit_log.action` CHECK with `cash_payment_created` and
  `cash_expired` (idempotent migration, same pattern as 0006).
- `PAYMENT_EVENT_TYPES` in `payment_security.py` updated in lockstep.

### Paymob client (`services/common/paymob_client.py`)
- `create_cash_payment(staging_token, cash_type, amount_paisa, currency,
  reference_id)` — cash payments use `method_type` directly (no
  payment_method indirection); returns the payment object including the
  cash `payment_code` (fallback read: `otp`, per provider field drift).

### Router (`services/api/routers/payment.py`)
- `PaymentConfirmBody` gains `cash_type`; dispatcher gains the `cash` branch.
- `_confirm_cash_payment`:
  - `cash_type` validated against the server allowlist {fawry, bank} → 400.
  - User-row lock; 5 cash confirms/hour per user (mirrors wallet, plan
    3.2 anti-abuse); enforced BEFORE consuming the staging token.
  - Shared `_consume_staging_token` (single-use, ownership-bound).
  - Server-determined amount; `reference_id` unchanged (webhook grants).
  - Code: 8 chars from an unambiguous alphabet (no 0/O/1/I), unique
    (collision retry); stored + returned. No PII in the code (3.1).
  - `expires_at = now + 24 h`; `cash_payment_created` audit (code,
    cash_type, package, amount — the code is not sensitive per 3.5).
  - Response `{payment_id, payment_code, expires_at, status: "pending"}`.
- `GET /payment/status/{payment_id}` extended for cash rows:
  - Lazy expiry (3.3): a `pending` cash row past `expires_at` transitions to
    `canceled` (committed) and is audited as `cash_expired`; a later
    succeeded webhook still wins (webhook = source of truth, consistent with
    Feature 2 semantics).
  - Code-enumeration guard (3.2): cash status lookups are rate-limited to
    1/minute per payment (atomic counter keyed by payment id; Redis
    fail-closed 503). Card/wallet lookups are unaffected (their in-app
    polling is faster).
  - `PaymentStatusResponse` gains optional `payment_code`/`expires_at`.

### Billing webhook (`services/billing/main.py`)
- `_update_cash_payment_status`: terminal webhooks transition cash rows
  (pending and prior terminal states; explicit commit — the Feature 2
  lesson).

## Flutter
- `payment_models.dart`: `CashType` enum; `CashPaymentResult`
  (payment_id/payment_code/expires_at/status); `PaymentStatusInfo` gains
  optional code/expiry.
- `payment_repository.dart`: `confirmCashPayment(...)` through the shared
  `_call` fallback path.
- Screen rename: `wallet_payment_screen.dart` → `payment_flow_screen.dart`,
  `WalletPaymentScreen` → `PaymentFlowScreen` (it now hosts the full flow):
  package → **method** (wallet | cash) → wallet step **or** cash step
  (fawry/bank tiles) → (wallet: OTP) / (cash: code display with copy button
  + expiry) → result. Cash result polls at 60 s intervals (matches the
  1/min per-payment limit) for up to 5 minutes.
- l10n en/ar for the new steps.

## Files touched
- `infra/sql/schema.sql`, migrations `0007_cash_payments.sql`,
  `0008_payment_audit_log_cash_events.sql`
- `services/api/cash_payment_models.py` (new)
- `services/api/routers/payment.py`, `services/api/payment_security.py`,
  `services/api/manual_payment_models.py` (ORM audit CHECK)
- `services/common/paymob_client.py`
- `services/billing/main.py`
- `services/api/test_cash_payment.py` (new)
- `flutter-app/lib/src/data/models/payment_models.dart`
- `flutter-app/lib/src/data/repositories/payment_repository.dart`
- `flutter-app/lib/src/ui/payment/payment_flow_screen.dart` (renamed)
- `flutter-app/lib/src/ui/subscription_screen.dart`
- `flutter-app/lib/l10n/*.arb` + generated localizations
- `flutter-app/test/payment_repository_test.dart`,
  `flutter-app/test/payment_flow_screen_test.dart` (renamed)

## Test strategy
- Backend (pytest, in-memory SQLite, mocked paymob_client):
  - confirm: valid fawry/bank; invalid/missing cash_type (400, staging
    survives); 6th confirm → 429; server-determined amount; missing code
    from Paymob → 502, no row; audit carries the code.
  - status: pending returns code + expiry; lazy expiry → canceled +
    `cash_expired` audit; expired row + succeeded webhook → succeeded
    (webhook wins); owner-only 404; 2nd lookup within 60 s → 429.
  - billing: webhook transitions cash rows (succeeded/failed), persisted.
- Flutter: repository (confirmCashPayment parsing, demo fallback), widget
  flow (method selection → cash step → code display; wallet path regression).
- Gates: `pytest services`, `ruff check services`, `black --check services`,
  `flutter analyze`, `dart format --set-exit-if-changed`, `flutter test`.
