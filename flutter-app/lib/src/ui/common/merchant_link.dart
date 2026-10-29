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
class MerchantLink {
  /// Builds a link. Tests inject [repository] and [launcher]; production
  /// callers use the default constructor unchanged.
  MerchantLink({AffiliateRepository? repository, Launcher? launcher})
    : _repository = repository ?? AffiliateRepository(),
      _launcher = launcher ?? _externalLaunch;

  final AffiliateRepository _repository;
  final Launcher _launcher;

  /// Resolve + open. Returns false only when the URL may not be handed to
  /// a browser at all (validated with the shared [isHttpUrl] rule on BOTH
  /// ends: the scraped input and the server's answer) or when the launch
  /// itself fails — callers then show their existing snackbar.
  Future<bool> open({
    required String targetUrl,
    required String source,
    String? sku,
    String? dealId,
    String? category,
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
        category: category,
      );
    } catch (error) {
      // Defensive: the real AffiliateRepository already swallows every
      // failure and returns the original URL itself. Even so, a tap must
      // never be blocked by attribution — fall back to the original.
      debugPrint('MerchantLink: resolve failed ($error); opening original');
      resolved = targetUrl;
    }
    if (!isHttpUrl(resolved)) return false;

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
