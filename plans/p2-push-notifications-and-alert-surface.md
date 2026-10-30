# Plan: P2 — Push Notifications and the Alert Surface

**Branch:** `feat/push-notifications-and-alert-surface` (off `main`)
**Date:** 2026-10-29
**Status:** In implementation — MS1 backend shipped on `feat/push-notifications-and-alert-surface` (PR #49,
HGM round 1 findings addressed) — `alert_events` + stream consumer + `GET /alerts/recent` + `POST /alerts/{id}/open`
+ store-facing copy truth; MS2 (Alerts tab, app copy in both locales) blocked on owner-supplied Arabic, MS3 blocked
on H2 + H3 (see §7 and the Implementation Record at §9).
**Series:** 2 of 5 release-priority plans (P1 affiliate clicks → **P2** → P3 free-tracker model, P4 analytics, P5 activation/trust).

---

## 1. Goal

Close the `WAIT → ALERT → RETURN → BUY` leg of the economic loop, honestly:

1. **Alerts exist in the app** — a durable per-user alert-event history and an Alerts
   surface, so a price event is visible the next time the app is opened even with
   zero notification infrastructure.
2. **Alerts reach a closed app** — OS push on Android is the default, low-cost channel
   (report §8 hierarchy: *push notification → secondary → email → WhatsApp*).
3. **Copy stops promising what the build cannot do** — the "you'll get a WhatsApp
   notification" promise and the listing's "Elhaq lets you know" become true, or
   they are removed until the channel ships.

Non-goals: WhatsApp cost optimization beyond keeping it as the *secondary* channel,
iOS notifications (v1 is Android-only per `plans/flutter-android-release.md`), email
channel, per-product notification scheduling beyond the existing target-price logic.

---

## 2. Current State — Evidence

| # | Finding | Evidence |
|---|---|---|
| N1 | No OS notifications: permission explicitly removed, no notification package | `flutter-app/android/app/src/main/AndroidManifest.xml:4` ("POST_NOTIFICATIONS is deferred to v1.1"); `pubspec.yaml` has no `firebase_messaging` / `flutter_local_notifications` / web-push |
| N2 | The alert path in the client is dead code: write-only, no read, never called | `flutter-app/lib/src/data/repositories/alerts_repository.dart` (only `createAlert`, provider defined in the file itself, zero references in `lib/src/ui/**`) |
| N3 | No Alerts screen: the dashboard has exactly four tabs | `flutter-app/lib/l10n/app_en.arb` (`navTrackers`, `navDeals`, `navChat`, `navProfile`) |
| N4 | The app promises WhatsApp delivery it cannot deliver | `lib/l10n/app_en.arb:68` `"trackerCreated": "✅ Tracker created! You'll get a WhatsApp notification when we find a deal."` |
| N5 | The store listing promises alerting too | `flutter-app/docs/play-store/store-listing.md` §3 "Get alerted on drops… Elhaq lets you know" |
| N6 | Server-side delivery is WhatsApp-only, and events are not persisted per user | `services/whatsapp/sender.py` (consumes `stream:confirmed_deals`, group `cg_whatsapp`; `docker-compose.yml:220-238`), `services/notification/src/index.ts` (legacy 360dialog path); `services/api/models.py:106` `Alert` = the user's *tracker* row (`notify_channel` default `"whatsapp"`), no event history table |
| N7 | The report's own cost model warns against WhatsApp-first | report §8 "Recommended notification hierarchy: Push notification (default)… WhatsApp"; §28 checklist item 13 "Why should push notifications be the default before WhatsApp?" |
| N8 | Gate 3 has no instrumentation | report §26 Gate 3 = "Do users click merchants?" preceded by "Do alerts bring users back?"; nothing in the client records an alert being opened |

---

## 3. Approach

### WS1 — Persist alert events, then show them (works with no third-party infra)

1. **New table (canonical schema first)** — `services/api` owns `alerts`, so it owns
   the event history too (`infra/sql/schema/postgres.sql`, `update_updated_at_column()`
   trigger, UUID PK, `ON DELETE CASCADE` to `users`):
   ```sql
   CREATE TABLE IF NOT EXISTS alert_events (
     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
     user_id  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
     tracked_item_id TEXT NOT NULL,
     sku      TEXT, store_id TEXT, category TEXT,
     event_type TEXT NOT NULL,      -- price_drop | threshold_crossed | lowest_price_changed | back_in_stock
     price_egp NUMERIC(12,2), reference_price_egp NUMERIC(12,2), discount_pct NUMERIC(6,2),
     channel  TEXT NOT NULL,        -- push | whatsapp | in_app
     opened_at TIMESTAMP WITH TIME ZONE,   -- set when the user sees it in-app or taps it
     created_at ..., updated_at ...
   );
   -- indexes: (user_id, created_at DESC), (tracked_item_id, created_at)
   ```
2. **Consumer in `services/api`** (new `services/api/alert_events_consumer.py`, started from
   `main.py` startup, Redis **Streams only**, `ensure_group("stream:alerts", "cg_alerts_api")`,
   `XACK` after each successful insert per `AGENTS.md` rule). Fans one event out to the
   owning user's rows via `tracked_items.user_id`. Dedupe: skip when an event for the same
   `(tracked_item_id, event_type)` exists today (the Skill 7 rate rule: *max 1 alert per
   item per day*).
3. **Read endpoint**: `GET /alerts/recent` (auth, `slowapi` limited, bounded `limit`/`since`)
   returning the last N events with `opened_at` null-or-set. Also `POST /alerts/{id}/open`
   (idempotent) so an in-app view of an alert is *measured*, which is exactly report §23's
   `alert_opened` event and Gate 3's evidence.
4. **Client**: `lib/src/data/repositories/alert_events_repository.dart` +
   `providers.dart` provider + `lib/src/ui/alerts/alerts_tab.dart` (card list: product
   image, store, delta %, "when", tap → `merchant_link` from P1). Add the fifth dashboard
   tab (`navAlerts`) ahead of Deals, since returning users should land on *what changed*.
5. Delete `alerts_repository.dart`'s dead `createAlert` path: tracker creation already
   creates the target (`POST /tracked-items/from-url` pushes to `stream:targets`), so the
   second, parallel alert-creation path is removed rather than wired (one mechanism).

### WS2 — OS push on Android (default channel)

**Decision framing** (needs H2 + H3): for a native Android app there is no
self-hosted push primitive; the standards are FCM/GCM (Firebase), or a third-party
broker (OneSignal et al.). Recommendation: **FCM**, because the same Firebase project
also satisfies P4's crash-reporting need (H2 is one decision, two features).

1. **Storage** (`services/api` owns it): `push_tokens(user_id UUID REFERENCES users …,
   token TEXT UNIQUE, platform TEXT, push_application TEXT, revoked_at TIMESTAMPTZ,
   created_at, updated_at)` — canonical schema addition.
2. **Client registration**: `flutter-app/lib/src/data/services/push_registration.dart`
   + `main.dart` bootstrap: obtain the FCM registration token after login,
   `POST /push/register` / `DELETE /push/register` on logout, revoke-and-clear on
   `410 Not Found` from the sender. Store nothing user-identifying in the token row.
3. **Sender** as its own service (service-isolation rule — no cross-service imports):
   `services/push/` (Python worker, Dockerfile, `docker-compose.yml` entry) consuming
   `stream:alerts` with consumer group **`cg_push`**, authenticating FCM HTTP v1 with a
   service-account JSON from env (`FCM_SERVICE_ACCOUNT_JSON`, `FCM_PROJECT_ID`), sending
   a collapse key per `(user_id, tracked_item_id)` so burst price changes become **one**
   notification (report §8: "Batch low-value events instead of sending repeated messages").
   Metrics: counters `el72_push_sent_total / failed / skipped / cost_estimate` in the
   same Prometheus style as `services/notification/src/index.ts:20-60`.
4. **Permission & dependency land together**: re-add `POST_NOTIFICATIONS` to the manifest
   in the *same* PR as the notification package and the data-safety/privacy update, with
   the justification row (`docs/play-store/privacy-policy.md` + `store-listing.md` §4).
   Until then the permission stays removed — no orphan permission again.
5. **Notification preference per user and product** (report §8: "notification
   preferences per user and per product"): reuse `alerts.notify_channel`
   (`services/api/models.py:119`) — the tracker creation UI writes the chosen channel
   (`push`, `whatsapp`, `in_app`) and the sender/push consumer honor it.
6. **Android-only guard**: keep iOS out of v1 — `pubspec.yaml` deps stay, but
   `flutter-app/pubspec.yaml` `flutter: uses-material-design` plus
   `firebase_messaging` init guarded by `Platform.isAndroid`; note the iOS
   `Entitlements`/`aps` work as a later release (the current plan explicitly excludes it).

### WS3 — Make the promises true, in both locales

1. Rewrite `trackerCreated` so it states what actually happens for the chosen channel
   (`push` → "we'll notify you when the price drops"; when notifications are not
   configured → "it will appear in your Alerts tab"). **The English and Arabic values
   come from the owner** (Arabic hard rule, see §7); this plan only specifies the key
   names and the truth condition.
2. `docs/play-store/store-listing.md` §3: change "Get alerted on drops" to the channel
   that actually ships, and remove the WhatsApp-first framing (report §8).
3. Add keys for: Alerts tab label, alert card ("was {price} → now {price}",
   "{n}% under its 90-day low"), notification-channel picker, "N newer alerts" badge.

### WS4 — Cost and fatigue guardrails (report §8, §25 risk "WhatsApp cost")

1. Meaningful-event gate before send: only emit when the deal-score change crosses
   the existing analyzer threshold — do not push every scrape delta.
2. Daily dedupe per item per type; collapse keys; 1-per-day ceiling for the free tier
   (Skill 7).
3. A per-user `notifications_sent / opened / tapped` rollup available to the KPI
   endpoint (`/stats/notifications`), so the report's question *"does WhatsApp create
   more contribution than it costs?"* can be answered per channel — incremental
   affiliate revenue by `channel` joins P1's `affiliate_clicks.source/channel` to
   `alert_events.channel`.

---

## 4. Files Touched

**New**
```
services/api/alert_events_consumer.py
services/api/routers/alerts.py            -- GET /alerts/recent, POST /alerts/{id}/open, /push/register
services/api/push_models.py               -- PushToken ORM
services/push/{main.py,sender.py,Dockerfile,requirements.txt,test_sender.py}
flutter-app/lib/src/data/repositories/alert_events_repository.dart
flutter-app/lib/src/data/services/push_registration.dart
flutter-app/lib/src/ui/alerts/alerts_tab.dart
flutter-app/lib/src/ui/alerts/alert_card.dart
flutter-app/test/alerts_tab_test.dart
flutter-app/test/push_registration_test.dart
```
**Modified**
```
infra/sql/schema/postgres.sql                     -- alert_events, push_tokens
services/api/models.py                     -- AlertEvent, PushToken
services/api/main.py                  -- include alerts router, start consumer
services/api/dependencies.py      -- (reuse get_current_user)
docker-compose.yml             -- push service + FCM env
services/api/main.py, .env.example              -- FCM_SERVICE_ACCOUNT_JSON, FCM_PROJECT_ID
flutter-app/pubspec.yaml                 -- firebase_messaging, firebase_flutter (+ flutter_local_notifications if offline alert echo is kept)
flutter-app/android/app/src/main/AndroidManifest.xml      -- POST_NOTIFICATIONS re-added with justification
flutter-app/lib/main.dart, lib/src/data/providers.dart, lib/src/ui/dashboard/dashboard_page.dart
flutter-app/lib/src/ui/create_tracker_sheet.dart          -- channel picker + truthful confirmation
flutter-app/lib/l10n/app_en.arb + app_ar.arb
flutter-app/docs/play-store/{privacy-policy.md,store-listing.md}
flutter-app/docs/release-checklist.md
```

---

## 5. Test Strategy

| Layer | Test file | Asserts |
|---|---|---|
| Backend consumer | `services/api/test_alert_events_consumer.py` | `ensure_group` before first read; every processed id is `xack`ed; fan-out to the owning user only; same-day dedupe; unknown `tracked_item_id` → skipped and counted, not crashed |
| Backend API | `services/api/test_alerts_api.py` | `/alerts/recent` auth-gated, bounded, ordered; `/alerts/{id}/open` idempotent and rejects another user's id (404); `/push/register` upsert + revoke |
| Push sender | `services/push/test_sender.py` | collapse key per (user, item); `MOCK_PUSH=true` path; 410 from FCM revokes the stored token; counters increment; no promotional wording in the payload (Meta-style classifier rule from Skill 7 applies to WhatsApp templates, mirrored here for neutrality) |
| Flutter unit | `test/alert_events_repository_test.dart` | demo fallback pattern (mirrors `deals_repository.dart`), rethrow in live mode |
| Flutter widget | `test/alerts_tab_test.dart`, `test/dashboard_credits_test.dart` siblings | Alerts tab renders light+dark, AR RTL + EN, tap resolves through `merchant_link`, "N newer alerts" badge; new tab does not break `test/system_ui_test.dart` |
| Copy truth | extend `test/l10n_hardcoded_strings_test.dart` allow-list shrink + a guard test asserting no shipped string mentions WhatsApp while the WhatsApp channel is not selected |
| Manual (release checklist §6) | signed AAB on a device: receive one push while the app is closed; tap → merchant opens tagged (P1); `Alerts` tab shows the event when push is disabled |

Run before PR: `pytest services/api/test_alert*.py services/push/test_*.py -v`,
`cd flutter-app && flutter test` (66 existing tests stay green), `flutter analyze`,
`dart format --set-exit-if-changed lib test`.

---

## 6. Milestones

| MS | Scope | Depends on | Est. |
|----|-------|-----------|------|
| MS1 | `alert_events` + consumer + `/alerts/recent` + `/alerts/{id}/open` (backend) | — | 1-2 d |
| MS2 | Alerts tab in the client (pull model) + copy truthfulness in both locales + listing fix | MS1 | 1-2 d |
| MS3 | `push_tokens` + register/revoke + FCM sender service + permission/dep/data-safety landed together | **H2 + H3** | 2-3 d |
| MS4 | Channel preference per product + per-channel contribution rollup | MS3, P1 (click source/channel) | 1 d |

**MS1+MS2 are unblocked and are the release-critical half**: they make alerts real
without any Google/Firebase dependency. MS3 can slip to v1.1 exactly as
`plans/flutter-android-release.md` anticipated ("defer notifications, remove the
permission now") — but only **if** MS2 removes the false promise, which today it does not.

---

## 7. Risks & Open Questions

| Risk / Question | Mitigation / Needed decision |
|---|---|
| **H2** — Firebase project + `google-services.json` (+ service account JSON) | cannot be generated in-repo; blocks MS3 only |
| **H3** — "are OS notifications in v1?" | now a *costed* decision: MS1/MS2 deliver the loop without it; if H3 = no, MS2's copy fix is mandatory, not optional |
| Notification fatigue → uninstalls (report §25 "Low retention: Very high") | dedupe + collapse keys + meaningful-delta gate (WS4), user-visible channel preference |
| Push cost becomes an unbounded variable cost (report §13 break-even math) | per-channel cost counters from WS4 so contribution margin stays computable |
| Dead-person risk: a stale registration token looks like a working subscription | revoke-on-410 + a `push_tokens` health gauge exposed to `/stats` |
| Consumer lag between `stream:alerts` and `alert_events` | XACK only after commit; consumer lag already observable via existing Prometheus/`infra/monitoring` patterns |
| Two alert pipelines (legacy `services/notification` Node service vs `services/whatsapp`) — a third must not appear by accident | `AGENTS.md` labels `services/notification` legacy; the new `services/push` worker consumes the same stream with its own group; document in the Streams table in `.agents/AGENTS.md` **from a maintainer session** (`scripts/check_agents.py` blocks agent-dir edits otherwise) |

### ⚠️ Human input required
| # | Item | Why |
|---|---|---|
| H2 | Firebase project, `google-services.json`, service-account JSON (shared with P4 crash reporting) | external account creation |
| H3 | Whether OS push ships in v1.0 or v1.1 | product decision; determines whether MS3 is release-blocking |
| — | Arabic strings for every new/changed UI key | `PI_MODEL=qwen3.8-flash-next-coder-iq1_m`: per `.agents/AGENTS.md` + Skill 10 the Arabic locale is authored by the owner; land `app_en.arb` and `app_ar.arb` in the same commit, never English alone |

---

## 8. Definition of Done

- [ ] A price event is visible in the app's Alerts tab on next open, with or without push
      configured, in AR (RTL) and EN, light and dark.
- [ ] Opening an alert records `alert_opened`; tapping records a merchant click (P1 path).
- [ ] When the app is closed, a meaningful price event produces **exactly one** push
      (dedupe + collapse key), on the channel the user chose.
- [ ] No shipped string or store copy promises a channel the build cannot deliver.
- [ ] `POST_NOTIFICATIONS` exists only alongside a notification dependency, sender service,
      privacy-policy row and data-safety row that all describe it.
- [ ] `alert_events` and `push_tokens` exist in `infra/sql/schema/postgres.sql` with the
      trigger/index conventions; services talk over Redis Streams only.
- [ ] All backend and Flutter suites green; review agent reports no CRITICAL/WARNING.

---

## 9. Implementation Record (deviations actually shipped)

| Planned | Shipped | Why |
|---|---|---|
| `user_id UUID NOT NULL REFERENCES users(id)` | `user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE` | `users.id` is `SERIAL` in the canonical schema (reconciled; see the header note in `infra/sql/schema/postgres.sql`) and the ORM mirrors it with `OperationalIdType` — P1 hit the same correction |
| `tracked_item_id TEXT` | `tracked_item_id INTEGER NOT NULL`, **no FK** | `tracked_items.id` is `SERIAL`; the FK is left out deliberately because `tracked_items` is scraper-owned (service isolation) and gets `idx_alert_events_item_time` instead |
| `channel TEXT NOT NULL` (free text) | `channel TEXT NOT NULL DEFAULT 'in_app' CHECK (channel IN ('in_app','push','whatsapp'))` | WS3's truth rule applies to data too: a row must not claim a push/WhatsApp send that never happened, so the only value written today is `in_app` and the CHECK widens with the sender that ships |
| `POST /alerts/{id}/open` also wired for push taps | in-app open only | the push channel is MS3 and blocked on H2; `opened_at` semantics are identical when a push tap later reuses it |
| `routers/alerts.py` also serves `/push/register` | not shipped in MS1 | the endpoint is meaningless before `push_tokens` and the FCM sender exist (MS3, H2); landing it early would be a contract with no implementation |
| consumer "started from `main.py` startup" | an `asyncio` task created in the API's startup hook, Redis connected **lazily** inside the loop, guarded by `ALERT_EVENTS_CONSUMER` (default true) + `el72_alert_events_consumer_up` gauge + `el72_alert_events_read_errors_total` | a Redis outage must not stop the API from serving alert reads; it must be observable instead (§7 "consumer lag" row), which is what the gauge and the separate read-error counter are for |
| migration for deployed trees | `infra/sql/migrations/0013_alert_events.sql`, applied by `scripts/db-bootstrap.sh`, registered in `services/common/test_migration_files.py` | the canonical file is the baseline only; deployed trees need the migration (Skill 4: canonical schema + migration + owning model move together) |
| `alert_events` backfilled from `current_prices` on upgrade | **no backfill** | an `alert_events` row asserts "a price event happened for this user"; synthesizing rows from current prices would invent events and inflate the opened/unopened ratio Gate 2 measures (§13 note in the migration file) |
| drift guard: a comment noting model↔schema parity | `services/api/test_alert_events_schema_sync.py` | AGENTS: a pair that must stay in lockstep gets a test — it pins columns (schema ↔ migration ↔ ORM), the CHECK value sets (↔ the consumer's `VALID_EVENT_TYPES`), index names, the updated_at trigger, the CASCADE retention rule and the bootstrap reference |
| Streams table gains a `cg_alerts_api` row | **not edited here** | rewriting `.agents/` rules is a maintainer-session act (§7 last risk row); this PR states the need, the edit belongs in its own PR |

### Round 1 — HGM review findings on PR #49 (CRITICAL + every WARNING addressed)

| Finding | Fix | Where |
|---|---|---|
| **CRITICAL** a payload with non-object `metadata` (list/string/number) raised inside the write, leaving the message pending forever | `_event_metadata()` yields `{}` unless metadata is an object — display context, never identity | `alert_events_consumer.py`, test `test_non_object_metadata_never_crashes_the_write` |
| WARNING the ORM wrote naive values into `TIMESTAMP WITH TIME ZONE` columns: comparisons break once psycopg2 reads them back tz-aware, while SQLite tests stay green | `alert_events` timestamps are `TIMESTAMP WITHOUT TIME ZONE`, defaulted **and** triggered in UTC (`NOW() AT TIME ZONE 'UTC'` through a dedicated trigger function, so a naive column cannot inherit the session timezone); one timestamp kind from SQL default → trigger → Python | `schema/postgres.sql`, `0013_alert_events.sql`, `models.py::_utc_naive_now`, test `test_alert_events_timestamps_are_naive_utc_everywhere` |
| WARNING `since` accepted offset-carrying bounds against naive rows | converted to UTC and stripped at one normalization point, so a client in another zone sees the same rows | `routers/alerts.py::_parse_since`, test `test_since_normalizes_an_offset_to_utc` |
| WARNING messages left pending were never reclaimed by this consumer | the loop reads its **own pending list (`0`) before** asking for new messages (`>`), and bounds redelivery: after `MAX_DELIVERY_ATTEMPTS` = 3 failures the entry is acked into `el72_alert_events_discarded_total` | `consume_loop` / `_process_with_retry`, test `test_broken_write_is_reclaimed_then_discarded_and_the_gauge_drops` |
| WARNING one fixed consumer name collides across API workers/replicas | default `alerts_api_<host>-<pid>` (env still overrides): a pending list belongs to the process that wrote it | `CONSUMER_NAME` |
| WARNING same-day dedupe raced with no database guarantee | `CREATE UNIQUE INDEX uq_alert_events_item_type_day ON alert_events(tracked_item_id, event_type, (created_at::date))` in the canonical schema **and** the migration; the write catches `IntegrityError` and answers `duplicate`. SQLite keeps the read-then-write check (the expression index is not portable) | both SQL files + `store_event`, pinned by the drift test |
| WARNING an `XACK` failure other than `ResponseError`, or any error while handling a message, could end the task while the gauge still read 1 | ack errors caught for **any** exception and counted (`el72_alert_events_ack_errors_total`); per-message handling is contained in `_process_with_retry`; the loop ends with `finally: consumer_up.set(0)` | `process_message` / `_process_with_retry` / `consume_loop` |
| WARNING dedupe and `created_at` used processing time instead of event time | `_event_time()` reads the emitter's own stamp (converted to naive UTC), so a drained backlog cannot rewrite history or steal today's dedupe slot | `_event_time`, test `test_dedupe_uses_event_time_across_midnight` |
| WARNING open-marking was not atomic under concurrency | the UPDATE carries `opened_at IS NULL` and `rowcount` decides `already_open` | `open_alert` |
| WARNING the store copy still promised alerting the build cannot deliver | §2 short description and §3's alert bullet state what actually ships (a recorded price event, visible in-app, tap → merchant); the Arabic promise is replaced by an ASCII note pending the owner's wording — machine Arabic copy is forbidden under the active model | `flutter-app/docs/play-store/store-listing.md`, `privacy-policy.md` §1/§2/§3 |
| INFO `datetime.utcnow()` deprecated | `_utc_naive_now()` for the new table only; existing tables keep their defaults (changing those is a data-visible migration, not a cleanup) | `models.py` |
| INFO the startup hook could start a second consumer | a live task is never replaced, and the log says so | `main.py::_start_alert_events_consumer` |
| INFO the dedupe index did not cover `event_type`; migration lacked a trailing newline | unique index above + plain item-time index kept for the item-history read; newline added | both SQL files, `0013_alert_events.sql` |

Deferred here, not blocked: MS2 needs the owner's Arabic values for every new key (`navAlerts`, the
alert-card lines, the channel picker, and a truthful rewrite of `trackerCreated`); MS3 needs H2 (Firebase
project, `google-services.json`, service-account JSON) and H3 (is OS push in v1.0?). If H3 answers "no", MS2's
copy fix stops being optional. The **store-facing** promise was already corrected in this PR (`store-listing.md`
§2/§3 and `privacy-policy.md` now describe an in-app alert history and state that no OS push/email/WhatsApp
channel is used); the **in-app** promise (`app_en.arb` `trackerCreated`, which claims a WhatsApp notification)
still needs the owner's Arabic to be rewritten, which is why it lands with MS2 rather than here.
