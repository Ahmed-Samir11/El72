# Elhaq Android — Pre-Release Checklist

This is the gate a release must pass before it is signed, published to a
GitHub Release (`v*` tag), and submitted to Google Play. It mirrors the
automated `flutter-ci` and `publish-release` jobs in `.github/workflows/ci.yml`,
so most items are already enforced by CI — this doc is the human sign-off layer
on top of the automated gates.

## 1. Automated CI gates (must be green on the release commit / tag)

- [ ] **`flutter analyze`** — zero issues (the `Analyze` step fails on any issue).
- [ ] **`dart format --set-exit-if-changed lib test`** — all Dart sources formatted.
- [ ] **`flutter test`** — full unit + widget suite green.
- [ ] **Signed AAB build** — `flutter build appbundle --release` succeeds with the
      release keystore (never a debug-signed bundle; CI fails fast if any of the
      four signing secrets is missing).
- [ ] **AAB certificate check** — `scripts/verify-release-aab.py` confirms the AAB's
      SHA256 certificate matches the release keystore and the `versionCode` matches
      `RELEASE_VERSION_CODE`.
- [ ] **`PROD_API_BASE_URL` is HTTPS** — the build step rejects a non-HTTPS base URL.

## 2. Versioning (Play requirement)

- [ ] `versionCode` is a **strictly increasing** positive integer. For `v*` tag
      releases it comes from the owner-controlled `RELEASE_VERSION_CODE` secret;
      confirm it is greater than the last published `versionCode`.
- [ ] `versionName` in `flutter-app/pubspec.yaml` follows `major.minor.patch` and
      matches the intended marketing version.

## 3. Endpoint & runtime

- [ ] `PROD_API_BASE_URL` points at the **production** HTTPS gateway (not the
      `http://10.0.2.2:8000` emulator default). The release build is compiled with
      `--dart-define=API_BASE_URL=<prod>`.
- [ ] The production endpoint is reachable over TLS and returns valid responses for
      the auth + tracked-items + price flows.
- [ ] **Startup guard**: a release build that would ship with the emulator default
      base URL fails fast (see WS5 in `plans/flutter-android-release.md`).

## 4. Signing & identity

- [ ] Release keystore is the same one used for every Play submission (a changed
      certificate invalidates all prior updates). It lives only in the
      `KEY_STORE` CI secret; `flutter-app/android/key.properties` is gitignored.
- [ ] `applicationId` is final and available on Play (`com.elhaq.tracker`, or the
      agreed fallback).
- [ ] `minSdk = 24`, `targetSdk = 35` are set in `android/app/build.gradle.kts`.

## 5. Store assets (see `docs/play-store/`)

- [ ] **Privacy policy** published and hosted; URL entered in the Play console.
- [ ] **Data-safety form** answers match the privacy policy and the app's actual
      behavior (data collected, sharing, deletion).
- [ ] Short + long description present in **EN and AR**.
- [ ] 6 screenshots rendered from the current visual pass (light theme), uploaded.
- [ ] Content rating completed (target: **Everyone / E**).

## 6. Physical-device smoke test (pre-submission gate)

Run the signed AAB on at least one physical device (ideally across low/mid/high
classes and AR + EN locales):

- [ ] Install → launch → no cleartext-traffic warning.
- [ ] Login with a real account (phone number + OTP).
- [ ] Add a tracker → price fetch succeeds against the production endpoint.
- [ ] A deal card renders with a correctly formatted, locale-aware price.
- [ ] Dark mode and RTL (Arabic) both render correctly.

## 7. Submission sign-off

- [ ] All of the above checked by the release owner.
- [ ] Tag `v<major.minor.patch>` pushed → CI publishes the signed AAB to a GitHub
      Release → download the AAB and upload it to the Play Console.

---
_Keep this list in sync with `.github/workflows/ci.yml`. If a CI gate changes,
update the matching item here._
