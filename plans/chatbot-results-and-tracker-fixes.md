# Plan: Chatbot Results, Add-to-Tracker, and Tracker Display Fixes

## Goal

Make the chatbot usable end-to-end in the Flutter app and make trackers show
correct product names, stores and images:

1. Searches return products instead of always "couldn't find items".
2. Results show as cards (image, title, store, price) with a working
   "Add to Feed" button.
3. The chat survives switching tabs.
4. Every free account has a 100-tracker allowance.
5. Trackers show the real product name and store, and Amazon trackers show
   the product image.

## Root causes found

| Symptom | Cause |
|---------|-------|
| Every search: "couldn't find items" | Local LLM (reasoning model, 1 server slot) spent its token budget "thinking" and timed out at 60s; 4 parallel requests queued on 1 slot; client retries added load; text prices (`"9,000"`) failed float validation |
| Few matches | ElBadr used a dead domain; 2B search URL dropped the query; Alfrensia missing; page menus filled the LLM's 8000-char window; only 1 product kept per store |
| No result cards | `ListView` inside a `Column` with unbounded height threw a layout error |
| Add to Feed failed | Client used a bare `RequestOptions` (no host); chatbot read `result_id` but the app sends `product_url`; chatbot called the API without the user's token |
| Chat wiped on tab switch | Dashboard rebuilds tabs; all chat state lived in the page's `State` |
| Old accounts limited to 3 trackers | Free allowance raised 3 → 100 only for accounts without a credits row |
| "Unknown:" / "Amazon Eg:ref=…" names, no Amazon image | Title derived from the URL; scraped title never saved; store domain list outdated; Amazon's first `<img>` is a tracking beacon |

## Approach

### Chatbot service (`services/chatbot`)
- Disable reasoning (`chat_template_kwargs.enable_thinking=false`), serialize
  LLM calls (`LLM_MAX_CONCURRENCY`, default 1), no retries, 120s timeout,
  100s overall search deadline returning partial results.
- Coerce text prices; ask for ≤10 relevant products with numeric prices.
- Fix ElBadr/2B search URLs, add Alfrensia, start the LLM window at the first
  price on the page, return the top 3 matches per store within budget.
- Accept `product_url` for add-to-feed; forward the caller's `Authorization`
  header to the API.
- `ChatResponse.tracker_created` (default `false`) says explicitly whether a
  tracker was created, so the client never infers success from the presence of
  `search_results`.

### API (`services/api`)
- Save the fetched page title in `tracked_items.specs.title`; return `title`
  from list/detail endpoints.
- Store detection: add `elbadrgroupeg.store`, `sigma-computer.com`,
  `2b.com.eg`; SKU from Amazon's slug before `/dp/` and from `?id=`.
- Price fetcher: Amazon main image (`#landingImage`), skip tracking beacons,
  title from `#productTitle` / `<title>`; the markup fallback only accepts a
  plausible product name and drops bot-wall, site-name and oversized leftovers.
- Migration `0005_free_tier_100_credits.sql`: idempotent top-up of existing
  free accounts to a 100 allowance (registered in `scripts/db-bootstrap.sh`).
  The allowance subtracts transactions whose reason `IS DISTINCT FROM
  'free_tier_100'`, so a row with an unexpected reason still counts as a
  real credit movement.

### Flutter (`flutter-app`)
- Fix result list layout; rebuild `SearchResultCard` on `ProductImage`.
- Only `http`/`https` product urls are opened or offered for "Add to Feed":
  `SearchResultModel.isLaunchable` gates both, because `result.url` comes from
  scraped third-party pages.
- Use `_dio.get/post` with auth `Options` for all chatbot calls; show the
  chatbot's message when add-to-feed did not create a tracker, keyed on
  `ChatResponseModel.trackerCreated`.
- `ChatConversation` (`ChangeNotifier`) in `chatConversationProvider` holds
  messages, results, draft and session; invalidated on login/register/demo.
  `reset()` also clears the sending flag and bumps a `revision` counter, and
  every in-flight reply is dropped when the revision it was sent under no longer
  matches — a cleared chat is not repopulated by a request the user abandoned.
  History is capped at `maxMessages` so a long session cannot grow without
  bound. `ChatPage` watches the provider and `_ChatPageBody` re-attaches its
  listener in `didUpdateWidget`, so a replaced (invalidated) conversation is
  picked up instead of the stale instance being kept.
- `ChatbotRepository` validates the session id against a UUID shape before
  interpolating it into `/chatbot/sessions/<id>`; the value can come back from
  the server, so it must not be able to change the route.
- `TrackedItem.title`; `displayName` prefers it, else the slug without the
  `store:` prefix.

## Review response (PR #43 re-review, 12 findings, 1 CRITICAL)

| # | Finding | Fix | Test |
|---|---------|-----|------|
| C | `search_result_card.dart` opened `result.url` with no scheme check — a scraped page can carry `file:`/`data:`/custom schemes, which `launchUrl` hands to another program | `SearchResultModel.isLaunchable` (absolute http/https only) gates the tap, and `launchUrl` failures/exceptions show `unableToOpen` | `search_result_card_test.dart`: https opens, `file:`/`data:`/empty do not, and "Add to Feed" is disabled with them |
| W | add-to-feed success inferred from empty `searchResults` | server sets `ChatResponse.tracker_created`; client branches on `trackerCreated` | `services/chatbot/test_main.py` asserts `tracker_created` true on the create path, false on "no results" and API failure; chat page widget test drives both |
| W | `reset()` left `isSending` set and an in-flight reply could repopulate a cleared chat | `reset()` clears sending and bumps `revision`; replies whose captured revision changed are dropped | `chat_page_test.dart`: send → reset mid-flight → reply ignored, chat stays empty |
| W | chat page kept the old conversation after `chatConversationProvider` was invalidated | `ref.watch` in `ChatPage.build`, listener re-attached in `didUpdateWidget` (old listener removed, controller re-seeded from the new draft) | `chat_page_test.dart`: invalidate then assert the new empty conversation is rendered |
| W | `addToFeed` exception handling | already present (`UnauthorizedException`, `InsufficientCreditsException`, generic) — verified, now also covered by tests | `chat_page_test.dart`: 402 surfaces the credits message |
| W | "Add to Feed" enabled with an empty/invalid url | same `isLaunchable` predicate drives the button | covered by the card test above |
| W | `0005_free_tier_100_credits.sql` used `reason <> 'free_tier_100'`, which drops rows whose reason is NULL from the allowance sum | `IS DISTINCT FROM`; the migration was also missing from the bootstrap list in `test_migration_files.py`, so the single-transaction guard never covered it | `services/common/test_migration_files.py`: 0005 registered, and asserted to compare reasons null-safely |
| W | `<title>` fallback could pick a bot wall, the bare site name or a 10 KB blob | `_is_plausible_title`: length bounds, challenge phrases, site-name-only, no-letter checks | `test_price_fetcher.py`: wall title, site-only title and oversized title rejected; `productTitle` still accepted |
| I | session id interpolated into a URL path unvalidated | `_sessionPathSegment` requires a UUID shape before the request is built (the id the server echoes back overwrites the client's) | `chatbot_repository_test.dart`: `''`, `session/../../x`, a non-hex uuid, `?x=1` and `#frag` all raise before any transport is reached |
| I | chat history unbounded | `ChatConversation.maxMessages` keeps the most recent messages | `chat_conversation_test.dart`: the cap drops the oldest first and keeps the newest |
| I | Arabic scale words: `alef-lam-feh` ("and something") after a number was not multiplied, and hamza-alef spellings of the scale words were unreachable | input folds hamza-alef onto bare alef and the number-word table is folded the same way; a captured scale word extends to the whole word | `services/chatbot/test_arabic_nlp.py` (already on the branch, failing before the fix): `12 alef-lam-feh` = 12000, `alefineh` = 2000 |
| I | `plans/chatbot-demo-monitors.md` committed internal dev addresses | addresses replaced with `<dev-host>:<port>` placeholders | — |

## Review response (PR #43 re-review, 6 findings, 0 CRITICAL)

| # | Finding | Fix | Test |
|---|---------|-----|------|
| W | a reply landing on a conversation the provider had already disposed passed `_isCurrent`: `identical()` stays true and the revision counter dies with the object | `ChatConversation.isDisposed` (set in `dispose()`) joins `_isCurrent`, and writes are ignored once disposed | `chat_conversation_test.dart`: late `addMessage`/`reset`/`isSending` after `dispose()` change nothing |
| I | `didUpdateWidget` removed a listener from a possibly disposed conversation | removal skipped when `oldWidget.conversation.isDisposed`; same guard in `dispose()` | covered by the disposed-instance test's use-after-dispose guard |
| W | `search_result_card` called `ScaffoldMessenger.of(context)` after `await launchUrl`, which throws if the tab was left meanwhile | the messenger is captured before the await and passed to `unableToOpen` | `search_result_card_test.dart` still asserts the unable-to-open toast |
| I | `isLaunchable` accepted a bare `https://` (`isAbsolute` is true with no host) | requires a non-empty `host` | `chatbot_models_test.dart`: `https://`, `http://`, `https:///` rejected; `HTTPS://…` accepted |
| I | `_authOptions` sent `Authorization: Bearer ` for an empty stored token | header only when the token is non-null and non-empty | — |
| I | an `UnauthorizedException` while the tab was off screen left no trace in the conversation | the bot message is recorded before the mounted check; only the toast needs the page | `chat_page_test.dart`'s 402 path still shows the toast; auth path is UI + chat |

Missed-test suggestions reviewed: the card's non-http refusal and the
session-id path guard already have tests; `TrackedItem.displayName` is covered
by `tracked_item_model_test.dart`; the disposed-conversation case is now
covered at model level (a widget test cannot observe a provider disposal that
happens while no consumer is attached).

## Review response (PR #43 re-review, 6 findings, 0 CRITICAL, APPROVE)

| # | Finding | Fix | Test |
|---|---------|-----|------|
| W | provider disposal can race with the page's listener | `ChatConversation.dispose()` sets `isDisposed`; `_saveDraft`, the write paths and the listener detach all check it | `chat_page_test.dart`: after `container.invalidate(...)`, the old instance reports `isDisposed`, the new conversation renders, and typing into the field drives the live instance; `chat_conversation_test.dart` covers late writes |
| W | add-to-feed toasts were hardcoded English | success reuses the already-translated `trackerCreated` key and appends the product title; the failure fallback is one shared constant instead of two copies | `chat_page_test.dart` reads the snackbar content on both paths |
| I | blank service message produced an empty toast | falls back to the shared failure text | `chat_page_test.dart`: an add refusal with `message: ''` still toasts a failure |
| I | `tracker_created` cast could throw on a non-bool | `json['tracker_created'] == true` | `chatbot_models_test.dart` covers absent / false / true |
| I | session-id validation looked like it would be retried | verified: `_retryGet` catches only `DioException`, so `ArgumentError` fails on the first attempt; documented at the retry helper | `chatbot_repository_test.dart` shows one rejection per call |
| - | locale keys for the new failure wording | deliberately NOT added: the Arabic half must come from a native speaker (see the i18n rule in `.agents/AGENTS.md` for this model), so the shared English constant stays until then | - |

## Review response (PR #43 re-review, 13 findings, 0 CRITICAL)

| # | Finding | Fix | Test |
|---|---------|-----|------|
| W | the fallback failure text is an untranslated constant | NOT closable by this model: the i18n rule in `.agents/AGENTS.md` forbids inventing the Arabic twin. The constant replaces an already-hardcoded duplicate instead of adding a new phrase, the success toast uses the existing translated `trackerCreated` key, and the maintainer is asked for the Arabic wording before merge | toast content asserted on both paths |
| W | generic chat catch paths are hardcoded English | pre-existing in this file, same constraint; recorded as pending Arabic | - |
| W | `addToFeed` trusted the card's disabled button | the method re-checks `result.isLaunchable` and answers with the already-translated `unableToOpen` | `search_result_card_test.dart` keeps the UI guard covered |
| W | an empty session id passed the null guard | the id must also have the chatbot's UUID shape (`ChatbotRepository.isSessionId`) before it is sent | `chatbot_repository_test.dart` |
| W | the session id echoed by the server was stored as-is | adopted only when UUID-shaped; otherwise the client's own id is kept and the value is logged away | - |
| W | `debugPrint('$e')` on a DioException can carry request details, headers included | `_errorSummary` logs the failure type and HTTP status only | - |
| I | listener attached to a replacement conversation without a disposed check | guarded, mirroring the removal guard | - |
| W | scraped `imageUrl` reached the image loader unvalidated | `ProductImage` now requires an absolute http/https url with a host; it previously accepted any `http` prefix (`httpfoo/x`) and fetched it | `product_image_test.dart`: data:/file:/relative/bare-https render the placeholder, a real https url reaches the loader |
| W | `setSearchResults` was unbounded | `ChatConversation.maxSearchResults` keeps the ranked head of the response | `chat_conversation_test.dart` |
| I | session id validation applied only to path segments | `_requireSessionId` guards every boundary the repository sends an id to, path and body | `chatbot_repository_test.dart` on `sendMessage`/`addToFeed` |
| I | the success toast interpolated a raw scraped title | `_toastTitle` folds whitespace and cuts at 80 characters | - |
| I | `messages`/`searchResults` getters copy their list | accepted: the caps bound the copies, and exposing a live view would leak the mutable backing list | - |
| I | a shrink-wrapped result list can hide overflow | accepted for this PR: the service returns a handful per store and the conversation caps the rest; list affordances are a UI polish item | - |

## Review response (PR #43 re-review, round 5: 5 findings, 0 CRITICAL, REQUEST_CHANGES)

Reviewer comment id `6403386723`, confidence 0.78, 835.7 s.

| # | Finding | Fix | Test |
|---|---------|-----|------|
| W | the add-to-feed failure toast is a hardcoded English constant | NOT closable by this model (i18n rule in `.agents/AGENTS.md`): the Arabic twin must come from the maintainer. Still pending, unchanged from the previous round | `chat_page_test.dart` asserts the toast text on both paths |
| W | the generic chat catch paths are hardcoded English | pre-existing wording, same constraint; recorded as pending Arabic rather than re-typed here | - |
| W | `search_result_card` showed a snackbar through `ScaffoldMessenger.of(context)` after the await, i.e. after the card may have been disposed | the messenger is captured before `await launchUrl` and both post-await branches are gated on `context.mounted` | `search_result_card_test.dart` keeps the unable-to-open toast green |
| I | tapping add-to-feed before the chat had a usable session id was dropped silently deep inside `addToFeed`, which reads as a dead button | the card is rendered disabled until `ChatbotRepository.isSessionId(_conversation.sessionId ?? '')` holds, so the tap is never offered | `chat_page_test.dart`: `a result is only trackable once the chat has a usable session id` |
| W | "`services/chatbot/tests/test_arabic_price.py` is still failing" | FALSE: that path does not exist. `services/chatbot/test_search_service.py`, `test_main.py` and `test_arabic_nlp.py` all pass (35 tests) | `python -m pytest services/chatbot -q` |

## Review response (PR #43 re-review, round 6: 7 findings, 0 CRITICAL, REQUEST_CHANGES)

Reviewer comment id `6404813274`, confidence 0.78, 435.5 s.

| # | Finding | Fix | Test |
|---|---------|-----|------|
| W | `addTrackerFailedText`, the "Sorry I could not process your request" reply and the generic "An error occurred" snackbar are hardcoded English | NOT closable by this model: `.agents/AGENTS.md` requires every English key and its Arabic twin to land in one commit, and the Arabic wording is the maintainer's. Unchanged from round 5, still pending | `flutter-app/test/l10n_coverage_test.dart` fails if a key ever lands without a non-empty Arabic twin |
| W | `ChatbotRepository.addToFeed` forwarded a scraped `productUrl` with no repository-level validation, so a bypassed UI path could send a non-web scheme | new `_requireHttpUrl` static mirroring `SearchResultModel.isLaunchable` (absolute, host present, http/https only) called in `addToFeed` before any network work | `chatbot_repository_test.dart`: `refuses a product url that is not an absolute web address` over 10 hostile values (`file:`, `data:`, `javascript:`, `tel:`, `ftp:`, relative, empty, `https:///no-host`) |
| W | "chatbot suite still has failing Arabic price-parsing tests" | FALSE for the third consecutive round: `services/chatbot/tests/test_arabic_price.py` does not exist and the real suite is green | `python -m pytest services/chatbot -q` → 35 passed |
| W | the hook schema change may silently disable branch protection | TRUE, and now root-caused. A fresh `powershell` call is still denied with `Denied by preToolUse hook from ".github/hooks/check-agents.json" (hook errored)`: the file loads but the harness cannot run the command, and it fails closed. Both guards were rewritten in Python (`scripts/check_agents.py`, `scripts/check_branch.py`) because the bash versions cannot execute natively here, and the JSON is now the authoritative Copilot SDK shape (`version: 1`, `preToolUse`, one `command` key, `timeoutSec`) — the `powershell` alias was dropped because the runtime rejects a shell key alongside `exec`. Hook config is read once at session start, so this can only be verified in a fresh session | `services/common/test_branch_guard.py`: 10 tests driving both guards as subprocesses against throwaway git repos (deny on `main`, allow on `feat/guard`, fail-closed outside a repo / on an unborn branch / on an unparseable payload, agents guard deny + allow) |
| I | `sessionId`, `draft` and `isDisposed` were public mutable fields on a long-lived provider object | fields are now private (`_isDisposed`, `_sessionId`, `_draft`); `isDisposed` is read-only from outside and only `dispose()` may set it, while `sessionId`/`draft` route through setters that no-op once disposed | `flutter-app/test/chat_conversation_test.dart`: `a disposed conversation ignores late writes` now seeds a session id and a draft before `dispose()`, attempts both setters afterwards and asserts the values are unchanged |
| W | the revision/disposed race handling is central but lightly tested | partially addressed: the encapsulation above makes post-dispose writes structurally impossible rather than merely discouraged. Chat-page-level races (reset mid-reply, provider invalidation mid-reply) remain open | `chat_page_test.dart` covers reset mid-request and provider replacement; trimming and mid-flight invalidation still to add |
| I | the retroactive free-tier credit migration has no automated tests | covered. The reviewer's path was wrong — the file is `infra/sql/migrations/postgres/0005_free_tier_100_credits.sql`. No Postgres is reachable here, so the migration's own `allowance` CTE is replayed verbatim in SQLite (3.53.2) with `public` attached and `gen_random_uuid`/`now` stubbed | `services/common/test_migration_files.py`: 3 new behavioural tests — old accounts topped up to exactly 100 once, `tier='paid'` accounts untouched, running it twice is a no-op — plus the existing null-safe-reason assertion |

Two gate regressions were mine, not the reviewer's: `dart format --set-exit-if-changed` flagged the new repository test file (reformatted in place) and `flutter analyze` reported `curly_braces_in_flow_control_structures` at `search_result_card.dart:61` from the round-5 `context.mounted` guard (braced). Both gates are clean again.

## Review response (PR #43 re-review, round 7: 10 findings, 0 CRITICAL, REQUEST_CHANGES)

Reviewer comment id `6406106085`, feedback id `d7611f9c-c6eb-4c1e-9214-9541fe325b2e`, confidence 0.78, 341.9 s, reviewed `04c0349`.

| # | Finding | Fix | Test |
|---|---|---|---|
| O | `.github/hooks/block-main.json:4` — the hook schema change may silently disable branch enforcement | TRUE, and closed the only way available: the *wiring* is now under test instead of eyeballed. An entry the harness cannot spawn or parse is a guard that protects nothing, and that is invisible from inside the repo | `services/common/test_hook_config.py`: 7 tests asserting `version: 1`, a `preToolUse` group, `type: "command"`, exactly one shell key (never alongside `exec`), an integer `timeoutSec`, a compilable `matcher`, no non-Copilot `${…}` tokens, a script that exists on disk, one interpreter per file, and that both guard scripts answer with a single parsable JSON decision (exit 0 = `{}`, exit 2 = deny) |
| O | `.github/hooks/check-agents.json:4` — same risk for the agents guard | same file, plus a cross-loader assertion: every guard must be wired for Claude (`.claude/settings.json`) *and* Copilot (`.github/hooks/*.json`), with `check_branch.py` required on both sides | same test file (`test_claude_side_settings_are_kept_in_sync`) |
| O | `chat_page.dart:31` — hardcoded English user-facing strings violate the i18n rule | PARTLY FALSE — `git grep` at the PR base `a736ee7b` proves the "Sorry, I could not process your request…" reply and the "An error occurred…" snackbar predate this PR (they now sit at `:287`/`:292`); only `addTrackerFailedText` is mine. Still not closable by this model: `.agents/AGENTS.md` requires the English key and its Arabic twin in one commit, and the Arabic wording is the maintainer's | `l10n_coverage_test.dart` (parity) and the new scan test, which pins each string by name so the list can only shrink |
| O | `providers.dart:48` — the chat conversation can survive an account transition | the Profile tab's logout handler now calls `ref.invalidate(chatConversationProvider)` alongside the other invalidations (the demo-mode toggle already did) | `test/dashboard_logout_test.dart`: 2 tests — logout after the chat tab was used leaves a fresh empty conversation, the retired instance reports `isDisposed` and ignores writes; logout from a session that never opened the chat still replaces the instance |
| W | `chat_page.dart:190` — `sendMessage` can fire against a disposed conversation (`conversation.sessionId ??= …` mutates a disposed object) | explicit `if (conversation.isDisposed) return;` guard, the id is read into a local and only written back if the conversation is still live, and `addToFeed` gained the same guard | `chat_page_test.dart`: `a tap that lands on a disposed conversation issues no request` — the provider is left alone so the stale UI is still on screen, then the send icon and Add-to-Feed are tapped and both call counters stay where they were |
| W | `chatbot_repository.dart:130` — the strict absolute-url guard may reject valid **relative** product urls | REJECTED as designed: refusing relative urls is the point of round 6 #2 (they would resolve against the API base, not the vendor site). Checking it exposed a real bug though — Dart's `Uri.isAbsolute` is `hasScheme && !hasFragment`, so the guard silently rejected legitimate `#fragment` urls; it now tests `!uri.hasAuthority` | `test/url_guard_test.dart`: 3 tests including `https://2b.com.eg/p/1#price`, plus acceptance of `HTTP://` (Dart lowercases schemes) and userinfo |
| I | `chat_conversation.dart:100` — `reset()` does not cancel in-flight requests | documented rather than fixed: a reset abandons the reply (revision check drops it when it lands) but cannot cancel the HTTP call without a per-request token threaded through the repository | existing revision tests |
| I | `chat_page.dart:295` — the non-launchable toast embeds the raw scraped title | truncation moved into `lib/src/core/format/toast_title.dart` (`toastTitle`, `maxToastTitleLength = 80`) and applied at **both** refusal sites: the chat page's private `_toastTitle` is gone, and the card's own `unableToOpen` closure (reached by `!isLaunchable` *and* the launch failure/catch paths) wraps the title | `test/toast_title_test.dart`: 5 tests, plus the card case (`Unable to open Monitor ……` cut at 80 with the ellipsis, single line) and the chat-page toast case |
| O | `chatbot_repository.dart:130` — URL validation is duplicated | one guard: `lib/src/core/url_guard.dart::isHttpUrl` now backs both `SearchResultModel.isLaunchable` and `ChatbotRepository._requireHttpUrl` | `test/url_guard_test.dart` + the existing model/repository tests still passing against the shared helper |
| O | `.agents/AGENTS.md:97` — the localization rule is not enforced by tests | TRUE, and now enforced with a **ratchet** rather than a whole-app audit: a literal handed to `Text(` or a `hintText:`/`label:`/`message:`-style parameter, comment lines blanked, interpolations folded away before deciding a literal carries prose. A naive scan was not viable — the scratch scan found 121 hits across 52 files. Offenders are reported as `path|literal`, and an entry that no longer exists fails too | `test/l10n_hardcoded_strings_test.dart`: 7 tests (3 self-checks of the scanner itself, incl. a probe that a planted hardcoded string is caught; the pinned allow-list of 13 known offenders; demo fixtures and `DioException(message:)` exempted per file; Arabic-in-code check with `lib/main.dart` pinned as the web document title) |

Net round 7: 5 code fixes (logout invalidation, disposed guards, shared `toastTitle`, shared `isHttpUrl`, the `hasAuthority` fragment bug the rejection review surfaced), 2 findings closed with configuration tests instead of code, 1 documented, 1 partly false, 1 real but repo-wide (localization scan, scoped to a ratchet).

The chat-page races round 6 left open are now also closed: reset while a tracker request is in flight, and a reply that lands after the provider was invalidated — `_isCurrent` decides staleness by object identity as well as revision, because a replacement conversation restarts its counter at the same value.

## Test strategy
  non-dict `specs`), Amazon image/title extraction, beacon skipping; credit
  tests aligned with the 100 allowance.
- Chatbot: existing suite.
- Common: `test_migration_files.py` replays the free-tier migration's own
  `allowance` CTE in SQLite (no Postgres here) to prove the top-up lands once,
  skips paid accounts and is a no-op on a second run; `test_branch_guard.py`
  runs both git hooks as subprocesses against throwaway repos to prove a
  commit on `main` is denied, a feature branch is allowed, and anything
  undeterminable fails closed; `test_hook_config.py` validates the hook *wiring*
  itself — schema keys, `preToolUse`, script paths and the Claude/Copilot parity
  — so a typo cannot turn branch protection into a silent no-op.
- Flutter: chat page renders result cards without layout errors; bounded history and result caps
  survives leaving/returning; `displayName` fallbacks; add-to-feed success and
  the credits/402 path; reset mid-request; provider replacement; the card
  refuses non-http urls; add-to-feed stays disabled until the conversation holds
  a UUID-shaped session id; the shared url guard accepts `#fragment` urls; the
  shared toast title truncates a hostile scraped title at both refusal sites;
  logging out from the Profile tab replaces the chat conversation;
  a tap landing on a disposed conversation issues no request; reset while a
  tracker request is in flight drops the announcement; a reply arriving after
  the provider was invalidated is kept out of the replacement chat; and
  `l10n_hardcoded_strings_test.dart` ratchets hardcoded user-facing strings.
- Manual: end-to-end searches (English and Egyptian Arabic) against the local
  LLM; migration applied twice (second run a no-op) and on a simulated
  3-credit account.

## Known limitations
- Branch protection is **not enforced in every agent harness**: the Copilot hook
  config is read once at session start and, in the session where it was first
  reported, the configured command errored on spawn, so every `powershell`
  call was denied fail-closed regardless of branch. `.claude/settings.json`
  (Claude Code) and `.github/hooks/*.json` (Copilot) are the two loaders that do
  read these files; a harness that reads neither — pi, for instance — gets no
  guard at all. The guards themselves are correct (proven by
  `test_branch_guard.py`), and the wiring is now covered by
  `test_hook_config.py`, but neither test can prove a given harness loads them.
- Amazon/Jumia anti-bot, Noon HTTP2 errors and EgyPrice's dead domain still
  block those stores in chatbot search.
- A search takes ~50–65s on the current local model.
- The browser fetch fallback does not check HTTP status, so a 404 page that
  contains a price is treated as a product page (pre-existing).
