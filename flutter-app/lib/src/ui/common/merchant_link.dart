import 'package:flutter/foundation.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/url_guard.dart';
import '../../data/repositories/affiliate_repository.dart';

/// The one component a card may use to open a merchant web URL (plan p1,
/// Gate 3/4): every departure from the app to a store resolves through
/// `GET /affiliate/redirect` first, so it is attributable (an
/// `affiliate_clicks` row) and monetized (the opened URL carries the store's
/// affiliate tag). No widget may call `launchUrl()` on a merchant URL
/// directly — that produces an invisible, untagged tap.
///
/// The tap itself is never blocked by attribution: if the resolve fails
/// (unknown host, offline, timeout, legacy server) the ORIGINAL URL is
/// opened instead, and only a genuinely unopenable URL reports failure
/// through the card's existing `unableToOpen` snackbar.
/// Stable surface labels for the resolve call — the values the server
/// allowlists into `affiliate_clicks.source` (the dimension affiliate CTR is
/// measured along). Constants, not string literals at three call sites, so
/// the client cannot drift from itself.
const String sourceDealFeed = 'deal_feed';
const String sourceSearchResult = 'search_result';
const String sourceTrackerCard = 'tracker_card';
const String sourceAlertCard = 'alert_card';

class MerchantLink {
  /// Builds a link. Tests inject [repository] and [launcher]; production
  /// callers use [shared] — one repository (one Dio pool) for the whole
  /// app, instead of a fresh ApiClient per card tap.
  MerchantLink({AffiliateRepository? repository, Launcher? launcher})
    : _repository = repository ?? AffiliateRepository.shared,
      _launcher = launcher ?? _externalLaunch;

  /// The default link used by cards that do not inject one.
  static final MerchantLink shared = MerchantLink();

  final AffiliateRepository _repository;
  final Launcher _launcher;

  /// Resolve + open. Returns false only when the URL may not be handed to
  /// a browser at all (validated with the shared [isHttpUrl] rule) or when
  /// the launch itself fails — callers then show their existing snackbar.
  Future<bool> open({
    required String targetUrl,
    required String source,
    String? sku,
    String? dealId,
  }) async {
    // Scraped urls can be empty, malformed or hostile (`file:`, `data:`,
    // custom schemes). The same rule the chat UI and the chatbot repository
    // share — one copy, no drift; the server re-validates independently.
    if (!isHttpUrl(targetUrl)) return false;

    String resolved;
    try {
      resolved = await _repository.resolve(
        targetUrl: targetUrl,
        source: source,
        sku: sku,
        dealId: dealId,
      );
    } catch (error) {
      // Defensive: the real AffiliateRepository already swallows every
      // failure and returns the original URL itself. Even so, a tap must
      // never be blocked by attribution — fall back to the original.
      debugPrint('MerchantLink: resolve failed ($error); opening original');
      resolved = targetUrl;
    }

    // The endpoint is asked to answer with a tagged URL on a merchant host;
    // anything else (off-allowlist host, junk) must not steer the OS launch
    // onto a domain the app never promised. Fall back to the URL the user
    // actually tapped instead of opening the server's suggestion.
    if (resolved != targetUrl && !isMerchantUrl(resolved)) {
      debugPrint(
        'MerchantLink: server Location is not a supported merchant '
        'host; opening the tapped URL instead',
      );
      resolved = targetUrl;
    }

    try {
      // Android opens the merchant's own app when installed, else the
      // browser — both require the host to be in the manifest allowlist
      // (kept equal to the server's STORE_HOSTS by
      // services/api/test_affiliate_manifest_sync.py).
      return await _launcher(Uri.parse(resolved));
    } catch (error) {
      // The launcher can throw (no handler on this platform, plugin
      // error). A failed launch is reported, never allowed to escape the
      // tap handler.
      debugPrint('MerchantLink: launch failed ($error)');
      return false;
    }
  }
}

/// Launch hook for [MerchantLink]: takes an already-validated absolute
/// http/https URI and returns whether it was opened.
typedef Launcher = Future<bool> Function(Uri uri);

Future<bool> _externalLaunch(Uri uri) =>
    // url_launcher 6.x (the pinned major here) spells the plan's
    // "externalBrowser" intent as `LaunchMode.externalApplication`: the
    // URL is handed to the OS, which opens the merchant's own app when
    // installed and the browser otherwise. (The `UriLaunchMethod.externalBrowser`
    // naming in plans/p1 belongs to the url_launcher 7.x API.)
    launchUrl(uri, mode: LaunchMode.externalApplication);
