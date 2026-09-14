import 'package:dio/dio.dart';
import '../config.dart';
import '../demo_data.dart';
import '../models/platform_stats_model.dart';
import '../services/api_client.dart';

/// Data source for platform-wide stats (`GET /stats`).
class StatsRepository {
  final ApiClient _apiClient = ApiClient();

  Future<PlatformStats> getStats() async {
    try {
      final response = await _apiClient.dio.get('/stats');
      if (response.statusCode == 200 && response.data is Map<String, dynamic>) {
        return PlatformStats.fromJson(response.data as Map<String, dynamic>);
      }
    } on DioException catch (_) {
      // Fall through to demo fallback below.
    }
    if (AppConfig.demoMode) return DemoData.stats;
    return const PlatformStats(totalTrackers: 0, dealsToday: 0, totalSavings: 0);
  }
}
