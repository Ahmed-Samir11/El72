# Paymob Integration — Feature Plan

## Context

Elhaq is a credit-based price-tracking app. Users buy credits (one-time packages) to create
trackers. This plan defines how to integrate Paymob (Egyptian payment gateway) for real payments,
broken into independently shippable features with explicit security requirements.

**Current state:**
- Credit system: ✅ working (free=3, 1/tracker, 402 when depleted)
- Billing service: ⚠️ stub (static URL, custom webhook payload)
- Flutter `SubscriptionScreen`: ⚠️ mock (`https://paymob.com/pay/$plan`)
- Paymob HMAC helper: ✅ exists (`services/common/paymob.py`)
- `PaymentLog` model: ✅ exists

**Pricing (one-time packages, not subscriptions):**

| Package | Credits | Price (EGP) |
|---------|---------|-------------|
| Free | 3 | 0 |
| Standard | 10 | 30 |
| Premium | 30 | 90 |

---

## Feature 0: Manual Payment Flow

### Definition
A complete in-app payment submission flow where the user selects a package, sees payment
details (bank IBAN / wallet number), taps "I've Paid", and an admin manually verifies and
approves the payment. No payment gateway involved.

### Scope
**Includes:**
- In-app package selection + payment details display
- "I've Paid" submission → creates a pending order
- Admin approval/rejection (CLI or simple web endpoint)
- WhatsApp notification on approval
- Credit granting on approval

**Excludes:**
- Any Paymob API calls
- Automatic verification
- Refunds (admin handles manually)

### API Contract

`order_ref` (e.g. `ELH-20250101-a3f2b1`) is the public order identifier in all
endpoints; the internal UUID `id` is opaque to clients and admins. Admin
endpoints require a separate admin credential (`POST /admin/login`), never a
user tier. Every admin action writes an append-only entry to
`payment_audit_log`.

```
POST /payment/manual
  Auth: Bearer token (logged-in user)
  Body: { "package": "standard" | "premium" }   # pricing is server-determined
  Response: { "id", "order_ref", "package", "amount_egp", "status": "pending" }

GET /payment/manual/{order_ref}
  Auth: Bearer token (owner only; 404 for other users' orders)
  Response: { "id", "order_ref", "package", "amount_egp", "status", "reject_reason" }

POST /admin/login
  Body: { "username", "password" }   # separate admin credential, rate-limited (5/min)
  Response: { "access_token", "token_type" }
  Token: signed with ADMIN_SECRET_KEY (separate from user tokens), 1h expiry

GET /admin/payments?status=pending&date_from=...&date_to=...
  Auth: Admin token (422 on invalid dates)
  Response: [ { "id", "order_ref", "user_phone_masked", "package", "amount_egp", "created_at" } ]

GET /admin/payments/{order_ref}/contact
  Auth: Admin token — audited full-contact reveal
  Response: { "order_ref", "user_phone" }

POST /admin/payments/{order_ref}/approve
  Auth: Admin token — idempotent, concurrency-safe (atomic CAS)
  Effect: pending->approved + credit grant + audit entry in one transaction
  Response: { "id", "order_ref", "status": "approved", "credits_granted", "new_balance" }

POST /admin/payments/{order_ref}/reject
  Auth: Admin token — with reason, audited
  Body: { "reason": "..." }
  Response: { "id", "order_ref", "status": "rejected", "reject_reason" }
```

### Security Requirements

| # | Threat | Mitigation |
|---|--------|-----------|
| 0.1 | User submits multiple "I've Paid" for same package | Rate limit: max 3 pending orders per user per day. Additional submissions return 429. |
| 0.2 | Admin endpoint abuse | Admin auth requires a separate admin credential (not a user tier/JWT): `admins` table + `POST /admin/login`. Admin actions are written to the append-only `payment_audit_log`. |
| 0.3 | Order ID enumeration | `order_ref` includes a random hex suffix (`secrets.token_hex`). Users can only query their own orders (404 otherwise). |
| 0.4 | Credit double-grant | Approval is idempotent AND concurrency-safe: pending->approved is an atomic compare-and-swap; only the winning request grants credits, in the same transaction as the audit entry. |
| 0.5 | PII exposure in admin lists | Phone numbers are masked by default; full contact requires an explicit, audited `reveal_contact` action. |
| 0.5 | Payment details leakage | IBAN/wallet shown only to authenticated users. Not in public API. Logged access. |
| 0.6 | No audit trail | Every approve/reject logged with admin ID, timestamp, IP. Immutable log table. |

### Database

Implemented in `infra/sql/schema.sql` (canonical DDL). Summary:

- **admins** — separate admin credentials (`id VARCHAR(36)`, `username UNIQUE`,
  `password_hash`, `created_at`). Provisioned out-of-band; the first admin is
  bootstrapped from `ADMIN_USERNAME`/`ADMIN_PASSWORD` at startup (idempotent,
  concurrency-safe). Admins are never user tiers.
- **manual_payments** — `id UUID PK`, `order_ref VARCHAR(32) UNIQUE`
  (public identifier, format `ELH-{YYYYMMDD}-{random_hex_8}`), `user_id`,
  `package` + `amount_egp` + `status` CHECK constraints, `reject_reason`,
  `created_at` (indexed for admin date-range filters), `resolved_at`,
  `resolved_by VARCHAR(36) REFERENCES admins(id) ON DELETE SET NULL`.
- **payment_audit_log** — append-only trail of admin actions
  (`action IN ('approve','reject','reveal_contact')`, `actor_id REFERENCES
  admins(id)`, `target_user_id`, `order_ref`, `client_ip`). No UPDATE/DELETE
  path exists.

Note: the canonical DDL uses `UUID` for user ids (matching `users.id`), while
the SQLAlchemy models map user ids as `VARCHAR(36)` dashed-UUID strings — a
pre-existing convention in this codebase; Postgres accepts dashed UUID
literals for the `uuid` type.

### Acceptance Criteria
- [ ] User can select package, see payment details, submit "I've Paid"
- [ ] Order appears in admin pending list
- [ ] Admin approves → credits added → WhatsApp notification sent
- [ ] Admin rejects → user notified with reason
- [ ] Double-approval is a no-op
- [ ] Rate limiting prevents spam submissions
- [ ] All admin actions are audited

### Dependencies
- None (works standalone, no Paymob)

---

## Feature 1: Paymob Card Payments

### Definition
Card payment flow using Paymob's ToC (Tokenization Component) SDK for on-device card
tokenization. The user enters card details in the app; the card is tokenized by Paymob
on-device (PCI-compliant); our backend creates the payment; Paymob handles 3D Secure.

### Scope
**Includes:**
- `GET /payment/start` → creates Paymob customer, returns `staging_token`
- ToC SDK platform channel (Android + iOS) for card tokenization
- `POST /payment/confirm` (card) → creates payment method + payment
- 3D Secure completion via ToS SDK
- Payment status polling
- Webhook confirmation → credit granting

**Excludes:**
- Wallet payments (Feature 2)
- Cash payments (Feature 3)
- Recurring/subscription cards (Feature 7)
- Stored cards for repeat purchase (v2)

### API Contract

```
GET /payment/start
  Auth: Bearer token
  Response: { "staging_token": "...", "expires_in": 900 }

POST /payment/confirm
  Auth: Bearer token
  Body: {
    "staging_token": "...",
    "method_type": "card",
    "token": "...",              -- from ToC SDK
    "package": "standard" | "premium"
  }
  Response: {
    "payment_id": "...",
    "authentication_token": "...",  -- for ToS SDK (3DS)
    "status": "pending"
  }

GET /payment/status/{payment_id}
  Auth: Bearer token (owner only)
  Response: { "status": "pending" | "succeeded" | "failed" | "canceled" }
```

### Security Requirements

| # | Threat | Mitigation |
|---|--------|-----------|
| 1.1 | **PCI-DSS: raw card data on our servers** | Card tokenized **on-device** via ToC SDK. Our servers only ever see the Paymob `token`, never the card number/CVV. **Non-negotiable.** |
| 1.2 | **Staging token hijacking** | Staging token stored in Redis with 15-min TTL. Bound to user_id. If user A's token is used by user B, the payment is rejected. Token is single-use: after `confirm`, it's deleted. |
| 1.3 | **Payment amount tampering** | Amount is **server-determined** from `package` (not user-supplied). Client sends `package`, server looks up price. Client never sends an amount. |
| 1.4 | **Replay attacks** | `staging_token` is single-use. After `confirm`, Redis key is deleted. Replaying the same token returns 400. |
| 1.5 | **3DS bypass** | `authentication_token` is only valid for 15 min and single-use. ToS SDK completion is required for card payments. We don't mark payment as succeeded until Paymob webhook confirms. |
| 1.6 | **API key leakage** | `PAYMOB_API_KEY` in environment variable / secret manager. Never in code, never in logs. If leaked, rotate immediately in Paymob dashboard. |
| 1.7 | **Man-in-the-middle** | All app↔backend and backend↔Paymob traffic is HTTPS/TLS 1.2+. No HTTP fallback. Certificate pinning in app (optional, v2). |
| 1.8 | **User sees other users' payments** | `/payment/status/{id}` verifies the payment belongs to the authenticated user. No cross-user access. |
| 1.9 | **Excessive Paymob API calls** | Rate limit `/payment/start` to 5/hour per user. Rate limit `/payment/confirm` to 3/hour per user. |
| 1.10 | **Log leakage of sensitive data** | Logs must NOT contain: card numbers, CVV, tokens, staging tokens, full IBANs. Only payment IDs and order references. |

### ToC SDK Integration

**Android** (Kotlin, via platform channel):
```kotlin
// PaymobTokenizePlugin.kt
class PaymobTokenizePlugin : FlutterPlugin, MethodCallHandler {
    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        if (call.method == "tokenize") {
            val stagingToken = call.argument<String>("stagingToken")
            val cardNumber = call.argument<String>("cardNumber")
            val expiryMonth = call.argument<String>("expiryMonth")
            val expiryYear = call.argument<String>("expiryYear")
            val cvv = call.argument<String>("cvv")
            // Paymob ToC SDK tokenizes on-device
            // Returns token or error
        }
    }
}
```

**iOS** (Swift, via platform channel):
```swift
// PaymobTokenizePlugin.swift
class PaymobTokenizePlugin: NSObject, FlutterPlugin {
    func tokenize(stagingToken: String, card: CardDetails) -> (String?, Error?) {
        // Paymob ToC iOS SDK
    }
}
```

**Flutter:**
```dart
class PaymobTokenize {
  static const _channel = MethodChannel('paymob/tokenize');

  static Future<String> tokenize({
    required String stagingToken,
    required String cardNumber,
    required String expiryMonth,
    required String expiryYear,
    required String cvv,
  }) => _channel.invokeMethod('tokenize', { ... });
}
```

### Security Note: Card Data Handling
- Card number, expiry, CVV exist **only on the device** during tokenization
- ToC SDK encrypts and sends directly to Paymob — our app code never logs it
- After tokenization, only the `token` (a reference) exists
- **Our database never stores card data.** Only `payment_id` and `order_id`.

### Acceptance Criteria
- [ ] User enters card → ToC SDK tokenizes → backend creates payment
- [ ] 3D Secure completes via ToS SDK
- [ ] Paymob webhook fires → credits granted
- [ ] Card data never appears in our logs or database
- [ ] Staging token expires after 15 min
- [ ] Staging token is single-use
- [ ] Amount is server-determined (client can't set it)
- [ ] Rate limiting active
- [ ] Failed payment → user sees error, no credits granted

### Dependencies
- Feature 4 (Webhook & Credit Granting)
- Paymob sandbox/production API keys

---

## Feature 2: Paymob Wallet Payments

### Definition
Wallet payment flow for Egyptian mobile wallets (Vodafone Cash, Orange Money, Etisalat
Cash, Fawry). User selects wallet type, enters wallet phone number, receives OTP, confirms.

### Scope
**Includes:**
- Wallet type selection UI (4 wallets)
- Wallet phone number input + validation (Egyptian format: 01X XXXXXXXX)
- `POST /payment/confirm` (wallet) → creates payment
- OTP entry screen
- `POST /payment/confirm-otp` → confirms with OTP
- Payment status polling
- Webhook confirmation → credit granting

**Excludes:**
- Card payments (Feature 1)
- Cash payments (Feature 3)
- International wallets

### API Contract

```
POST /payment/confirm
  Auth: Bearer token
  Body: {
    "staging_token": "...",
    "method_type": "wallet",
    "wallet_type": "VODAFONE_CASH" | "ORANGE_money" | "ETISALAT_CASH" | "FAWRY",
    "wallet_number": "01012345678",
    "package": "standard" | "premium"
  }
  Response: {
    "payment_id": "...",
    "status": "pending_otp"
  }

POST /payment/confirm-otp
  Auth: Bearer token
  Body: {
    "payment_id": "...",
    "otp": "123456"
  }
  Response: { "status": "processing" | "succeeded" | "failed" }

GET /payment/status/{payment_id}
  (same as Feature 1)
```

### Security Requirements

| # | Threat | Mitigation |
|---|--------|-----------|
| 2.1 | **OTP brute force** | Max 3 OTP attempts per payment. After 3 failures, payment is canceled. OTP expires in 60 seconds. |
| 2.2 | **Wallet number enumeration** | Rate limit wallet confirm to 5/hour per user. Invalid numbers rejected fast (format validation before hitting Paymob). |
| 2.3 | **Payment to wrong wallet** | Wallet number is displayed back to user for confirmation before submission. "You're paying 01012345678 — confirm?" |
| 2.4 | **Amount tampering** | Same as Feature 1: server-determined from package. |
| 2.5 | **Staging token reuse** | Same as Feature 1: single-use, 15-min TTL. |
| 2.6 | **OTP in logs** | OTP values are NEVER logged. Only "OTP verified" / "OTP failed" without the value. |
| 2.7 | **Wallet type spoofing** | `wallet_type` is validated against a server-side allowlist. Unknown types rejected. |
| 2.8 | **No audit trail** | Every wallet payment logged: user_id, wallet_type (not number), amount, status, timestamp. |

### Egyptian Phone Validation
```python
import re
WALLET_PHONE_RE = re.compile(r'^01[0125]\d{8}$')  # 010, 011, 012, 015 + 8 digits

def validate_wallet_number(number: str) -> bool:
    return bool(WALLET_PHONE_RE.match(number))
```

### Acceptance Criteria
- [ ] User selects wallet, enters number, sees confirmation
- [ ] OTP received on user's phone, entered in app
- [ ] Payment succeeds → credits granted
- [ ] 3 failed OTPs → payment canceled
- [ ] OTP expires after 60s
- [ ] Wallet number format validated before API call
- [ ] No OTP values in logs
- [ ] Rate limiting active

### Dependencies
- Feature 4 (Webhook & Credit Granting)
- Feature 1 (shared `/payment/start` endpoint)

---

## Feature 3: Paymob Cash Payments

### Definition
Cash payment flow where the user receives a payment code to pay at a Fawry cash point
or bank branch. The payment is confirmed when Paymob detects the cash deposit.

### Scope
**Includes:**
- Cash type selection (Fawry / Bank)
- Payment code generation + display
- Code expiry timer
- Payment status polling (user checks if cash was received)
- Webhook confirmation → credit granting

**Excludes:**
- Real-time cash detection (depends on Paymob)
- Multiple cash payments per order

### API Contract

```
POST /payment/confirm
  Auth: Bearer token
  Body: {
    "staging_token": "...",
    "method_type": "cash",
    "cash_type": "fawry" | "bank",
    "package": "standard" | "premium"
  }
  Response: {
    "payment_id": "...",
    "payment_code": "FAWRY-123456",
    "expires_at": "2025-01-02T12:00:00Z",
    "status": "pending"
  }

GET /payment/status/{payment_id}
  (same as Feature 1)
```

### Security Requirements

| # | Threat | Mitigation |
|---|--------|-----------|
| 3.1 | **Payment code sharing** | Code is single-use, bound to user + order. If shared, only the original user can receive credits. Code expires in 24h. |
| 3.2 | **Code enumeration** | Codes are random (not sequential). 6+ characters. Rate limit status polling to 1/minute. |
| 3.3 | **Cash never arrives** | Order auto-expires after 24h. User notified: "Your payment code expired." No credits granted. |
| 3.4 | **Amount tampering** | Server-determined from package. |
| 3.5 | **No audit trail** | Cash payments logged with code (not user-sensitive data), status, expiry. |

### Acceptance Criteria
- [ ] User gets a payment code with expiry
- [ ] Code displayed clearly (can write it down)
- [ ] Status pollable
- [ ] Code expires after 24h → order canceled
- [ ] Cash received → webhook → credits granted
- [ ] No sensitive data in code

### Dependencies
- Feature 4 (Webhook & Credit Granting)
- Feature 1 (shared `/payment/start` endpoint)

---

## Feature 4: Webhook & Credit Granting

### Definition
Server-side handler that receives Paymob webhook notifications, verifies their authenticity,
validates the payment details, and grants credits to the user's account. This is the
**single source of truth** for "payment succeeded."

### Scope
**Includes:**
- `POST /webhook/paymob` endpoint (billing service)
- HMAC-SHA512 signature verification
- Real Paymob payload parsing (`obj.status`, `obj.reference_id`, `obj.amount`)
- Idempotency (duplicate webhooks ignored)
- Amount validation (matches package price)
- Credit granting (atomic: payment_log + user_credits + credit_transactions)
- Failed/canceled payment handling
- Fallback: `GET /payment/status` polling if webhook is delayed

**Excludes:**
- Refund processing (Feature 6)
- Subscription renewal webhooks (Feature 7)

### API Contract

```
POST /webhook/paymob  (billing service, called by Paymob)
  No auth (uses HMAC signature instead)
  Body: Paymob webhook payload
  Response: 200 { "status": "processed" } | 401 { "detail": "Invalid signature" }
```

### Paymob Webhook Payload Format
```json
{
  "obj": {
    "id": "txn_abc123",
    "status": "succeeded",
    "amount": 3000,
    "currency": "EGP",
    "reference_id": "elhaq-{user_id}-{package}",
    "created_at": "2025-01-01T12:00:00Z"
  }
}
```

### Security Requirements

| # | Threat | Mitigation |
|---|--------|-----------|
| 4.1 | **Webhook forgery** | HMAC-SHA512 signature verification on raw body. Secret is `PAYMOB_HMAC_SECRET` (env var). If signature doesn't match → 401. **This is the primary security gate.** |
| 4.2 | **Replay attacks** | `paymob_order_id` (transaction ID) is unique-constrained in `payment_logs`. Second delivery of same ID → 200 "duplicate", no side effect. |
| 4.3 | **Amount fraud** | Server validates `amount == PACKAGE_PRICES[package] * 100`. Mismatch → 400, no credits. |
| 4.4 | **Reference ID tampering** | `reference_id` format validated: must match `elhaq-{valid_uuid}-{valid_package}`. Malformed → 400. |
| 4.5 | **Credit double-grant** | Entire credit grant is in a single DB transaction. If any part fails, all rolls back. Combined with 4.2 (idempotency), double-grant is impossible. |
| 4.6 | **User ID injection** | `user_id` from `reference_id` is validated as a real UUID that exists in `users` table. Non-existent user → 400. |
| 4.7 | **Webhook secret leakage** | `PAYMOB_HMAC_SECRET` in env/secret manager. Not in code. Rotatable in Paymob dashboard. If leaked, all past webhooks are suspect → audit log. |
| 4.8 | **No audit trail** | Every webhook processed (success or failure) logged: timestamp, transaction ID, user ID, amount, result. Immutable. |
| 4.9 | **Denial of service** | Webhook endpoint rate-limited (100/hour). Excess → 429. Paymob retries, so legitimate webhooks still get through. |
| 4.10 | **Partial failure** | If credit grant succeeds but notification fails, payment is still recorded. Notification is best-effort (retry queue). |

### Implementation

```python
@app.post("/webhook/paymob")
async def paymob_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()

    # 4.1: Verify signature
    if not verify_paymob_webhook(request, body):
        raise HTTPException(401, "Invalid signature")

    data = json.loads(body.decode("utf-8"))
    tx = data.get("obj", data)

    # Only process succeeded
    if tx.get("status") != "succeeded":
        return {"status": "ignored"}

    # 4.4: Validate reference_id
    reference_id = tx.get("reference_id", "")
    parts = reference_id.split("-")
    if len(parts) != 3 or parts[0] != "elhaq":
        raise HTTPException(400, "Invalid reference_id")
    user_id_str, package = parts[1], parts[2]

    # 4.6: Validate user exists
    user = db.execute(
        text("SELECT 1 FROM users WHERE id = :id"), {"id": user_id_str}
    ).first()
    if not user:
        raise HTTPException(400, "Unknown user")

    # 4.3: Validate amount
    amount_egp = tx.get("amount", 0) / 100
    if package not in PACKAGE_PRICES or amount_egp != PACKAGE_PRICES[package]:
        raise HTTPException(400, "Amount mismatch")

    # 4.2: Idempotency
    existing = db.execute(
        text("SELECT 1 FROM payment_logs WHERE paymob_order_id = :id"),
        {"id": tx["id"]},
    ).first()
    if existing:
        return {"status": "duplicate"}

    # 4.5: Atomic credit grant
    with db.begin():
        db.execute(text("INSERT INTO user_credits ... ON CONFLICT DO UPDATE ..."), ...)
        db.execute(text("INSERT INTO credit_transactions ..."), ...)
        db.add(PaymentLog(...))
        db.flush()

    return {"status": "processed"}
```

### Acceptance Criteria
- [ ] Valid webhook → credits granted, payment logged
- [ ] Invalid signature → 401, no side effects
- [ ] Duplicate webhook → 200 "duplicate", no double-grant
- [ ] Amount mismatch → 400, no credits
- [ ] Invalid user → 400
- [ ] Failed/canceled status → ignored, no credits
- [ ] All processing logged (immutable audit)
- [ ] Rate limiting active

### Dependencies
- `PAYMOB_HMAC_SECRET` configured
- `payment_logs` table with unique constraint on `paymob_order_id`

---

## Feature 5: Payment Security & Audit

### Definition
Cross-cutting security infrastructure that applies to ALL payment features. Includes
audit logging, secret management, rate limiting, input validation, and security monitoring.

### Scope
**Includes:**
- Immutable audit log table (all payment events)
- Secret management (API keys, HMAC secrets)
- Global rate limiting on payment endpoints
- Input validation framework (phone numbers, packages, amounts)
- Security monitoring alerts (failed webhook signatures, excessive failures)
- Log sanitization (no card data, no OTPs, no tokens in logs)

**Excludes:**
- Penetration testing (external)
- PCI-DSS certification (handled by Paymob for tokenization)

### Security Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ Rate Limiting (per-user, per-endpoint)                       │
├──────────────────────────────────────────────────────────────┤
│ Input Validation (packages, phone numbers, amounts)          │
├──────────────────────────────────────────────────────────────┤
│ Authentication (user JWT / admin token / HMAC)                │
├──────────────────────────────────────────────────────────────┤
│ Authorization (user can only access own payments)             │
├──────────────────────────────────────────────────────────────┤
│ Business Logic (server-determined amounts, single-use tokens)│
├──────────────────────────────────────────────────────────────┤
│ Audit Logging (immutable, all events)                        │
├──────────────────────────────────────────────────────────────┤
│ Secret Management (env vars, rotation)                       │
└──────────────────────────────────────────────────────────────┘
```

### Audit Log Table

```sql
CREATE TABLE payment_audit_log (
    id UUID PRIMARY KEY DEFAULT (gen_random_uuid()),
    event_type TEXT NOT NULL,        -- "webhook_received", "approved", "rejected",
                                      -- "otp_failed", "token_expired", "amount_mismatch"
    user_id UUID,
    payment_id TEXT,
    detail TEXT,                     -- sanitized (no sensitive data)
    ip_address INET,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- This table is APPEND-ONLY. No UPDATE, no DELETE.
```

### Rate Limits

| Endpoint | Limit | Window |
|----------|-------|--------|
| `/payment/start` | 5 | per user / hour |
| `/payment/confirm` | 3 | per user / hour |
| `/payment/confirm-otp` | 5 | per payment / 10 min |
| `/payment/status` | 30 | per user / minute |
| `/payment/manual` | 3 | per user / day |
| `/webhook/paymob` | 100 | global / hour |
| `/admin/payments/*` | 20 | per admin / minute |

### Secret Management

| Secret | Storage | Rotation |
|--------|---------|----------|
| `PAYMOB_API_KEY` | Env var / Docker secret | On suspicion of leakage |
| `PAYMOB_HMAC_SECRET` | Env var / Docker secret | Quarterly or on suspicion |
| Admin token | Env var | Monthly |
| DB password | Env var | Quarterly |

**Rules:**
- Never in source code
- Never in logs
- Never in error messages
- If leaked: rotate immediately + audit log for impact assessment

### Log Sanitization Rules

| Data | In Logs? |
|------|----------|
| Card number | ❌ NEVER |
| CVV | ❌ NEVER |
| Paymob token | ❌ NEVER |
| Staging token | ❌ NEVER |
| OTP | ❌ NEVER |
| Wallet phone number | ⚠️ Masked: `0101***5678` |
| IBAN | ⚠️ Masked: `EG12****5678` |
| Payment ID | ✅ Yes |
| Order ID | ✅ Yes |
| User ID | ✅ Yes |
| Amount | ✅ Yes |
| Status | ✅ Yes |

### Acceptance Criteria
- [ ] All payment events in immutable audit log
- [ ] Rate limits enforced on all endpoints
- [ ] No sensitive data in any log output
- [ ] Secrets only in env vars
- [ ] Alert on: 5+ failed webhook signatures in 1 min, 10+ OTP failures in 1 hour
- [ ] Admin actions always attributed to specific admin

### Dependencies
- All other features depend on this

---

## Feature 6: Admin & Dispute Management

### Definition
Admin tools for managing payments: viewing all payments, handling disputes, processing
refunds, and investigating security events.

### Scope
**Includes:**
- Admin dashboard (web page or CLI): list all payments, filter by status/date
- Refund processing (manual, via Paymob API or manual bank transfer)
- Dispute handling (user claims payment but no credits)
- Security event investigation (audit log viewer)
- User credit adjustment (manual override with audit)

**Excludes:**
- Automatic dispute resolution
- Chargeback handling (Paymob manages card chargebacks)

### API Contract

```
GET /admin/payments
  Auth: Admin token
  Query: ?status=...&date_from=...&date_to=...&user=...
  Response: [ { "order_id", "user_phone", "package", "amount_egp", "status", "method", "created_at" } ]

POST /admin/payments/{order_id}/refund
  Auth: Admin token
  Body: { "reason": "..." }
  Response: { "status": "refunded" }

POST /admin/users/{user_id}/adjust-credits
  Auth: Admin token
  Body: { "amount": 5, "reason": "..." }
  Response: { "new_balance": 15 }

GET /admin/audit-log
  Auth: Admin token
  Query: ?event_type=...&user_id=...&date_from=...
  Response: [ { "event_type", "user_id", "detail", "ip_address", "created_at" } ]
```

### Security Requirements

| # | Threat | Mitigation |
|---|--------|-----------|
| 6.1 | **Admin privilege escalation** | Admin token is separate from user JWT. Cannot be obtained via user auth. Admin endpoints not discoverable (no OpenAPI exposure). |
| 6.2 | **Insider threat** | All admin actions logged with admin ID + IP. Credit adjustments require reason. Large adjustments (>50 credits) require second admin approval. |
| 6.3 | **Data exposure** | Admin dashboard shows masked phone numbers by default. Full data requires explicit "reveal" action (logged). |
| 6.4 | **Refund abuse** | Refund requires reason. Refunded amount deducted from user credits. Refund is irreversible (logged). |
| 6.5 | **Audit log tampering** | Audit log is append-only. No UPDATE/DELETE permissions. DB user for app has INSERT only on this table. |

### Acceptance Criteria
- [ ] Admin can view all payments with filters
- [ ] Admin can process refund (credits deducted, logged)
- [ ] Admin can adjust credits (reason required, logged)
- [ ] Large adjustments require second approval
- [ ] Audit log viewable by admin
- [ ] All admin actions attributed + logged

### Dependencies
- Feature 5 (Audit Log)
- All payment features (data to display)

---

## Feature 7: Recurring Subscriptions (v2)

### Definition
Monthly automatic payments where the user's card is charged every month for a subscription
package. Uses Paymob's Subscriptions API. User can cancel anytime.

### Scope
**Includes:**
- Subscription creation (first payment + recurring mandate)
- Monthly renewal via Paymob
- Renewal webhook handling
- Cancellation flow
- Failed renewal → dunning (notify user, retry)
- Plan change (upgrade/downgrade)

**Excludes:**
- Weekly/yearly billing (v3)
- Proration (v3)
- Family/group plans

### API Contract

```
POST /subscription/create
  Auth: Bearer token
  Body: {
    "staging_token": "...",
    "token": "...",              -- card token
    "package": "standard" | "premium",
    "interval": "month"
  }
  Response: { "subscription_id": "...", "next_charge": "2025-02-01" }

POST /subscription/cancel
  Auth: Bearer token
  Body: { "subscription_id": "..." }
  Response: { "status": "canceled", "effective": "2025-02-01" }

GET /subscription/status
  Auth: Bearer token
  Response: { "active": true, "package": "standard", "next_charge": "..." }
```

### Security Requirements

| # | Threat | Mitigation |
|---|--------|-----------|
| 7.1 | **Unauthorized charges** | Subscription bound to user_id + card token. Can only be canceled by the owner. Renewal amount is fixed (server-determined). |
| 7.2 | **Zombie subscriptions** | After 3 failed renewals, subscription is auto-canceled. User notified. |
| 7.3 | **Card expiry** | Paymob handles card update prompts. If card fails, dunning flow starts. |
| 7.4 | **Cancellation bypass** | Cancellation is immediate (no retention flow in v2). Effective end of billing period. |
| 7.5 | **Webhook forgery** | Same HMAC verification as Feature 4. |
| 7.6 | **Double charge** | Paymob subscription ID is unique. Renewal webhook is idempotent (same as Feature 4). |

### Acceptance Criteria
- [ ] User can subscribe with card
- [ ] Monthly charge happens automatically
- [ ] User can cancel
- [ ] Failed charge → notification → retry → auto-cancel after 3 failures
- [ ] No double charges
- [ ] All events audited

### Dependencies
- Feature 1 (Card Payments — tokenization)
- Feature 4 (Webhook & Credit Granting)
- Paymob Subscriptions API access

---

## Implementation Order

```
Feature 5 (Security & Audit)     ← Foundation, build first
    ↓
Feature 0 (Manual Payments)      ← Works immediately, no Paymob needed
    ↓
Feature 4 (Webhook & Credits)    ← Core backend, needed by all Paymob features
    ↓
Feature 1 (Card Payments)        ← Primary payment method
    ↓
Feature 2 (Wallet Payments)      ← Secondary (very popular in Egypt)
    ↓
Feature 3 (Cash Payments)        ← Tertiary
    ↓
Feature 6 (Admin & Disputes)     ← Operations tooling
    ↓
Feature 7 (Subscriptions)        ← v2, after stable one-time payments
```

---

## Environment Configuration

```env
# Paymob
PAYMOB_API_KEY=                    # sandbox or production
PAYMOB_API_BASE=https://sium4m6aqfgh-prod.a.run.app
PAYMOB_HMAC_SECRET=                # webhook signing secret
PAYMOB_REDIRECT_URL=https://elhaq.com/payment/return

# Admin
ADMIN_TOKEN=                       # separate from user JWT

# Rate Limits
RATE_LIMIT_PAYMENT_START=5/hour
RATE_LIMIT_PAYMENT_CONFIRM=3/hour
RATE_LIMIT_WEBHOOK=100/hour
```

---

## Testing Strategy

| Feature | Test Type | Details |
|---------|-----------|---------|
| 0 | Integration | Manual payment → approve → credits granted |
| 1 | Unit + Integration | Mock Paymob API. Card flow end-to-end. |
| 2 | Unit + Integration | Mock Paymob API. Wallet + OTP flow. |
| 3 | Unit + Integration | Mock Paymob API. Cash code flow. |
| 4 | Unit + Integration | Valid/invalid HMAC. Duplicate. Amount mismatch. |
| 5 | Unit | Rate limits. Log sanitization. Audit log immutability. |
| 6 | Integration | Admin endpoints. Refund. Credit adjustment. |
| 7 | Integration | Mock subscription. Renewal. Cancellation. Dunning. |

**Sandbox test cards (Paymob):**
- Success: `4242 4242 4242 4242`, any future expiry, any CVV
- Failure: `4000 0000 0000 0002`
- 3DS challenge: `4000 0000 0000 0027`

---

## Open Questions

1. **ToC SDK availability**: Confirm exact Paymob ToC SDK versions for Android/iOS.
   If no official Flutter support, platform channels are the path.
2. **Wallet OTP flow**: Does Paymob send OTP to the wallet app or via SMS?
   (Affects UX: in-app OTP entry vs "check your phone")
3. **Cash code expiry**: How long is a Fawry code valid? (24h? 48h?)
4. **Refund policy**: What's our refund window? (14 days? 30 days?)
5. **Tax invoices**: Do we need to issue fiscal invoices? (Affects admin feature)
6. **Multi-currency**: EGP only for v1? (Yes, for now)
