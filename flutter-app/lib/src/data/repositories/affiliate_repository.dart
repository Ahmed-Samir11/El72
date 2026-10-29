import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../config.dart';
import '../services/api_client.dart';

/// Data source for the merchant-click choke point (`GET /affiliate/redirect`).
///
/// Every departure from the app to a merchant resolves through this endpoint
/// (plan p1, Gate 3/4): the server decides the store, logs an attributed
/// `affiliate_clicks` row (user via the bearer token the shared [ApiClient]
/// already attaches, plus source/sku/deal/session context) and answers with
/// a 307 to the TAGGED merchant URL. The tagged URL is the payload of that
/// request, so Dio must NOT follow the redirect — the Location header is
/// read directly.
///
/// Monetization is an optimization of the tap, never a precondition for it:
/// any failure (400 unknown host, offline, timeout, legacy server without
/// the endpoint) returns the ORIGINAL url and never throws at the call site.
class AffiliateRepository {
  /// Creates a repository. An [ApiClient] may be injected for testing;
  /// a default client is created when omitted. Prefer [shared] so the
  /// whole app resolves through one Dio instance (one connection pool,
  /// one place for the provider below) instead of building a client per
  /// widget.
  AffiliateRepository({ApiClient? apiClient})
    : _apiClient = apiClient ?? ApiClient();

  /// The process-wide instance: what the Riverstone provider and every
  /// default-constructed [MerchantLink] use.
  static final AffiliateRepository shared = AffiliateRepository();

  final ApiClient _apiClient;

  /// Resolve a merchant URL to its affiliate-tagged form (or the original
  /// URL when attribution is unavailable for any reason).
  ///
  /// [source] is the app surface that opened the merchant and must be one of
  /// the stable labels the server allowlists (`deal_feed`, `search_result`,
  /// `tracker_card`, `browse`, `web`); it is the dimension affiliate CTR is
  /// measured along, so it is required here rather than defaulted.
  Future<String> resolve({
    required String targetUrl,
    required String source,
    String? sku,
    String? dealId,
  }) async {
    // The server bounds target_url at 2048 chars; sending anything longer
    // only earns a 422. A merchant URL beyond that limit is a pathological
    // scrape: skip attribution (never the tap) and open it as-is.
    if (targetUrl.length > 2048) return targetUrl;
    final params = <String, dynamic>{
      'target_url': targetUrl,
      'source': source,
      'session_id': AppConfig.sessionId,
      if (sku != null) 'sku': sku,
      if (dealId != null) 'deal_id': dealId,
    };
    try {
      final response = await _apiClient.dio.get<String?>(
        '/affiliate/redirect',
        queryParameters: params,
        options: Options(
          // The tagged URL is returned in the 307's Location header; letting
          // Dio follow it would fetch the merchant page and hide the URL
          // we are being asked for (plan p1 risk: "Dio following the 307
          // would hide the tagged URL"). `followRedirects: false` +
          // `maxRedirects: 0` are the redirect knobs this pinned Dio (5.x)
          // exposes; there is no `maxFollowRedirects` option in it.
          followRedirects: false,
          maxRedirects: 0,
          // The tap's fallback must be fast: the shared client is tuned
          // for 30 s scraper reads, but a hanging attribution endpoint may
          // not delay opening the merchant page by half a minute.
          connectTimeout: const Duration(seconds: 2),
          receiveTimeout: const Duration(seconds: 3),
        ),
      );
      final location = _locationOf(response.headers);
      if (location != null && location.isNotEmpty) {
        return _joinOrOriginal(targetUrl, location);
      }
      // 2xx without a Location (e.g. a server that logged but cannot tag):
      // the click was still attributed; open the original.
      return targetUrl;
    } on DioException catch (error) {
      // A 3xx with followRedirects:false surfaces as a DioException whose
      // response carries the Location we actually want.
      final status = error.response?.statusCode;
      final location = _locationOf(error.response?.headers);
      if (location != null &&
          location.isNotEmpty &&
          status != null &&
          status >= 301 &&
          status <= 308) {
        return _joinOrOriginal(targetUrl, location);
      }
      // 400 (host refused / context rejected), timeout, offline, anything
      // else: the user still gets their tap. debugPrint is the counter hook
      // until plans/p4-analytics-crash-reporting-and-compliance.md wires the
      // telemetry counter.
      debugPrint(
        'AffiliateRepository: attribution unavailable '
        '(${error.response?.statusCode ?? error.type}): '
        'opening the original URL. reason=${error.message}',
      );
      return targetUrl;
    } catch (error) {
      debugPrint(
        'AffiliateRepository: unexpected attribution failure ($error): '
        'opening the original URL',
      );
      return targetUrl;
    }
  }

  /// Resolve a returned `Location` against the tapped URL, or fall back to
  /// the tapped URL itself: the never-throws contract belongs to the whole
  /// method, including its own catch blocks — a garbage Location (or a
  /// target URL that failed to parse inside a DioException handler) must
  /// still end in "open the original".
  String _joinOrOriginal(String targetUrl, String location) {
    try {
      return Uri.parse(targetUrl).resolve(location).toString();
    } catch (error) {
      debugPrint(
        'AffiliateRepository: unusable Location ($location): opening the '
        'original URL',
      );
      return targetUrl;
    }
  }

  /// The `Location` header of a Dio response, matched case-insensitively
  /// (header casing is not guaranteed across adapters), or null.
  String? _locationOf(Headers? headers) {
    if (headers == null) return null;
    for (final entry in headers.map.entries) {
      if (entry.key.toLowerCase() == 'location' && entry.value.isNotEmpty) {
        return entry.value.last;
      }
    }
    return null;
  }
}
