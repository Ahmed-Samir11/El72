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
}
