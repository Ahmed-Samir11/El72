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
| I | Arabic scale words: `alef-lam-feh` ("and something") after a number was not multiplied, and hamza-alef spellings of the scale words were unreachable | input folds hamza-alef onto bare alef and the number-word table is folded the same way; a captured scale word extends to the whole word | `services/chatbot/test_arabic_nlp.py` — these cases were red *before* this fix and are green on the branch (the suite answers 35 passed, 0 failed): `12 alef-lam-feh` = 12000, `alefineh` = 2000 |
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

## Review response (PR #43 re-review, round 8: 12 findings, 1 CRITICAL, REQUEST_CHANGES)

| # | Finding | Verdict | Where |
| --- | --- | --- | --- |
| 1 | CRITICAL — client URL guard is not a boundary for server-side fetching | FIXED | `services/common/url_policy.py`, `create_tracked_item_from_url` answers 422 before any row is written or credit spent |
| 2 | WARNING — toast truncation off by one, can split a surrogate pair | FIXED | `toast_title.dart`: the cap reserves the ellipsis slot (`cut = max - 1`) and backs off a unit when the kept unit is a leading surrogate (`codeUnits`, since this SDK exposes no `charCodeAt`) |
| 3 | WARNING — hardcoded English strings in `chat_page.dart` break the i18n rule | PARTIAL | the credits-exhaustion toast now uses the existing bilingual `reachedLimitBody`; the two generic error strings stay pinned in the `l10n_hardcoded_strings_test.dart` allow-list. New keys need maintainer-authored Arabic, which this model must not produce |
| 4 | WARNING — service failure message shown unbounded in a snackbar | FIXED | `toastMessage(...)` bounds the add-to-feed explanation to one line like scraped titles |
| 5 | WARNING — raw exception messages surfaced | PARTIAL | `InsufficientCreditsException` no longer reaches the UI; `UnauthorizedException` still does, documented in place: no translated "session expired" key exists in either locale, so adding one is an i18n task, not a code task |
| 6 | WARNING — `sendMessage` does not guard concurrent sends | FIXED | `_sendMessage` returns when `conversation.isSending`, **and** the input field's `onSubmitted` is now gated on the same term as the send button. Pinned by `chat_page_test.dart`: a probe that re-opened either gate made the test fail, so the assertion is proven to bite rather than merely to pass |
| 7 | WARNING — conversation caps turn count, not content size | FIXED at the boundary | `clip(...)` plus `maxChatContentLength` / `maxResultTitleLength` / `maxResultStoreNameLength` in the model parsers; a link longer than `maxResultUrlLength` is dropped rather than truncated, because half an address would still be handed to the browser |
| 8 | WARNING — free-tier migration must not top up accounts that already used the new allowance | FALSE, pinned anyway | the allowance is `balance - SUM(amount) FILTER (reason IS DISTINCT FROM 'free_tier_100')`, and `deduct` writes negative amounts, so a 60-of-100 spent-down new account computes to 100 and is skipped. `test_free_tier_top_up_leaves_a_spent_down_new_account_alone` now pins exactly that case, including a signup grant journaled under the migration's own reason |
| 9 | WARNING — known failing Arabic price tests | FALSE (stale) | `pytest services/chatbot` → 35 passed; full suite green |
| 10 | INFO — `initState` does not guard a disposed conversation | FIXED | `addListener` is skipped when `_conversation.isDisposed`; the test hands the page an already-retired conversation and asserts the chat tab still paints |
| 11 | INFO — chat state invalidated on login/register but not logout | FALSE, documented | dashboard logout does invalidate `chatConversationProvider` (`dashboard_logout_test.dart` reads the retired instance and the clean replacement); `providers.dart` now states that all three identity changes reset the chat |
| 12 | INFO — hook schema change should be verified against the runner | ALREADY COVERED | `services/common/test_hook_config.py` pins `preToolUse`, the executable shell key, integer `timeoutSec`, a compiling matcher, the existing script paths, and Claude/Copilot parity |

Two defects this round found on its own, neither of which the reviewer raised:

- The billing webhook tests hardcoded the free tier's old starting balance (`credit.balance == 13`), so the
  round-5 change of the free allowance from 3 to 100 broke them silently. They now derive the expectation
  from `TIER_STARTING_CREDITS["free"]`. The suite had been run before that change and not after, which is
  how it slipped.
- `ruff check services` was red on this branch (23 errors: long lines in `i18n.py`, `search_service.py`,
  `store_scrapers.py`, `billing/main.py`, plus unsorted import blocks) while `main` was clean, so CI lint
  would have failed. All are cleaned; the `INTENT_EXTRACTION_PROMPT` text was reflowed only at existing
  whitespace and verified whitespace-equivalent to its previous version, so no prompt wording moved.

## Review response (PR #43 re-review, round 9: 12 findings, 0 CRITICAL, REQUEST_CHANGES)

Reviewer comment id `6450523509`, confidence 0.78. A previous attempt at this round
**failed technically, not as a review**: the served model ran out of output budget while
reasoning (`finish_reason=length` at `max_tokens=32768`, retried at `49152`), the JSON
never parsed, and the pilot posted a **fallback** comment (`6450286249`, confidence
`0.0`, 0 findings). That comment is not a verdict on this code and should be read as a
reviewer-model failure.

| # | Finding | Verdict | Where |
| --- | --- | --- | --- |
| 1 | WARNING — the client-side guard in `url_guard.dart` is not the boundary for server-side fetching | TRUE, and already the design; now stated where it was missing | `url_guard.dart`'s own doc comment says the rule decides only what the app may hand to a browser or forward, names `services/common/url_policy.py::fetch_block_reason` as the boundary and `POST /tracked-items/from-url` as the place it is enforced before any row write or credit spend |
| 2 | WARNING — `imageUrl` is length-clipped but not scheme-checked | FIXED | `SearchResultModel.fromJson` clears the field unless [isHttpUrl] holds, so a scraped `data:`/`file:`/custom-scheme value never reaches the image loader and the card shows its placeholder. `ProductImage` still refuses non-web urls — bounding the field is what keeps that rule from depending on every call site |
| 3 | WARNING — `clip` indexed `codeUnits[cut - 1]` for `max <= 0` | FIXED | `clip` returns `''` for `max <= 0`; `_oneLine` returns `''`/`'…'` for `max <= 1`. Pinned directly, since the public helpers only ever pass the 80 constant |
| 4 | WARNING — the whitespace fold scanned the whole remote payload before bounding | FIXED | the fold runs on a window of `max * 8` units, so the cap bounds the work as well as the display. The window is observable: content that starts past it is never seen, which is the price recorded under limitations |
| 5 | WARNING — hardcoded English remains in `chat_page.dart` | STILL OPEN — needs the maintainer | the add-tracker-failure copy, the two generic chat error strings and the expired-session message. Unchanged: `.agents/AGENTS.md` requires each English key to land with its Arabic twin, and this model (`PI_MODEL=qwen3.8-flash-next-coder-iq1_m`) must not author Arabic. Every offender is pinned in `l10n_hardcoded_strings_test.dart`, so the list can only shrink |
| 6 | WARNING — typed/pasted text is stored unbounded | FIXED at both app-side stores | `_saveDraft` clips the draft to `maxChatContentLength` and the optimistic user bubble stores `clip(text, maxChatContentLength)`. Honest limit recorded in the doc comment: this bounds what the app *retains*, not what the user may submit — the repository still receives the full text |
| 7 | WARNING — one malformed result destroys the whole reply | FIXED | new `_parseSearchResults`: non-object entries are skipped, an entry whose parse throws (`FormatException` or a bad field type) is skipped with a `debugPrint`, and the surviving entries are returned. No existing test asserted the throwing behaviour |
| 8 | WARNING — the result count was trimmed only after every entry was parsed | FIXED | `maxParsedSearchResults` is checked **before** parsing, so a hostile array cannot build fifty thousand models; a parity test pins it to `ChatConversation.maxSearchResults` so the two limits cannot drift |
| 9 | WARNING — `chatConversationProvider` lifetime is managed by hand | PARTIAL, documented | the provider is invalidated by the login, register and dashboard-logout flows (round 8 documented and tested that in `providers.dart` and `dashboard_logout_test.dart`). Deriving the provider from auth state automatically would be a provider refactor beyond this PR's scope, so the manual invalidation and its three call sites are stated in place instead |
| 10 | INFO — `displayName` strips only up to the first colon, so an empty/whitespace slug yields a label-less card | FIXED | an empty derived label falls back to the whole `canonicalProductId`. No English word is invented: that would be a new i18n key with an Arabic twin to author |
| 11 | INFO — `reset()` abandons rather than cancels an in-flight reply | ALREADY DOCUMENTED | `ChatConversation.reset`'s doc comment says exactly this and why (a per-request Dio token would have to be threaded through the repository); cited here rather than repeated |
| 12 | INFO — `messages`/`searchResults` could return a cached unmodifiable view | DECLINED | a cached view needs invalidation on every mutation, and a stale view is a worse bug than one allocation per access on a list capped at 200 messages |

One repo defect this round found on its own: the `## Test strategy` list in this plan file had
lost its lead-in bullet line (`- API: link parsing (parametrized), title persisted and exposed (incl.`)
in the round-5 plan edit, which left an orphaned continuation line under the heading. Restored.

## Review response (PR #43 re-review, round 10: 10 findings, 0 CRITICAL, REQUEST_CHANGES)

Reviewer comment id `6473817789`, feedback id `fc153956-8408-49ea-b736-2554b467d41e`,
confidence 0.75, 549.0 s, reviewed `d8c49f0`. This is the first clean run since the fallback:
the diff reached the model truncated (`323193 → 50000` characters), which is why two findings
below are false — the reviewer could not see the code that answers them.

| # | Finding | Verdict | Where |
| --- | --- | --- | --- |
| 1 | WARNING — `addTrackerFailedText` ships as a hardcoded English literal | STILL OPEN — the maintainer's to close | unchanged from round 9 #5: `.agents/AGENTS.md` requires each English key and its Arabic twin in one commit, and this model must not author Arabic. The reviewer's own suggestion ends the same way ("block merge until a native-speaker value is supplied"). Pinned in `l10n_hardcoded_strings_test.dart` so it cannot grow |
| 2 | WARNING — the outgoing chat message is not bounded before it is sent | FIXED, reversing the round-9 stance | `_sendMessage` now clips the turn once, at `maxChatContentLength`, and that same value is what the history stores and what the repository receives: the app never transmits more than it keeps. A spoken refusal of oversized input would need a new key in both locales, which is the maintainer's; clipping uses the bound already in force |
| 3 | WARNING — the results parser walks and logs every junk entry | FIXED | `maxScannedSearchResults` bounds the entries *examined*, not only the ones kept, and the skips are reported as one summary line per reply instead of one per entry. The test places a valid entry past the scan limit (not found) and one inside it (found), which is what makes the bound observable |
| 4 | WARNING — `_requireHttpUrl` does not enforce url length | FIXED | the repository now refuses anything longer than `maxResultUrlLength`, the bound the model parser already applies, so the public `addToFeed` path cannot smuggle a payload-sized link to the component that would fetch it. A legitimate 900-character referral link stays acceptable |
| 5 | WARNING — `TrackedItem.title` is not bounded at parse time | FIXED | `maxTrackedItemTitleLength` (500) clips the scraper's page title where the model reads it, which also bounds `displayName`, since that label is derived from the same field |
| 6 | WARNING — logout/demo-mode invalidation is not visible in the diff | FALSE — diff truncation | `dashboard_page.dart:332` and `:353` call `ref.invalidate(chatConversationProvider)` (logout and the demo toggle), and `dashboard_logout_test.dart` reads the retired instance and the clean replacement. The reviewer saw 50 000 of 323 193 diff characters |
| 7 | INFO — the fold window can drop content behind very long leading whitespace | FIXED, with the reviewer's first suggestion | the window is anchored on the first character that is not whitespace, so padding can no longer push the product name out of it — and it cannot split a word, because the anchor is the content itself. This SDK exposes neither `RegExp.match` nor `String.matchAll`, so the padding is walked a chunk at a time (`_contentStart`) and no more than `max * 8` units of a hostile payload are ever held |
| 8 | INFO — the two result-count caps can drift | FIXED | `ChatConversation.maxSearchResults` is now an alias of `maxParsedSearchResults`: one constant, seen from the parser side and the storage side |
| 9 | INFO — the wording calls the client repository a "server-side guard" | FIXED | `chatbot_repository.dart` now states what the check is (client-side, bypassable, defence in depth) and where the authoritative policy lives (`services/common/url_policy.py`, enforced by the API service before it visits a url) |
| 10 | INFO — the hook schema change should be verified against the loader | ALREADY COVERED | `services/common/test_hook_config.py` pins `version: 1`, the `preToolUse` group, `type: "command"`, exactly one shell key, an integer `timeoutSec`, a compiling matcher, script paths that exist, and Claude/Copilot parity — added in rounds 7-8 for exactly this finding |

Of the reviewer's `missed_tests` list, every item now exists except the oversized-send
refusal (clipped rather than refused, per #2) and the localization of `addTrackerFailedText`
(per #1): the scan test ratchets hardcoded strings, `_parseSearchResults` has the scan-bound
and per-entry tests, `chatbot_repository_test.dart` refuses the over-long url, `tracked_item_model_test.dart`
clips the title, `dashboard_logout_test.dart` covers logout invalidation and the demo toggle,
`toast_title_test.dart` covers padding past the window, and the `trackerCreated` success/failure
paths are pinned by two `chat_page_test.dart` cases.

## Review response (PR #43 re-review, round 11: 12 findings, 0 CRITICAL, REQUEST_CHANGES)

Reviewer comment id `6474664981`, feedback id `05828b7b-cb82-4856-8ac3-7eb84c16a2d0`,
confidence 0.82, 451.9 s, reviewed `617dd9a`. The diff reached the model truncated again
(`336860 → 50000` characters), which is why three findings below repeat work that is
already in the branch.

| # | Finding | Verdict | Where |
| --- | --- | --- | --- |
| 1 | WARNING — `addTrackerFailedText` is a hardcoded English fallback | STILL OPEN — the maintainer's to close | unchanged through rounds 7-11. Checked whether an existing bilingual key could carry it: `reachedLimitBody`, `paymentError`, `priceRefreshFailed` and `genericLoadError` all say something different, so reusing one would misinform the user; and a toast that says nothing is worse than one in English, so the "do not expose the fallback" suggestion is not taken either. Pinned in the scan allow-list so it cannot grow |
| 2 | WARNING — `storeId` and `currency` are not bounded | FIXED | `maxResultStoreIdLength` (64) and `maxResultCurrencyLength` (16): both are identifiers — a slug and an ISO three-letter code — so clipping far above their real shape costs nothing legitimate and stops a hostile reply from keeping oversized strings alive in the conversation |
| 3 | WARNING — `ChatbotRepository.sendMessage` does not bound the payload | FIXED | `_requireMessage` refuses a message longer than `maxChatContentLength` with an `ArgumentError`, before any request is built. The page clips, the repository refuses: a caller that hands over more than one turn is holding text the app should not have kept. Tested without touching the network |
| 4 | WARNING — the per-entry catch can hide a schema regression | PARTIAL | it still catches everything, because two different failures occur in practice (`FormatException` for a missing field, a cast error for a field of the wrong type) and round 9 asked for both to be survivable. What was missing — the failure detail — is now there: the single summary line per reply names the *first* failing entry and its message, so "one hostile entry" and "nothing parses any more" read differently. `a valid reply still parses every result` pins that good entries are never dropped by the net |
| 5 | WARNING — `displayName` returns the scraped title without folding whitespace | FIXED | `foldWhitespace` in `toast_title.dart` is now shared with the tracker card: the label folds whitespace runs without taking the toast's length cap, so a page title whose markup wrapped over lines cannot break the card layout |
| 6 | WARNING — verify the hook schema and make sure its tests run in CI | ALREADY COVERED | `services/common/test_hook_config.py` pins the schema keys, the `preToolUse` group, the executable shell key, integer `timeoutSec`, the matcher, script paths and Claude/Copilot parity; CI runs it — `.github/workflows/ci.yml` runs `ruff check services`, then `pytest services -q`, then `cd flutter-app && flutter test` |
| 7 | WARNING — the free-tier migration needs strict guards and its logic is invisible | FALSE (wrong path plus truncation) | the cited `services/api/migrations/0005_free_tier_100_credits.sql` does not exist; the migration is `infra/sql/migrations/postgres/0005_free_tier_100_credits.sql`, and `services/common/test_migration_files.py` replays its own `allowance` CTE in SQLite to prove the top-up lands once, skips `tier='paid'` accounts, is a no-op on a second run, and leaves a new account that already spent part of the allowance alone |
| 8 | WARNING — known failing Arabic tests remain | FALSE, for the fourth consecutive round | `pytest services/chatbot -q` → 35 passed; the full suite is green. The cited `services/chatbot/tests/test_arabic_price_parsing.py` does not exist |
| 9 | INFO — the whitespace scan can be linear over a large payload | DECLINED, documented | `_contentStart` walks padding a chunk at a time and copies one window, so the cost is a read of the padding rather than a fold of the payload; and both inputs are already bounded upstream — a scraped title at `maxResultTitleLength` (500) and the service's explanation at `maxChatContentLength` (20000) — so the practical worst case is a 20 000-unit walk for an 80-character line |
| 10 | INFO — `reset()` abandons rather than cancels an in-flight request | ALREADY DOCUMENTED | unchanged since round 9: cancelling needs a per-request Dio token threaded through the repository; the reply is recognised as stale by revision and identity, and the doc comment says so |
| 11 | INFO — `isHttpUrl` is permissive about host shapes | FIXED | whitespace and control characters are refused. `Uri.tryParse` does not reject them: `https://a b.com/x` parses as the single host `a%20b.com`, so a scraped attribute that wrapped over a line break would become one odd address rather than a rejection. A real link percent-encodes its own spaces and stays acceptable, which is pinned too |
| 12 | INFO — the PR mixes product changes with agent/hook infrastructure | NOTED, not split | the hook files are in this branch because round 5 demanded guards that actually run; their behaviour (`test_branch_guard.py`) and their wiring (`test_hook_config.py`) are tested here so the change and its tests land together. Splitting them out would strand the tests from the thing they cover |

The reviewer's `missed_tests` list is answered in full except the localization item (#1):
`toast_title_test.dart`, `url_guard_test.dart`, `chat_conversation_test.dart`,
`chatbot_repository_test.dart`, `chatbot_models_test.dart`, `tracked_item_model_test.dart` and
`chat_page_test.dart` each cover the cases it names, and `test_migration_files.py` the migration ones.

## Review response (PR #43 re-review, round 12: 7 findings, 0 CRITICAL, REQUEST_CHANGES)

Reviewer comment id `6475273754`, feedback id `55b92cab-9106-4c48-8b76-d32ded073228`,
confidence 0.78, 418.9 s, reviewed `508d5e0`. The run logged the reasoning-phase failure
again after posting (`finish_reason=length`, `max_tokens=32768`), but the JSON parsed and
7 findings were posted, so this is a real review.

| # | Finding | Verdict | Where |
| --- | --- | --- | --- |
| 1 | WARNING — `addTrackerFailedText` is a hardcoded English fallback | STILL OPEN, now for six rounds | the i18n rule in `.agents/AGENTS.md` requires the English key and its Arabic twin in one commit, and this model must not author Arabic. The reviewer's fallback suggestion — mark it a blocking TODO and do not merge until both locales exist — is what the allow-list pin plus this line are for: the merge decision stays with the maintainer, who has the Arabic wording |
| 2 | WARNING — session and message ids are not bounded where the reply is parsed | FIXED | `maxIdentifierLength` (64) clips `id`, `session_id` and the reply's `session_id` in all three parsers: they are UUIDs, and a session id is interpolated into the chatbot's URL path, so an oversized one is payload that would otherwise stay alive for the rest of the session. The shape check `ChatbotRepository.isSessionId` still decides whether an id is adopted at all — a 5 000-character id lands at 64 *and* fails the shape check, while a real UUID passes both |
| 3 | WARNING — the chat page may stay bound to a disposed conversation after the provider is replaced | FALSE (diff truncation) | `_ChatPageBodyState.didUpdateWidget` already returns early when the instance is identical, removes the listener from `oldWidget.conversation` unless it was disposed, and attaches to the new one — with a guard for an instance disposed in the same tick. Pinned by `chat_page_test.dart`: "an invalidated conversation is replaced, not kept" and "a reply that lands after logout is kept out of the new chat" |
| 4 | WARNING — the chatbot suite still has failing tests | FALSE, and root-caused | `pytest services/chatbot -q` → 35 passed, 0 failed. The claim recurs because this plan file said `test_arabic_nlp.py` was "already on the branch, failing before the fix", which reads as a live statement; it is reworded to say the cases were red *before* the fix and are green on the branch |
| 5 | WARNING — the free-tier migration would refund consumed credits | FALSE, pinned, wrong path again | the new allowance is `balance - SUM(amount) FILTER (reason IS DISTINCT FROM 'free_tier_100')` and `credits.py::deduct` writes negative amounts, so an account that already spent part of the allowance computes to ≤100 and is skipped; `test_free_tier_top_up_leaves_a_spent_down_new_account_alone` pins exactly that, with the idempotent re-run and `tier='paid'` cases beside it. The cited `services/api/migrations/...` still does not exist — the file is `infra/sql/migrations/postgres/0005_free_tier_100_credits.sql` |
| 6 | INFO — the whitespace scan is unbounded as a helper | DOCUMENTED, as the reviewer suggested | `_contentStart`'s doc comment now states the precondition: callers pass text already bounded at the boundary (500 for a scraped title, 20000 for the service's explanation), so the worst case is a 20 000-unit scan for an 80-character line, and a caller feeding unbounded remote text in must clip first |
| 7 | INFO — the Python formatter was not run | TRUE, and environmental | `black` is not installed in this environment (`python -m black --version` → *No module named black*), so Black formatting is unverifiable here. The lint gate that does run is `ruff check services` — clean, and it is what would have caught the branch's earlier 23 lint errors. Adding `black --check services` to CI is the maintainer's call, and it should come with the env that has Black installed |

The loop's shape is worth noting for the maintainer: rounds 10-12 each truncated the diff
(323 k → 50 k of 336-350 k characters) and each re-raised the Arabic-test and migration findings
that earlier rounds answered with tests. The recurring claims trace to two sentences in *this
plan file*, one of which is now reworded.

## Review response (PR #43 re-review, round 13: 10 findings, 0 CRITICAL, REQUEST_CHANGES)

Reviewer comment id `6475659004`, feedback id `c41ce5ae-8756-4841-88a1-01eba954fa57`,
confidence 0.78, 538.8 s, reviewed `76e229e`. Diff truncated again (`357564 → 50000`).

| # | Finding | Verdict | Where |
| --- | --- | --- | --- |
| 1 | WARNING — `addTrackerFailedText` is a hardcoded English fallback | STILL OPEN, seventh round | unchanged: the Arabic twin is the maintainer's, and no existing key says what needs saying. Ask is recorded at the end of this file |
| 2 | WARNING — the draft setter stores arbitrary text | FIXED, moving the bound onto the state | round 9 clipped at the page's `_saveDraft`; the setter in `ChatConversation` now clips to `maxChatContentLength`, so every writer inherits the limit and the page call site is plain assignment again. `chat_conversation_test.dart`: a 25 000-character draft lands at the bound, ordinary text is untouched, `reset()` still clears |
| 3 | INFO — the `sessionId` setter neither validates nor clips | FIXED | the setter clips to `maxIdentifierLength`. `ChatbotRepository.isSessionId` still decides whether an id may be *used*; this keeps a hostile path fragment from being carried by the conversation at all |
| 4 | WARNING — the hook key/matcher change may disable the branch guard | ALREADY COVERED | `services/common/test_hook_config.py` (rounds 7-8) pins `version: 1`, the `preToolUse` group, `type: "command"`, exactly one shell key, integer `timeoutSec`, a compiling matcher, that the script path exists, and Claude/Copilot parity; `test_branch_guard.py` runs both guards against throwaway repos |
| 5 | WARNING — the hooks depend on Python scripts that must be in the PR | FALSE (truncation) | `scripts/check_branch.py` and `scripts/check_agents.py` are on this branch, and the test above asserts the configured command points at a script that exists on disk |
| 6 | INFO — a non-http `url` survives in `SearchResultModel` | FIXED | `url` is now cleared unless it is an absolute http/https address — the same rule `image_url` already followed. `isLaunchable` gated the tap either way; the point is that no consumer of the field can mistake `file:`/`data:` for a safe value. `https://…/product-1.html#price` is still kept whole |
| 7 | INFO — `displayName` folds whitespace but not control characters | FIXED | `foldWhitespace` removes control characters that are not whitespace before folding: unlike a newline they survive a whitespace fold and reach the screen as a replacement glyph |
| 8 | INFO — the url guard misses non-ASCII separators | FIXED | the refused set now covers C1 separators, the Unicode line/paragraph separators, NBSP and the zero-width/format characters, for the same reason as ASCII: `Uri` percent-encodes them into the host instead of rejecting the link. International and percent-encoded hosts stay acceptable, which is pinned too |
| 9 | INFO — the stored bearer token is not trimmed | FIXED | `_authOptions` trims before building the header, so a token read back with stray whitespace cannot become `Bearer  <jwt> ` and be read as malformed rather than unauthenticated |
| 10 | WARNING — the PR description reports two failing Arabic tests | ROOT CAUSE FOUND | **the PR body said it**, not the code: "Chatbot: 32 passed, 2 failed … also fail on the base branch". That sentence is what every round from 5 to 13 re-raised. It is replaced with the current run — `pytest services/chatbot -q` → 35 passed, 0 failed — and the Python/Flutter counts are refreshed to 803 passed/1 skipped and 257 passed |

## Review response (PR #43 re-review, round 14: 6 findings, 0 CRITICAL, REQUEST_CHANGES)

Reviewer comment id `6476123974`, feedback id `2f3516cf-6211-4ee1-8eba-aa87b0ad3bed`,
confidence 0.78, 531.4 s, reviewed `c05809f`. Truncation unchanged (`367271 → 50000`).

The Arabic-test claim is gone after the PR body was rewritten — which confirms
that the rounds re-raising it were reading the description, not the suite.

| # | Finding | Verdict | Where |
| --- | --- | --- | --- |
| 1 | WARNING — `_oneLine` folds whitespace but never removes control characters | FIXED | `foldWhitespace` closed that hole for card labels while `_oneLine` missed it, so the toast paths kept it: a stray escape survives a whitespace fold — it is not a line break — and renders as a replacement glyph |
| 2 | WARNING — result `title`/`storeName` are clipped but not display-sanitized | FIXED | folded *before* clipping. Clipping first spends the cap on invisible characters instead of the product name a user is trying to recognize |
| 3 | INFO — the url guard misses bidi embedding and override controls | FIXED | the refused set became the whole U+2000-U+206F block — Unicode spaces, line and paragraph separators, bidi controls, invisible formatting characters — plus C1 separators, NBSP, the zero-width marker and the interlinear annotation tags. `Uri` percent-encodes any of them into the host, which is exactly how a spoofed hostname reads clean. Non-ASCII *text* still passes |
| 4 | INFO — the surrogate back-off was duplicated in `clip` and `_oneLine` | FIXED | one `_safeCut` helper; two copies of that rule were free to drift |
| 5 | INFO — `${CLAUDE_PROJECT_DIR:-.}` under a `powershell` matcher may not expand | FALSE | Claude Code substitutes `${CLAUDE_PROJECT_DIR}` itself before the command runs — it is not shell expansion, so the tool UI cannot break it. A relative `scripts/check_branch.py` would work too, and the guard fails closed either way, but the expansion is the documented form: `.claude/settings.json` is left unchanged |
| 6 | INFO — the hook schema change may disable the branch guard, "tests may only validate JSON shape" | ALREADY COVERED | `test_branch_guard.py` runs both guard scripts as real subprocesses against throwaway repos — denied on `main`, allowed on a feature branch, fail-closed outside a repo — and `test_hook_config.py` pins the key/entry/script path both loaders read |

Six findings, none CRITICAL. The two hook items are the same ones answered in
rounds 7-9; the one WARNING open for six rounds straight (`addTrackerFailedText`)
cannot be closed here, because the Arabic wording belongs to the maintainer.

### Follow-up owed on the stacked PR #44

This branch's history was rewritten (revert pairs collapsed), so #44's branch
no longer has it as an ancestor: `git merge-base` falls back to `3bc37d0`, and
GitHub now shows 17 commits and +6 903 for #44 — work that belongs to #43.

`git rebase feat/chatbot-results-and-tracker-fixes feat/tracker-delete-and-price-ranges`
fixes it. Measured on a scratch branch (nothing pushed): the first conflict is
`services/chatbot/search_service.py` while reapplying `55515d0` *"chatbot: price
ranges, drop off-topic products, find in-budget items"*, against the rounds 4-6
rewrite of that same file. Nine files overlap in total
(`search_service.py`, `main.py`, `models.py`, `arabic_nlp.py`, `i18n.py`,
`test_main.py`, `test_migration_files.py`, `dashboard_page.dart`,
`scripts/db-bootstrap.sh`). Resolve them against this branch's current
tool-calling schema and search shape rather than the old one, then force-push
#44's branch.

## Test strategy
- API: link parsing (parametrized), title persisted and exposed (incl.
  non-dict `specs`), Amazon image/title extraction, beacon skipping; credit
  tests aligned with the 100 allowance.
- `services/common/test_url_policy.py` - the server-side fetch policy: loopback, bracketed and bare IPv6, link-local and cloud metadata endpoints, decimal/hex/octal hosts, `nip.io`-style embedded dotted quads, control characters, non-http schemes, and the public links that must stay acceptable.
- `services/api/test_tracked_items_api.py` - the same policy at the endpoint: a refused url leaves no `TrackedItem` row, so the check lands before any credit is spent.
- `flutter-app/test/toast_title_test.dart` - the shared toast bound: cap includes the ellipsis, whitespace is folded before measuring, a UTF-16 pair is never split, a page-sized service explanation collapses to one line, `clip` answers an absurdly small bound (`0`, `-3`, `1`) with nothing instead of indexing below the start of the string, and only a bounded window is ever copied and folded - a megabyte title becomes one 80-character line, padding far longer than the window no longer erases the title behind it, and a payload that is nothing but padding still yields nothing.
- `test/url_guard_test.dart` - the shared client rule: absolute http/https accepted (uppercase scheme, query, fragment, userinfo), everything else refused, and whitespace or a control character inside an address refused because `Uri` percent-encodes it into the host instead of rejecting the link.
- `chatbot_models_test.dart` (`remote text stays bounded`) - reply, message, title, store-name, store-id and currency caps, an over-long url dropped rather than truncated so the result stops looking launchable, an `image_url` kept only when it is an absolute http/https address, and identifiers clipped to `maxIdentifierLength` - a 5 000-character session id lands at 64 and fails the shape check that decides whether an id is adopted, while a real UUID passes both.
- `chatbot_models_test.dart` (`one broken result cannot destroy a reply`) - a missing field, a field of the wrong type and an entry that is not an object each drop one entry and keep its neighbours; an array of nothing but junk answers empty instead of throwing; a flooded array stops at `maxParsedSearchResults` and that cap is pinned equal to `ChatConversation.maxSearchResults`; and the number of entries *examined* is bounded - a valid entry placed past `maxScannedSearchResults` is not found, while one inside the limit is.
- `tracked_item_model_test.dart` - `displayName` never returns an empty label: `"amazon_eg:"` and a slug that is only separators fall back to the whole `canonical_product_id`, and an entirely empty id invents nothing; `title` is clipped to `maxTrackedItemTitleLength` at the parse boundary, folded onto one line, while a real product name is left whole.
- `chatbot_repository_test.dart` - `addToFeed` refuses a `productUrl` longer than `maxResultUrlLength`, and `sendMessage` refuses a message larger than `maxChatContentLength`, both before any request is built.
- `test_migration_files.py` - a free account that already spent part of the *new* allowance is not topped up again.
- `services/billing/test_webhook.py` - credit expectations derive from `TIER_STARTING_CREDITS`, so changing the allowance cannot silently break them.
- `chat_page_test.dart` - the send path stays closed while a reply is in flight (`onSubmitted` and the button's `onPressed` are both null), a page that is handed an already-disposed conversation still paints, and a pasted megabyte of text is bounded in all three places a turn exists: the draft, the history bubble, and the request the repository receives.
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
- The url fetch policy is a blocklist of private targets, not an allowlist of stores: which domains are trackable changes every time a scraper lands, and a pinned list would silently break legitimate trackers. It refuses machine-local, private-network, link-local and cloud-metadata hosts, metadata and agent sockets, control characters and hostnames with embedded dotted quads (`127.0.0.1.nip.io`); it cannot prove an accepted host is a real product page, only that the server is not being pointed at its own network.
- Truncation in the toast helpers and the model caps counts UTF-16 code units, so a cut can still fall between a base character and a combining mark or inside a ZWJ/emoji-modifier sequence. Pairs are kept whole; decoration can be lost. A grapheme-accurate boundary needs an intl dependency.
- i18n residue in the chat page: `addTrackerFailedText`, the two generic failure strings and the expired-session message are still app-authored English, pinned in the hardcoded-string allow-list. The scan is a ratchet over 121 existing hits in 52 files, not an audit: closing the rest needs maintainer-authored Arabic landing with each English key in the same commit.
- The toast fold never copies or folds the payload whole: it anchors on the first character that is not whitespace and folds `max * 8` units from there. Padding is walked a chunk at a time because this SDK exposes neither `RegExp.match` nor `String.matchAll`, so a payload that is *entirely* whitespace is walked in full - in bounded chunks, with nothing kept - and the copy stays at one window. In practice the two inputs are already bounded upstream: scraped titles by `maxResultTitleLength` (500) and the service's own explanation by `maxChatContentLength` (20000).
- A turn of the chat is bounded in all three places it exists - the draft, the history bubble, and the text handed to the repository - so the app cannot transmit more than it retains. What it does *not* do is refuse oversized input: a paste longer than `maxChatContentLength` is silently cut rather than answered with a localized "too long", because that message would be a new key needing its Arabic twin, which is the maintainer's to author. The input field itself places no limit on typing.
- Parsing results per entry trades a loud failure for a partial answer: if the service starts answering with broken entries, the app silently shows fewer cards, and the only signal is one debug line per reply counting the entries it skipped. The count caps are applied before parsing and before storing, so the rejected entries are never built rather than built and dropped.
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
