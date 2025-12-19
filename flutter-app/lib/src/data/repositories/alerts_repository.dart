import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../services/api_client.dart';

class AlertsRepository {
  final ApiClient _apiClient = ApiClient();

  Future<void> createAlert(String targetUrl, double targetPrice) async {
    try {
      final response = await _apiClient.dio.post(
        '/alerts',
        data: {
          'target_url': targetUrl,
          'target_price': targetPrice,
        },
      );
      if (response.statusCode == 200) {
        // Success
      } else {
        throw 'Failed to create alert';
      }
    } catch (e) {
      throw 'Failed to create alert: $e';
    }
  }
}

final alertsRepositoryProvider = Provider<AlertsRepository>((ref) {
  return AlertsRepository();
});