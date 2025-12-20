import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../services/api_client.dart';

class AlertsRepository {
  final ApiClient _apiClient = ApiClient();

  Future<void> createAlert(String targetUrl, double targetPrice) async {
    print('🎯 AlertsRepository: Creating alert...');
    print('   URL: $targetUrl');
    print('   Target Price: $targetPrice');
    
    try {
      final response = await _apiClient.dio.post(
        '/alerts',
        data: {
          'target_url': targetUrl,
          'target_price': targetPrice,
        },
      );
      
      print('📥 API Response: ${response.statusCode}');
      print('📦 Response Data: ${response.data}');
      
      if (response.statusCode == 200) {
        print('✅ Alert created successfully! ID: ${response.data['id']}');
      } else {
        throw 'Failed to create alert: Status ${response.statusCode}';
      }
    } catch (e) {
      print('❌ AlertsRepository ERROR: $e');
      throw 'Failed to create alert: $e';
    }
  }
}

final alertsRepositoryProvider = Provider<AlertsRepository>((ref) {
  return AlertsRepository();
});