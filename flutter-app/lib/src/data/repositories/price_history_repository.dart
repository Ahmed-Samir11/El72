import 'package:dio/dio.dart';
import '../config.dart';
import '../demo_data.dart';
import '../models/price_point_model.dart';
import '../services/api_client.dart';

/// Data source for a product's price history (`GET /price-history/{sku}`).
class PriceHistoryRepository {
  final ApiClient _apiClient = ApiClient();

  Future<List<PricePoint>> getPriceHistory(String sku) async {
    try {
      final response = await _apiClient.dio.get('/price-history/$sku');
      if (response.statusCode == 200) {
        final data = response.data;
        final List<dynamic> list;
        if (data is List) {
          list = data;
        } else if (data is Map<String, dynamic>) {
          list = (data['points'] as List?) ??
              (data['history'] as List?) ??
              (data['data'] as List?) ??
              const <dynamic>[];
        } else {
          list = const <dynamic>[];
        }
        final points = list
            .whereType<Map<String, dynamic>>()
            .map(PricePoint.fromJson)
            .toList()
          ..sort((a, b) => a.time.compareTo(b.time));
        if (points.isNotEmpty) return points;
      }
    } on DioException catch (_) {
      // Fall through to demo fallback below.
    }
    if (AppConfig.demoMode) return DemoData.priceHistory(sku);
    return const [];
  }
}
