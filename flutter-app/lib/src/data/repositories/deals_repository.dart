import 'package:dio/dio.dart';
import '../config.dart';
import '../demo_data.dart';
import '../models/deal_model.dart';
import '../services/api_client.dart';

/// Data source for the live deal discovery feed (`GET /deals/live`).
class DealsRepository {
  final ApiClient _apiClient = ApiClient();

  Future<List<Deal>> getLiveDeals() async {
    try {
      final response = await _apiClient.dio.get('/deals/live');
      if (response.statusCode == 200) {
        final data = response.data;
        final List<dynamic> list;
        if (data is List) {
          list = data;
        } else if (data is Map<String, dynamic>) {
          list = (data['deals'] as List?) ??
              (data['data'] as List?) ??
              const <dynamic>[];
        } else {
          list = const <dynamic>[];
        }
        final deals = list
            .whereType<Map<String, dynamic>>()
            .map(Deal.fromJson)
            .toList();
        if (deals.isNotEmpty) return deals;
      }
    } on DioException catch (_) {
      // Fall through to demo fallback below.
    }
    if (AppConfig.demoMode) return DemoData.deals;
    return const [];
  }
}
