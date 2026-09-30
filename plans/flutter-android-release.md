# Plan: Flutter Android App — Visual Overhaul & Store-Release Readiness

**Branch:** `feat/flutter-android-release` (off `main`)
**Date:** 2026-07-09
**Status:** Draft for approval

---

## 1. Goal

Take the Elhaq (`elhaq_tracker`) Flutter app from a demo-grade prototype to:

1. **A visually polished, production-quality Android app** — consistent Material 3 design system, working dark mode, bundled fonts, full Arabic/English localization with RTL, and locale-aware price formatting.
2. **A fully deployable, Play Store-ready release** — correct package identity, minimal permissions, release signing, CI-built App Bundle, versioning, production API endpoint, and store assets (listing, privacy policy, data-safety).

Non-goals: iOS release (Android-only for v1), push notification backend work (server side is Phase 2), Flutter app-store listing for other platforms.

---

## 2. Current State — Evidence-Based Findings

### Visual / UI

| # | Finding | Evidence |
|---|---------|----------|
| V1 | Dead template code in `main.dart` (`MyApp`, `MyHomePage` counter app) | `lib/main.dart:37-172` |
| V2 | No theme tokens beyond seed color; no `surfaceContainer*`/`outline`/elevation system; no user dark-mode toggle (darkTheme exists but is never exposed in UI) | `lib/main.dart:20-35` |
| V3 | Hardcoded palette bypasses `AppColors`: `Colors.green/red/orange/grey/white` in cards and sheets → **dark mode renders broken** (white text on white, grey surfaces) | `tracker_card.dart`, `create_tracker_sheet.dart:76,85`, `deal_card.dart:121` |
| V4 | Runtime **network fonts** via `google_fonts` (JetBrainsMono, Roboto, Ubuntu) — first-launch CDN dependency, offline failure, data-use concerns | `app_colors.dart:39,45`, `welcome_page.dart`, `splash_page.dart:79` |
| V5 | IBM Plex Sans bundled **only as Bold + BoldItalic** — Regular/Medium weights fall back to device default → inconsistent type rendering | `pubspec.yaml` fonts section |
| V6 | Localization not wired: no `localizationsDelegates`/`supportedLocales` on `MaterialApp`; existing l10n classes are a **stale medical-app template** ("Hello Dr.", "patients", "AI"); every screen hardcodes English strings; **no RTL support** despite Arabic-first market | `lib/l10n/app_localizations_en.dart`, `main.dart` |
| V7 | Price formatting is raw `toStringAsFixed(2)` — no locale-aware currency/number formatting (Arabic numerals, thousands separators) | `tracker_card.dart:97,124` |
| V8 | `Image.network` with no cache, no offline placeholder strategy; minimal error builder | `tracker_card.dart:36-44` |
| V9 | Splash page shows **fake progress** (1s delays per status line) instead of real init state | `splash_page.dart:23-48` |
| V10 | No empty/error/loading state design system — ad-hoc `Text('Failed to load...')` | `dashboard_page.dart` |
| V11 | No adaptive launcher icon (foreground/background layers) — only a single `app_icon.png`; no themed/monochrome icon for API 33+/43 | `android/app/src/main/res`, `pubspec.yaml` |

### Deployment / Release

| # | Finding | Evidence |
|---|---------|----------|
| D1 | **Sample application ID** `com.example.n3n3_seha` (leftover from a previous medical project) — Play Store will reject | `android/app/build.gradle.kts:24`, `AndroidManifest.xml:2` |
| D2 | **Unjustified permissions**: `CAMERA`, `READ/WRITE_EXTERNAL_STORAGE`, `USE_BIOMETRIC`, `USE_FINGERPRINT`, `POST_NOTIFICATIONS` — none backed by a dependency or feature (no `image_picker`, no notification package). Privacy-review and Play data-safety risk | `AndroidManifest.xml:3-9` |
| D3 | `minSdk = flutter.minSdkVersion` (=21). Google Play requires **minSdk 24+** and **targetSdk 35+** for new apps (Aug 2025 policy) | `build.gradle.kts:28-29` |
| D4 | **No release signing** — no keystore/`key.properties` flow, no signed App Bundle path | `build.gradle.kts` (no signingConfigs) |
| D5 | **CI has zero Flutter jobs** — no `flutter analyze`, `flutter test`, no Android build; CI only covers Python/Node | `.github/workflows/ci.yml` |
| D6 | `API_BASE_URL` defaults to `http://10.0.2.2:8000` (**emulator loopback**) — a release build would ship pointing at nothing; cleartext HTTP is blocked by Android default (`usesCleartextTraffic=false`) | `lib/src/data/config.dart:14-17` |
| D7 | No versioning strategy — static `1.0.0+1`, no automated `versionCode` increment | `pubspec.yaml:20` |
| D8 | No crash reporting / analytics (Play best practice; required for data-safety honesty) | pubspec (no firebase/sentry) |
| D9 | No Play Store assets: listing, screenshots, **privacy policy** (mandatory), data-safety form, content rating | repo root |
| D10 | `go_router` in pubspec but unused — app uses named-route `Map<String, WidgetBuilder>`; `flutter_localizations` present but unused | `app_router.dart`, `main.dart` |

### In-flight work (coordinate with)

Uncommitted changes on `main` working tree: `dashboard_page.dart`, `tracker_card.dart`, `create_tracker_sheet.dart` (UI rework), plus `services/api/{price_fetcher,tracked_items_api}.py` + tests (on-demand price fetch). This plan's WS2 must land **on top of** that work, not conflict with it.

---

## 3. Approach — Five Workstreams

### WS1 — Design System Foundation (unblocks everything else)

1. **Full Material 3 token set** in `AppColors` → rename/expand to an `AppTheme` that builds both light and dark `ThemeData` from explicit tokens: `surface`, `surfaceContainerLow/High`, `onSurface`, `outline`, `primary/secondary/tertiary`, semantic `priceUp/priceDown/success/error/warning`.
2. **Contrast pass**: verify WCAG AA (4.5:1 body text). Known suspect: `textSecondary #8A6D3B` on cream `#FDFCEB` ≈ 3.9:1 → darken to ~`#6B5327`.
3. **Bundle all fonts locally**: add IBM Plex Sans **Regular (400), Medium (500), Bold (700) + Italic** TTFs to `assets/fonts/`; bundle a monospace for prices (JetBrains Mono or keep IBM Plex Mono); **remove the `google_fonts` dependency entirely**.
4. **Theme toggle**: persist user choice (`system | light | dark`) via SharedPreferences; `themeMode` on `MaterialApp`.
5. **Component style library** (`lib/src/core/styles/app_theme.dart`): standard `cardTheme`, `inputDecorationTheme`, `elevatedButtonTheme`, `bottomSheetTheme`, `navigationBarTheme`, `floatingActionButtonTheme`, `textTheme` scales (display/headline/title/body/label) so screens stop defining ad-hoc styles.

### WS2 — Screen-Level Visual Fixes

1. **Delete dead code** (`MyApp`, `MyHomePage`) from `main.dart`.
2. **Purge hardcoded colors** in `TrackerCard`, `DealCard`, `CreateTrackerSheet`, `MarketPulseHeader`, `TrackingStatusBox` → theme tokens only. Dark mode must render correctly on every screen.
3. **Localization (Arabic-first)**:
   - Migrate stale `lib/l10n/*.dart` template classes to **ARB files** (`lib/l10n/app_en.arb`, `app_ar.arb`) + `l10n.yaml` + `flutter gen-l10n`.
   - Wire `localizationsDelegates` + `supportedLocales: [ar, en]` on `MaterialApp`; default locale from device.
   - **RTL**: verify all rows/cards are direction-agnostic (`EdgeInsetsDirectional`, `AlignmentDirectional`); test Arabic layout end-to-end.
   - Extract **every** hardcoded string (dashboard tabs, FAB, sheets, empty states) into ARB.
4. **Locale-aware prices**: `Intl.NumberFormat.currency(locale: ..., symbol: 'EGP')` helper in `core/`; replace all `toStringAsFixed(2)` call sites.
5. **Image handling**: add `cached_network_image`; standard `ProductImage` widget with loading shimmer + branded error placeholder (used by `TrackerCard`, `DealCard`).
6. **Real splash state**: replace fake progress timer with actual `AppConfig.initialize()` + auth-token check; indeterminate progress until real work completes.
7. **State design system**: one `AsyncStateView<T>` widget (loading / error+retry / empty) used by all async screens — kills the ad-hoc `Text('Failed...')` pattern.
8. **Icons & branding**: adaptive launcher icon (foreground = falcon mark on transparent, background = brand color), monochrome variant for API 43 themed icons; keep `flutter_launcher_icons` config but generate both PNG + adaptive XML.

### WS3 — Android Platform Hardening

1. **Package identity**: `applicationId = com.elhaq.tracker` (verify domain/Play availability first); update manifest `package=` to match.
2. **Permission minimalism**: keep `INTERNET` only; remove CAMERA, storage, biometric. Keep `POST_NOTIFICATIONS` **only if** WS5 notifications land — otherwise remove.
3. **SDK levels**: pin `minSdk = 24`, `targetSdk = 35` explicitly in `build.gradle.kts`.
4. **Edge-to-edge / system UI**: handle `ViewInsets`/`SafeArea` for status+nav bars on API 35+ (default edge-to-edge); set status bar style per theme (light/dark icons).
5. **Manifest hygiene**: `android:label` stays "إلحق"; add `android:allowBackup="false"`; verify `<queries>` block only lists what `url_launcher` needs.

### WS4 — Release Engineering & CI

1. **Signing**: create release keystore, store in CI secret (`KEY_STORE` file + `key.properties` pattern); `signingConfigs.release` wired to `buildTypes.release`; local debug builds unaffected.
2. **Versioning**: semver in pubspec; CI increments `versionCode` automatically (e.g., from commit count or a `VERSION_CODE` env with default); `flutter build appbundle --release --dart-define=API_BASE_URL=<prod>`.
3. **CI Flutter job** (new `flutter-ci` job in `ci.yml`):
   - `subosito/flutter-action` (pinned stable)
   - `flutter pub get` → `flutter analyze` (fail on error) → `dart format --set-exit-if-changed` → `flutter test`
   - On PRs to `main`: build signed **App Bundle**, upload as GitHub Artifact; tag `v*` → publish artifact for release.
4. **Store assets** (`docs/play-store/`):
   - Privacy policy (hosted, covering: account data, prices, no third-party ad SDKs)
   - Data-safety form answers (data collected: phone number, tracked items; not shared; deletion available via account delete)
   - Short/long description (EN + AR), 6 screenshots per the visual pass, content rating (Everyone).
5. **Release checklist doc** (`docs/release-checklist.md`): pre-release gates (tests green, signed bundle smoke-tested on physical device, endpoint reachable over HTTPS, store listing reviewed).

### WS5 — Production Runtime Readiness

1. **API config**: production `API_BASE_URL` is HTTPS and injected at build time via `--dart-define` in CI; emulator default stays for dev. Add a startup guard: if base URL is the emulator default in a **release** build, fail fast with a clear log (prevents shipping a broken app).
2. **Auth resilience**: 401 interceptor → clear token → route to login (verify current `api_client.dart` behavior; add refresh or re-login path).
3. **Crash reporting**: add Firebase Crashlytics (or Sentry) — also needed for honest data-safety declaration. Minimal init in `main.dart`.
4. **Notifications decision** (gate): if in scope for v1 → add `flutter_local_notifications` for deal alerts + keep `POST_NOTIFICATIONS`; if out of scope → remove the permission now. **Decision needed from owner before WS3 step 2 finalizes.**
5. **Demo mode**: keep as a clearly-labeled profile setting (good for onboarding), but ensure store listing + first-run UX make live mode the default path.

---

## 4. Files Touched

### New files
```
flutter-app/lib/l10n/app_en.arb, app_ar.arb, l10n.yaml        ← ARB localization
flutter-app/lib/src/core/styles/app_theme.dart                  ← M3 token system + component themes
flutter-app/lib/src/core/styles/app_text.dart (optional)        ← text scale helpers
flutter-app/lib/src/ui/common/async_state_view.dart             ← shared loading/error/empty
flutter-app/lib/src/ui/common/product_image.dart                ← cached image widget
flutter-app/docs/play-store/privacy-policy.md                    ← store privacy policy
flutter-app/docs/play-store/store-listing.md                     ← EN/AR listing copy
flutter-app/docs/release-checklist.md                            ← release gates
android/app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml       ← adaptive icon
android/app/src/main/res/drawable/ic_launcher_foreground.xml     ← falcon foreground
android/key.properties (gitignored)                             ← signing
plans/flutter-android-release.md                                 ← this plan
```

### Modified files
```
flutter-app/lib/main.dart                                        ← delete dead code, wire l10n/themeMode/Crashlytics
flutter-app/lib/src/core/styles/app_colors.dart                  ← expand to full tokens; drop GoogleFonts
flutter-app/lib/src/ui/widgets/tracker_card.dart                 ← tokens, cached image, locale prices
flutter-app/lib/src/ui/widgets/deal_card.dart                    ← tokens, cached image, locale prices
flutter-app/lib/src/ui/create_tracker_sheet.dart                 ← tokens, l10n strings
flutter-app/lib/src/ui/dashboard/dashboard_page.dart             ← AsyncStateView, l10n, RTL check
flutter-app/lib/src/ui/common/splash_page.dart                   ← real init state, drop fake timer
flutter-app/lib/src/ui/auth/*.dart                               ← l10n strings, RTL check
flutter-app/lib/src/data/config.dart                             ← release-guard for API_BASE_URL
flutter-app/lib/src/data/services/api_client.dart                 ← 401 handling
flutter-app/pubspec.yaml                                         ← fonts, drop google_fonts, add cached_network_image + firebase_crashlytic(+sdk), versioning
flutter-app/android/app/build.gradle.kts                         ← applicationId, minSdk 24, targetSdk 35, signingConfigs
flutter-app/android/app/src/main/AndroidManifest.xml              ← package id, permission trim, allowBackup
flutter-app/test/widget_test.dart → rename to test/models_test.dart; add widget tests
.github/workflows/ci.yml                                         ← new flutter-ci job
.gitignore                                                        ← key.properties, build outputs
```

---

## 5. Test Strategy

| Layer | What | How |
|-------|------|-----|
| **Unit (existing, keep green)** | Model parsing, demo data | `flutter test` — already passes; rename `widget_test.dart` to `models_test.dart` |
| **New unit** | `Intl.NumberFormat` price helper (en + ar outputs), theme token contrast asserts | `flutter test` |
| **Widget tests (new)** | `TrackerCard` / `DealCard` render in **light and dark** themes; `AsyncStateView` states; RTL layout smoke test (Arabic locale, `Directionality.rtl`); splash → dashboard routing with fake auth | `flutter_test` with `MaterialApp` wrapped in both themes + `Localizations` |
| **Golden tests** | Dashboard (trackers tab) light+dark, one card each — catches visual regressions in CI | `matchesGoldenFile` (commit goldens; regenerate only via PR review) |
| **CI gates** | `flutter analyze` (0 errors), `dart format`, `flutter test`, signed appbundle build on `main` PRs | `.github/workflows/ci.yml` |
| **Manual QA matrix** | 3 device classes: low-end (Pixel 4a/Redmi), mid (Pixel 8), high (S24); Android 10/13/15; AR + EN locale; light/dark; offline (airplane mode) → image fallbacks, demo-mode behavior | Physical devices pre-release |
| **Release smoke** | Signed bundle on physical device: install → login → live API → add tracker → price fetch → deal card; verify no cleartext warnings | Pre-store-submission gate |

---

## 6. Milestones & Sequencing

| MS | Scope | Depends on | Est. |
|----|-------|-----------|------|
| **MS1** | WS1 design system: tokens, fonts bundled, theme toggle, component themes, contrast fix | — | 2-3 d |
| **MS2** | WS2 screens: dead code, token purge, l10n ARB + RTL, price formatting, cached images, real splash, AsyncStateView | MS1 (+ in-flight UI work merged) | 4-5 d |
| **MS3** | WS3 platform: package id, permissions, SDK levels, adaptive icons, edge-to-edge | MS2 | 1-2 d |
| **MS4** | WS4 release: signing, CI Flutter job, versioning, store assets, checklist | MS3 | 2-3 d |
| **MS5** | WS5 runtime: prod API config + guard, 401 flow, Crashlytics, notifications decision | MS3 (independent of MS2 visual work) | 2-3 d |
| **MS6** | QA matrix + release smoke + store submission | MS1–MS5 | 3-4 d |

Total: **~2.5–3 weeks** single developer, MS5 parallelizable with MS2.

---

## 7. Risks & Open Questions

| Risk / Question | Mitigation / Needed decision |
|-----------------|------------------------------|
| `com.elhaq.tracker` package name may be taken on Play | Owner verifies availability before MS3; fallback `com.el72.elhaq` |
| In-flight uncommitted UI work (dashboard/cards) conflicts with WS2 | Land the in-flight work first as its own PR; WS2 builds on top |
| Production API endpoint URL + TLS cert not finalized | Needed before MS4/MS5 builds; ask backend owner |
| Notifications in v1 or not? (permission + data-safety implications) | **Decision needed** — recommended: defer to v1.1, remove permission now |
| Crashlytics requires Firebase project + Google Services config | Create project early; `google-services.json` handled via CI secret or committed dev file |
| Golden tests on CI font rendering can be flaky across runners | Pin Flutter version in CI; treat goldens as advisory if flaky, keep widget/theme tests as the hard gate |
| Arabic translation quality | Owner/native speaker reviews ARB `app_ar.arb` before MS2 merge |

---

## 8. Definition of Done

- [ ] All screens render correctly in light **and** dark theme, in **AR (RTL)** and EN, with bundled fonts only (zero network font calls).
- [ ] Prices formatted per locale; no hardcoded colors outside the token system; no dead code.
- [ ] `flutter analyze` + `flutter test` green in CI; signed App Bundle builds on every PR to `main`.
- [ ] `applicationId` is real, permissions minimal, minSdk 24 / targetSdk 35, adaptive icon installed.
- [ ] Release build hits a real HTTPS endpoint; startup guard active; 401 → clean re-login.
- [ ] Crash reporting live; privacy policy + data-safety form + EN/AR listing complete in `docs/play-store/`.
- [ ] Physical-device smoke test passed on 3 device classes; store submission ready.

---

## 9. MS5 Kickoff — Production Runtime Readiness (in progress)

**Started:** after MS4 merged (PR #17). **Scope:** WS5 — prod API config + startup guard, 401 auth flow, crash reporting, notifications decision, demo-mode default.

### Tasks
1. **API config + startup guard** — a release build must fail fast if `API_BASE_URL` is the emulator default (`http://10.0.2.2:8000`). Emulator default stays for dev; the prod URL is injected via `--dart-define` in CI.
2. **Auth resilience** — 401 interceptor → clear stored token → route to login. Verify current `api_client.dart` behavior first (does the backend offer a refresh path, or is re-login the only option?).
3. **Crash reporting** — add Firebase Crashlytics (or Sentry) + minimal init in `main.dart`; also required for an honest data-safety declaration.
4. **Notifications decision** — in v1 or deferred? Gates the `POST_NOTIFICATIONS` permission and `flutter_local_notifications`.
5. **Demo mode** — keep as a clearly-labeled profile setting; make live mode the default first-run path.

### ⚠️ Human intervention / decisions needed BEFORE full implementation
These block parts of MS5 and need owner input:

| # | Item | Why it needs a human | Status |
|---|------|----------------------|--------|
| H1 | **Production API base URL** (real HTTPS endpoint) | Not finalized (see Risks). Needed for the CI release build's `--dart-define=API_BASE_URL=<prod>` and to verify the startup guard + 401 flow against a live backend. | ⏳ pending owner/backend |
| H2 | **Crash-reporting provider + config** | Requires creating a Firebase project + `google-services.json` (or a Sentry account + DSN). Cannot be generated in-repo. | ⏳ pending owner |
| H3 | **Notifications in v1?** | Explicit owner decision. Plan recommendation: defer to v1.1 and remove `POST_NOTIFICATIONS` now. | ⏳ pending owner |

### Can proceed WITHOUT human input (independent)
- Startup guard logic — checks the known emulator-default value; no prod URL required to write it.
- 401 → clear-token → login flow — code-only; verify against current `api_client.dart`.
- Demo-mode default-path UX — code-only.

### Blocked on human input
- CI release build wiring the real prod `API_BASE_URL` (needs **H1**).
- Crash-reporting init with a real config (needs **H2**).
- Final permission set / notifications scope (needs **H3**).
