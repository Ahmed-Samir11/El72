# Paymob Wallet Payments (Feature 2) — Implementation Plan

Part of `plans/paymob-integration.md` (Feature 2). Depends on Features 0/1/4/5
(all merged). This plan is the per-feature approval document for the branch
`feat/paymob-wallet-payments`.

## Goal

Wallet payment flow for Egyptian mobile wallets (Vodafone Cash, Orange Money,
Etisalat Cash, Fawry): user picks package + wallet + wallet number, server
creates the Paymob payment, user enters the OTP in-app, credits are granted by
the existing webhook (Feature 4) once Paymob confirms. No native SDK needed —
wallet payments are pure REST, so the Flutter app side ships in this feature.

## Backend

### Schema (`infra/sql/schema/postgres.sql`; historical migrations `0005`/`0006` archived under `infra/sql/migrations/postgres/legacy/`)
- New table `wallet_payments`: `id SERIAL PK`, `user_id` FK users CASCADE,
  `paymob_payment_id VARCHAR(255) UNIQUE`, `wallet_type` (canonical upper-case
  type, **never the wallet number**), `package` + `amount_egp` + `status`
  CHECK constraints (`pending_otp|processing|succeeded|failed|canceled`),
  `otp_attempts INT >= 0`, `otp_expires_at TIMESTAMPTZ`, `created_at`.
  Index `(user_id, created_at)`. The wallet number is deliberately NOT stored
  (plan 2.8: log the type, not the number).
- Widen `payment_audit_log.action` CHECK with `wallet_payment_created`
  (idempotent DROP/ADD CONSTRAINT migration, same pattern as 0004).
- `PAYMENT_EVENT_TYPES` in `services/api/payment_security.py` updated in lockstep
  (test_payment_security.py asserts schema/Python parity).

### Paymob client (`services/common/paymob_client.py`)
- `create_wallet_payment_method(staging_token, wallet_type, wallet_number)` —
  wallet types mapped to Paymob's enum (`Vodafone_Cash`, `Orange_money`,
  `Etisalat_Cash`, `Fawry`).
- `confirm_wallet_otp(payment_id, otp)` — OTP confirmation. The existing `_post`
  never logs request payloads, so OTPs cannot leak via the client.

### Router (`services/api/routers/payment.py`)
- `POST /payment/confirm` extended with `method_type="wallet"`:
  - `wallet_type` validated against server allowlist (2.7), matched
    case-insensitively and stored in canonical upper-case.
  - `wallet_number` validated with `^01[0125]\d{8}$` (010/011/012/015 + 8
    digits) BEFORE any Paymob call (2.2).
  - Per-user rate limit 5 wallet confirms/hour (2.2), enforced under the
    user-row lock like the card flow, BEFORE consuming the staging token.
  - Staging token: same single-use, 15-min-TTL, ownership-bound flow as cards
    (2.5). Non-destructive `get` first, atomic `pop` after ownership check.
  - Amount server-determined from package (2.4); `reference_id` keeps the
    `elhaq-{user_id}-{package}` format so the Feature 4 webhook grants credits
    without changes.
  - New `wallet_payment_created` audit event (type, not number) (2.8).
  - Response `{payment_id, status: "pending_otp"}` (or `processing` if Paymob
    skips the OTP challenge).
- `POST /payment/confirm-otp` (new):
  - Owner-only lookup by `paymob_payment_id` (404 otherwise, no existence leak).
  - slowapi limit `5/10 minute` keyed by payment_id (Feature 5 rate-limit table).
  - Business rules (2.1): max 3 OTP attempts per payment, row locked
    (`FOR UPDATE`) so concurrent submits serialize; after the 3rd failure the
    payment is `canceled`. OTP expires 60 s after the payment was created; an
    expired OTP cancels the payment and is audited as `token_expired`.
  - Malformed OTP (not 4-8 digits) → 400 without consuming an attempt.
  - Failed Paymob verification → 200 `{status: "failed", attempts_remaining}`,
    `otp_failed` audit event (OTP value NEVER in detail — 2.6) and
    `security_monitor.record_failure("otp_failed")` wired here (Feature 5
    deferred wiring).
  - Provider network/5xx errors → 502 WITHOUT consuming an attempt (outcome
    unknown).
- `GET /payment/status/{payment_id}` extended to also resolve wallet payments
  (owner-only; card lookup first, then wallet; effective status = latest
  `payment_logs` row if present, else the row's status).

### Billing webhook (`services/billing/main.py`)
- `_update_wallet_payment_status`: after the webhook terminal state, transition
  `wallet_payments` rows in `pending_otp|processing` to the terminal status
  (raw UPDATE, same pattern as `_update_card_payment_status`).
- Wire `security_monitor.record_failure("webhook_signature_failed")` on failed
  signature verification (Feature 5 deferred wiring; alert once per threshold
  crossing).

## Flutter app (wallet flow is pure REST — no native SDK)

- `lib/src/data/models/payment_models.dart`: `WalletType` enum (4 wallets),
  `WalletPaymentStatus`, confirm/status response models.
- `lib/src/data/repositories/payment_repository.dart`: `startPayment`,
  `confirmWalletPayment`, `confirmWalletOtp`, `getPaymentStatus` over the
  existing `ApiClient` (demo-mode fallback convention like `CreditsRepository`).
- `lib/src/ui/payment/wallet_payment_screen.dart`: step-based flow —
  1) package selection (Standard 30 EGP / 10 credits, Premium 90 EGP / 30
  credits, server-priced), 2) wallet type tiles + Egyptian number input with
  client-side validation (same regex), 3) confirmation dialog echoing the
  wallet number (2.3), 4) OTP entry, 5) result with status polling
  (pending → succeeded/failed/canceled).
- `subscription_screen.dart`: replace the mock `paymob.com/pay/...` URL and the
  stale monthly pricing with the real one-time packages; tapping Standard or
  Premium opens the wallet payment flow.
- l10n: new strings in `app_en.arb` + `app_ar.arb`, regenerated with
  `flutter gen-l10n`.

## Files touched
- `infra/sql/schema/postgres.sql`
- Historical migrations: `infra/sql/migrations/postgres/legacy/0005_wallet_payments.sql` and `infra/sql/migrations/postgres/legacy/0006_payment_audit_log_wallet_event.sql`
- `services/api/wallet_payment_models.py` (new)
- `services/api/routers/payment.py`
- `services/api/payment_security.py`
- `services/common/paymob_client.py`
- `services/billing/main.py`
- `services/api/test_wallet_payment.py` (new)
- `flutter-app/lib/src/data/models/payment_models.dart` (new)
- `flutter-app/lib/src/data/repositories/payment_repository.dart` (new)
- `flutter-app/lib/src/ui/payment/wallet_payment_screen.dart` (new)
- `flutter-app/lib/src/ui/subscription_screen.dart`
- `flutter-app/lib/l10n/app_en.arb`, `app_ar.arb` + generated localizations
- `flutter-app/test/payment_repository_test.dart` (new),
  `flutter-app/test/wallet_payment_screen_test.dart` (new)

## Test strategy
- Backend (pytest, in-memory SQLite, mocked `paymob_client`):
  - confirm: valid wallet; invalid package/type/number (400 before Paymob
    call); cross-user staging hijack rejected and NOT consumed; replay after
    consume rejected; rate limit 6th confirm → 429; server-determined amount.
  - confirm-otp: success (processing/succeeded); 3 failures → canceled + 400;
    expired OTP → canceled + `token_expired` audit; malformed OTP → 400 without
    attempt; provider 502 → no attempt consumed; OTP never appears in audit
    detail; owner-only 404; slowapi 5/10min per payment.
  - status: owner-only, wallet + card resolution, webhook terminal state
    reflected.
  - billing: webhook transitions wallet row; signature-failure alert wiring.
- Flutter: repository tests (mocked Dio), wallet validation, widget test of
  the flow steps (package → wallet → number → confirm → OTP → result).
- Gates before PR: `pytest services`, `ruff check services`,
  `black --check services`, `flutter analyze`, `dart format --set-exit-if-changed`,
  `flutter test`.
