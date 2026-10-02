import 'package:dio/dio.dart';

import '../config.dart';
import '../demo_data.dart';
import '../models/credit_balance_model.dart';
import '../services/api_client.dart';

/// Data source for the user's credit balance (`GET /credits/balance`).
class CreditsRepository {
  /// Create a repository. [apiClient] is injectable for tests; defaults to
  /// a fresh [ApiClient].
  CreditsRepository({ApiClient? apiClient})
    : _apiClient = apiClient ?? ApiClient();

  final ApiClient _apiClient;

  /// Fetch the current user's credit balance and tier.
  ///
  /// Falls back to [DemoData.creditBalance] in demo mode when the backend
  /// is unreachable, matching the fallback convention of the other
  /// repositories; in live mode the [DioException] propagates so callers can
  /// render an honest error state.
  Future<CreditBalance> getBalance() async {
    try {
      final response = await _apiClient.dio.get('/credits/balance');
      if (response.statusCode == 200 && response.data is Map) {
        return CreditBalance.fromJson(
          (response.data as Map).cast<String, dynamic>(),
        );
      }
    } on DioException catch (_) {
      // Fall through to demo fallback below.
    }
    if (AppConfig.demoMode) return DemoData.creditBalance;
    throw DioException(
      requestOptions: RequestOptions(path: '/credits/balance'),
      message: 'Failed to load credit balance',
    );
  }
}
