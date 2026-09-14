# Engineer B — "The Revenue Engine" — Work Status

Branch: `feature/storefront` (analyzer branch already merged in)
Plan reference: `implementation_plan.md` → Engineer B scope
Last updated: 2026-09-14 (work interrupted by power loss — resume from "In progress")

> ⚠️ **Resume note:** The credit-system deduction hook was **interrupted mid-way**.
> `services/api/tracked_items_api.py` imports `deduct` (line 13) but does **not** call it
> yet in `create_tracked_item`. Finish that hook, then add credit tests. Everything else
> below that is marked DONE is complete and (where noted) verified.

---

## Completed

### 1. Public API endpoints — DONE, verified ✅

`services/api/routers/public_api.py` — one consolidated router (DRY: all four share the
`price_history` source + one query helper). Wired into `services/api/main.py` (no-auth,
fail-soft if `price_history` is missing).

| Endpoint | Returns |
|---|---|
| `GET /stats` | Both consumer key sets — Flutter (`total_trackers`/`deals_today`/`total_savings`) **and** landing page (`deals_found_today`/`total_savings_egp`/`stores_monitored`) |
| `GET /deals/live` | Products whose current price < 90-day-high, ranked by discount depth |
| `GET /price-history/{sku}` | One clean series (lowest price across stores per day) for the chart |
| `GET /pricing` | Free / Standard / Premium tiers (matches the landing page) |

- **Tests:** `services/api/test_public_api.py` — **6/6 passing** (series shape, unknown-SKU→`[]`,
  deals ranking, stats counts, pricing tiers, fail-soft on missing table).
- **Verified live:** `GET /pricing` returns 200 on the main app with correct tiers.

### 2. Credit system — models + service + balance API — DONE ✅

- **Models** (`services/api/models.py`): `UserCredit` (`user_credits`, one row per user,
  keyed by canonical `User` UUID, lazy-provisioned) and `CreditTransaction`
  (`credit_transactions`, immutable ledger). Both share the canonical `Base` and
  `User` relationship; tables auto-created via `Base.metadata.create_all` in `main.py`.
- **Service** (`services/api/credits.py`): `get_balance` (read-only, lazy-provisioned),
  `deduct` (raises 402 on insufficient balance, atomic in caller's session), `grant`
  (for Paymob top-ups). `TIER_STARTING_CREDITS = {free: 3, standard: 10, premium: 1000}`.
- **Balance API** (`services/api/routers/credits.py`): `GET /credits/balance`,
  `GET /credits/transactions` (auth required). Wired into `main.py`.

---

## In progress (interrupted here)

### 3. Credit deduction on tracker creation — ⚠️ PARTIAL

- `services/api/tracked_items_api.py` line 13: `from services.api.credits import deduct`
  is **imported but NOT yet called**.
- **TODO (next step):** call `deduct(db, current_user, amount=1, reason="tracker_created")`
  inside `create_tracked_item` (before `db.commit()`), so a 402 rolls back the pending
  `TrackedItem`. Design already decided:
  - **Lazy provisioning** — a user with no credit row gets their tier's starting balance,
    so the existing free-tier `test_create_tracked_item` still returns 201.
  - **Atomic** — deduction runs in the same session/transaction as tracker creation.
- **TODO:** add `services/api/test_credits.py` (balance, deduct success, 402 on insufficient,
  grant, ledger ordering, lazy provisioning).

---

## Not started

- **Paymob webhook HMAC validation** — `services/billing/main.py` `verify_paymob_webhook()`
  still returns `True` always; mock fallback data on parse failure. Replace with real HMAC.
- **Affiliate link injection** — `services/api/middleware/affiliate.py` + `affiliate_clicks`
  table (store-specific programs: Amazon Associates EG, Noon Affiliate, Jumia KOL).
- **Rate limiting** — slowapi middleware on public endpoints.
- **Tiered pricing in billing** — `services/billing/main.py` `get_dynamic_pricing()` still
  returns hardcoded mock tiers; align with the `/pricing` tiers.

---

## Cross-cutting hardening (still needed)

- **`print()` → `logging`** — `services/api/main.py` (several) and `services/billing/main.py`.
- **Wire `tracked_items` router** — `services/api/main.py` only includes `auth`,
  `public_api`, and `credits`; the full `tracked_items_api.router` is still commented out
  (L414-415). Needed before the credit deduction is reachable in the running app.
- **Externalize hardcoded `DATABASE_URL`** — `docker-compose.yml` L114
  (`postgresql://elhaq:elhaq_pass@...`) and `services/billing/main.py` default.

---

## Known pre-existing issue (flagged, not yet fixed)

- **UUID vs Integer user-id fork:** `services/api/models.py` `User.id` is a **UUID**, but
  `services/api/tracked_items_models.py` re-declares its own `users` table with an
  **Integer** id and `TrackedItem.user_id` as an Integer FK (a separate `declarative_base()`
  SQLite shim). The credit system is keyed by the canonical UUID `User`. The
  `TrackedItem.user_id` Integer FK is a separate pre-existing bug to reconcile when the
  tracked-items router is wired in.

---

## Environment note

- `projects` conda env (`C:\Users\Compumarts\miniconda3\envs\projects\python.exe`) has
  `fastapi` + `sqlalchemy` but **not** `python-jose` / `passlib`. API tests that import
  `services.api.dependencies` need those installed (pre-existing gap — `test_main.py` and
  `test_tracked_items_api.py` have the same requirement). Public-API tests were verified via
  a throwaway stub harness (no installs, no source changes).
