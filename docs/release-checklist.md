# Elhaq — Release Checklist

Pre-release gates that must ALL be green before tagging a `v*` release and
submitting to Play.

## 1. Automated gates (CI)

- [ ] `flutter-ci` job green on the release commit:
  - `flutter pub get` OK
  - `flutter analyze` — zero issues
  - `dart format --set-exit-if-changed lib test` — clean
  - `flutter test` — all tests passing
- [ ] Signed App Bundle artifact uploaded for the PR/tag.
- [ ] GitHub Release published from the `v*` tag with the `.aab` attached.

## 2. Build & signing

- [ ] Release keystore exists and matches the CI secrets
  (`KEY_STORE`, `KEYSTORE_PASSWORD`, `KEY_ALIAS`, `KEY_ALIAS_PASSWORD`).
  Create once via `scripts/make-release-keystore.sh` — **the owner keeps the
  original key file; it never lives in the repo**.
- [ ] `PROD_API_BASE_URL` secret is set to the production HTTPS endpoint and
  verified reachable (curl returns 200 on `/health` or equivalent).
- [ ] Built AAB opens on a physical device: splash → login → dashboard.
- [ ] Startup guard (WS5) confirmed: a release build with the emulator
  default `API_BASE_URL` fails fast with a clear log.

## 3. Platform verification (physical device, API 35)

- [ ] Status/navigation bars follow the active theme (light icons on dark).
- [ ] Arabic (RTL) and English layouts both correct; default locale ar on
  an Arabic device.
- [ ] Adaptive launcher icon renders correctly in the launcher (no safe-zone
  clipping of the falcon mark).
- [ ] App label reads "إلحق".
- [ ] Pull-to-refresh, price fetch, deal open-in-browser all work over
  cellular (not just Wi-Fi).

## 4. Store submission

- [ ] Package name `com.elhaq.tracker` confirmed available on Play
  (fallback: `com.el72.elhaq`).
- [ ] Privacy policy hosted at a public URL; support email filled in
  (`docs/play-store/privacy-policy.md` has two placeholders to replace).
- [ ] Data-safety form answered per `docs/play-store/data-safety.md`.
- [ ] Listing copy + 6 screenshots ready per `docs/play-store/listing.md`.
- [ ] Content rating "Everyone" questionnaire completed.

## 5. Rollout

- [ ] Start with a 10–20 % staged rollout; watch Crashlytics + Play vitals
  for 48 h before expanding.
- [ ] Keep the keystore and `key.properties` backed up off-machine
  (encrypted password manager + hardware copy). Losing the release key
  means you can never ship an update again.
