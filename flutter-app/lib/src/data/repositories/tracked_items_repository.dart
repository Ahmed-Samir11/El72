import 'package:dio/dio.dart';
import '../config.dart';
import '../demo_data.dart';
import '../models/tracked_item_model.dart';
import '../services/api_client.dart';

/// Data source for the user's tracked items (`GET /tracked-items`).
class TrackedItemsRepository {
  final ApiClient _apiClient = ApiClient();

  Future<List<TrackedItem>> getTrackedItems({bool includeInactive = false}) async {
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
  Future<void> createFromUrl(String url, {double? targetPrice}) async {
    final response = await _apiClient.dio.post(
      '/tracked-items/from-url',
      data: {
        'url': url,
        if (targetPrice != null && targetPrice > 0)
          'target_price': targetPrice,
      },
    );
    if (response.statusCode != null &&
        (response.statusCode! < 200 || response.statusCode! >= 300)) {
      final detail = response.data is Map
          ? (response.data as Map)['detail']
          : null;
      throw Exception(detail ?? 'Failed to create tracker');
    }
  }
}
