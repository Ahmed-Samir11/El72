import 'package:dio/dio.dart';
import '../config.dart';
import '../demo_data.dart';
import '../models/tracked_item_model.dart';
import '../services/api_client.dart';

/// Shared shape for every refusal the backend can answer to a tracker create.
///
/// The point is [message]: the server's own human-facing `detail`, already
/// translated by the backend. `errorMessage` shows that instead of the
/// exception's internals, so a refusal can never put a class name on screen.
abstract class TrackerCreationRefusal implements Exception {
  const TrackerCreationRefusal(this.message);

  /// Human-facing detail from the API, when the response carried one.
  final String? message;
}

/// Thrown when the backend rejects a tracker creation with HTTP 402
/// (insufficient credits). Kept distinct from generic errors so the UI can
/// offer the "upgrade your plan" flow instead of a raw server message.
class InsufficientCreditsException extends TrackerCreationRefusal {
  const InsufficientCreditsException(super.message);
  @override
  String toString() => 'InsufficientCreditsException($message)';
}

/// Thrown when the backend rejects a tracker creation with HTTP 409 whose
/// `detail` is the structured fair-use body `{"code": "fair_use_cap", ...}`:
/// the user already has the maximum number of trackers running.
///
/// The free product's main refusal. Carries the numbers so the dialog can
/// state the ceiling the user hit instead of a generic "too many" message.
class FairUseCapException extends TrackerCreationRefusal {
  const FairUseCapException({
    required this.activeTrackers,
    required this.cap,
    String? message,
  }) : super(message);

  /// Trackers the user currently has running, or null when the server did not
  /// say. Never defaulted to 0: a cap dialog reading a made-up "0 of 0" would
  /// be worse than refusing to state a number.
  final int? activeTrackers;

  /// The per-user ceiling on active trackers, or null when the server did not
  /// send a usable number.
  final int? cap;

  @override
  String toString() => 'FairUseCapException($activeTrackers/$cap)';
}

/// Thrown when the backend rejects a tracker creation with HTTP 429:
/// creations are rate-limited (one per [MIN_CREATION_INTERVAL_SECONDS]).
///
/// [retryAfterSeconds] is what the server says to wait — it comes from the
/// structured body and falls back to the `Retry-After` header, and the server
/// rounds it upward, so waiting exactly this long gets through.
class RateLimitedException extends TrackerCreationRefusal {
  const RateLimitedException({
    required this.retryAfterSeconds,
    String? message,
    this.cause,
  }) : super(message);

  /// Seconds still to wait before another tracker may be created.
  final double retryAfterSeconds;

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
      // Trailing slash matches the route exactly. Without it the API answers
      // with a 307 redirect whose Location is http:// when it runs behind a
      // TLS-terminating proxy (e.g. Tailscale Funnel), and a release build
      // refuses cleartext, so the list failed to load.
      final response = await _apiClient.dio.get(
        '/tracked-items/',
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
      // Demo mode falls back to sample data; live mode must surface the
      // failure instead of showing an empty list as if there were no
      // trackers.
      if (AppConfig.demoMode) return DemoData.trackedItems;
      rethrow;
    }
    if (AppConfig.demoMode) return DemoData.trackedItems;
    throw Exception('Unexpected response while loading trackers');
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
            activeTrackers: _asIntOrNull(detail['active_trackers']),
            cap: _asIntOrNull(detail['cap']),
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

  /// Delete a tracker (the backend cascades to its stores and prices).
  /// Throws [DioException] on HTTP errors (e.g. 404 if already deleted).
  Future<void> deleteTrackedItem(int itemId) async {
    await _apiClient.dio.delete('/tracked-items/$itemId');
  }

  /// JSON number -> int, or null when the value is missing or not a number:
  /// a refusal whose numbers are malformed must not invent a ceiling of 0.
  static int? _asIntOrNull(Object? value) =>
      value is num ? value.toInt() : null;

  static double? _asDouble(Object? value) =>
      value is num ? value.toDouble() : null;
}
