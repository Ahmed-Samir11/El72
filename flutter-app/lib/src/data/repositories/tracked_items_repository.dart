import 'package:dio/dio.dart';
import '../config.dart';
import '../demo_data.dart';
import '../models/tracked_item_model.dart';
import '../services/api_client.dart';

/// Thrown when the backend rejects a tracker creation with HTTP 402
/// (insufficient credits). Kept distinct from generic errors so the UI can
/// offer the "upgrade your plan" flow instead of a raw server message.
class InsufficientCreditsException implements Exception {
  const InsufficientCreditsException(this.message);

  /// Human-facing detail from the API (kept for logging/tests; the UI shows
  /// its own localized copy).
  final String message;

  @override
  String toString() => 'InsufficientCreditsException($message)';
}

/// Thrown when the backend rejects a tracker creation with HTTP 409 whose
/// `detail` is the structured fair-use body `{"code": "fair_use_cap", ...}`:
/// the user already has the maximum number of trackers running.
///
/// The free product's main refusal. Carries the numbers so the dialog can
/// state the ceiling the user hit instead of a generic "too many" message.
class FairUseCapException implements Exception {
  const FairUseCapException({
    required this.activeTrackers,
    required this.cap,
    this.message,
  });

  /// Trackers the user currently has running.
  final int activeTrackers;

  /// The per-user ceiling on active trackers.
  final int cap;

  /// Machine-facing detail from the API, kept for logging/tests.
  final String? message;

  @override
  String toString() => 'FairUseCapException($activeTrackers/$cap)';
}

/// Thrown when the backend rejects a tracker creation with HTTP 429:
/// creations are rate-limited (one per [MIN_CREATION_INTERVAL_SECONDS]).
///
/// [retryAfterSeconds] is what the server says to wait — it comes from the
/// structured body and falls back to the `Retry-After` header, and the server
/// rounds it upward, so waiting exactly this long gets through.
class RateLimitedException implements Exception {
  const RateLimitedException({
    required this.retryAfterSeconds,
    this.message,
    this.cause,
  });

  /// Seconds still to wait before another tracker may be created.
  final double retryAfterSeconds;

  /// Machine-facing detail from the API, kept for logging/tests.
  final String? message;

  /// The original [DioException], so the UI can render the same honest line
  /// any other transport failure gets instead of this exception's internals.
  final Object? cause;

  @override
  String toString() => 'RateLimitedException($retryAfterSeconds s)';
}

/// Data source for the user's tracked items (`GET /tracked-items`).
class TrackedItemsRepository {
  /// Creates a repository. An [ApiClient] may be injected for testing;
  /// a default client is created when omitted.
  TrackedItemsRepository({ApiClient? apiClient})
    : _apiClient = apiClient ?? ApiClient();

  final ApiClient _apiClient;

  Future<List<TrackedItem>> getTrackedItems({
    bool includeInactive = false,
  }) async {
    try {
      final response = await _apiClient.dio.get(
        '/tracked-items',
        queryParameters: {'include_inactive': includeInactive},
      );
      if (response.statusCode == 200 && response.data is List) {
        final list = (response.data as List)
            .whereType<Map<String, dynamic>>()
            .map(TrackedItem.fromJson)
            .toList();
        return list;
      }
    } on DioException catch (_) {
      // Fall through to demo fallback below.
    }
    if (AppConfig.demoMode) return DemoData.trackedItems;
    return const [];
  }

  /// Create a tracker from a single product URL (any supported store).
  ///
  /// Maps the refusal the backend can answer for a *free* build:
  /// [FairUseCapException] (HTTP 409, structured cap body) and
  /// [RateLimitedException] (HTTP 429 + `Retry-After`), so the sheet can
  /// state the ceiling or the countdown instead of a raw server message.
  /// [InsufficientCreditsException] (HTTP 402) is the legacy credit answer,
  /// kept for builds that run the app against a `CREDITS_ENFORCEMENT=on`
  /// backend; anything else stays a generic [Exception].
  Future<void> createFromUrl(String url, {double? targetPrice}) async {
    try {
      await _apiClient.dio.post(
        '/tracked-items/from-url',
        data: {
          'url': url,
          if (targetPrice != null && targetPrice > 0)
            'target_price': targetPrice,
        },
      );
    } on DioException catch (e) {
      // Dio throws for every non-2xx status; the server answers refusals
      // with `detail` as a string (legacy/generic paths) or as a structured
      // object (fair use), and both shapes have to be read without crashing.
      final status = e.response?.statusCode;
      final detail = e.response?.data is Map
          ? (e.response!.data as Map)['detail']
          : null;
      final message = detail is String ? detail : null;

      // Fair-use refusals carry a machine-readable `code`; branch on that,
      // never on the human-facing text.
      if (detail is Map) {
        final code = detail['code'];
        if (code == 'fair_use_cap') {
          throw FairUseCapException(
            activeTrackers: _asInt(detail['active_trackers']),
            cap: _asInt(detail['cap']),
            message: message,
          );
        }
        if (code == 'creation_rate_limit') {
          // Prefer the body's precise countdown; fall back to the header
          // (seconds, or an HTTP date we cannot parse) if it is absent.
          final seconds =
              _asDouble(detail['retry_after_seconds']) ??
              double.tryParse(e.response?.headers['retry-after']?.first ?? '');
          throw RateLimitedException(
            retryAfterSeconds: seconds ?? 0,
            message: message,
            cause: e,
          );
        }
      }

      if (status == 402) {
        throw InsufficientCreditsException(message ?? 'Insufficient credits');
      }
      throw Exception(message ?? 'Failed to create tracker');
    }
  }

  /// Re-trigger the backend price fetch for a tracker (used when the initial
  /// fetch failed or the link may have been wrong). Throws [DioException] on
  /// HTTP errors, including the 429 throttle (refresh tried < 1 min ago).
  Future<void> refreshPrice(int itemId) async {
    await _apiClient.dio.post('/tracked-items/$itemId/refresh');
  }

  /// Read an optional JSON number without crashing on a malformed value: a
  /// string or object where a number was expected must degrade to 0, not throw
  /// a cast error out of the refusal mapping.
  static int _asInt(Object? value) => value is num ? value.toInt() : 0;

  static double? _asDouble(Object? value) =>
      value is num ? value.toDouble() : null;
}
