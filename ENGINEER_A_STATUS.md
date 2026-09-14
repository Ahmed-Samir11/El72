# Engineer A — "The Storefront" — Work Status

Branch: `feature/storefront` (created from `origin/main`)
Plan reference: `implementation_plan.md` → Engineer A scope
Last updated: 2026-09-13 (work paused on request)

## Completed

### 1. Landing Page (`frontend/`) — DONE, verified

Vite + vanilla JS/CSS single-page marketing site (per project web standards).

Files created:
- `frontend/package.json` — Vite 5 project, `dev`/`build`/`preview` scripts
- `frontend/vite.config.js` — serves on port 3000 (matches demo checklist)
- `frontend/index.html` — full marketing page:
  - Hero with animated price-drop visualization
  - How It Works (3-step flow)
  - Live stats ticker (pulls from API `/stats` with graceful fallback to
    realistic demo numbers when the API is unreachable — Engineer B's
    endpoint is not merged yet, so fallback keeps the demo alive)
  - Pricing tiers (Free / Standard 30 EGP / Premium 90 EGP)
  - Egyptian market positioning section
  - CTA "Track Your First Deal" deep-linking to the app/WhatsApp bot
  - AR/EN language toggle, RTL-ready layout direction
- `frontend/src/style.css` — premium dark theme, mobile-responsive
- `frontend/src/main.js` — stats fetch + language toggle logic

Verified:
- `npm install` OK (11 packages)
- `npm run build` OK (dist: index.html 12.7 kB, css 9.5 kB, js 3.0 kB)
- `npm run preview` → HTTP 200 on http://localhost:3000/, title confirmed

### 2. Codebase survey — DONE

Full read of everything needed for the Flutter + API work:
- Flutter app: `main.dart`, `app_router.dart`, all auth pages (welcome /
  register / login / OTP), `dashboard_page.dart`, `deal_card.dart`,
  `market_pulse_header.dart`, `create_tracker_sheet.dart`, `api_client.dart`,
  `auth_repository.dart`, `alerts_repository.dart`, `providers.dart`,
  `app_colors.dart`, `pubspec.yaml`
- API service: `main.py`, `routers/auth.py`, `tracked_items_api.py`,
  `tracked_items_models.py`, `models.py`, `dependencies.py`
- `infra/sql/schema.sql` (incl. `price_history` hypertable definition)
- Engineer C's `origin/analyzer` branch surveyed (reference only, untouched)

Key findings that shape the remaining work:
- `api_client.dart` baseUrl is hardcoded to `http://192.168.1.106:8000` —
  needs to become configurable (env/`--dart-define`) for the demo
- Auth API: `POST /auth/register` and `POST /auth/login` both return
  `{access_token, token_type}` directly (register does NOT need a second
  login call — current `auth_repository.register()` does a redundant
  second login; can be simplified)
- Phone format enforced server-side: `+20XXXXXXXXXX` (13 chars), password ≥ 8
- Tracked items API: `GET /tracked-items` returns list with `lowest_price`
  per item; `POST /tracked-items` takes `canonical_product_id`, `specs`,
  `target_price`, `stores[]`
- `price_history` table exists in schema (TimescaleDB hypertable on `time`,
  indexed by `sku` and `store_id`) — the `/price-history/{sku}` endpoint
  itself is Engineer B's deliverable; the Flutter chart screen will consume
  it
- No `test/` directory, no `analysis_options.yaml` in flutter-app yet
- `fl_chart` is NOT in pubspec yet

## Not started (paused here)

Remaining todo list, in order:
1. Flutter: add `fl_chart` to pubspec, build Price History chart screen
   (`lib/src/ui/price_history/`) consuming `GET /price-history/{sku}`
2. Flutter: Deal Discovery feed screen (`lib/src/ui/deals/`) consuming
   `GET /deals/live`
3. Flutter: replace dashboard mock data with Riverpod providers hitting
   real APIs (`/tracked-items`, `/deals/live`, `/stats`)
4. Flutter: wire onboarding flow Welcome → Register (phone) → OTP →
   Dashboard (pages exist; flow needs OTP verification against API and
   proper navigation state)
5. Demo mode: `DEMO_MODE` flag + `services/api/seed_demo_data.py` seeding
   realistic Egyptian products + 90-day price histories into
   `price_history`
6. Verification: `flutter analyze` + `flutter test` pass; landing page
   serves; seeder runs end-to-end

## Housekeeping still needed

- Add `frontend/.gitignore` (node_modules/, dist/) — node_modules is
  currently untracked but not ignored
- `presentation/` directory is untracked and pre-existing (not part of
  Engineer A's work — left alone)
- Nothing has been committed yet; all new files are untracked on
  `feature/storefront`
