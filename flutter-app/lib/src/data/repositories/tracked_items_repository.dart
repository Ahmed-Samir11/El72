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
  /// Throws [InsufficientCreditsException] when the backend rejects the
  /// request with HTTP 402 (no credits left) and a generic [Exception] for
  /// any other failure, so the UI can offer the upgrade flow for 402 and a
  /// plain error message otherwise.
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
      // Dio throws for every non-2xx status; map the credit-exhaustion
      // signal (HTTP 402) to a typed exception and keep other failures
      // generic.
      final status = e.response?.statusCode;
      final detail = e.response?.data is Map
          ? (e.response!.data as Map)['detail']
          : null;
      // The backend sends `detail` as a string, but treat it as dynamic:
      // a non-string value must not crash the app with a TypeError.
      final message = detail is String ? detail : null;
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
}
