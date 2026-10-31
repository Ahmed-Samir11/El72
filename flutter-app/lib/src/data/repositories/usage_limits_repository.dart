import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../config.dart';
import '../demo_data.dart';
import '../models/usage_limits_model.dart';
import '../services/api_client.dart';

/// Data source for the user's fair-use usage (`GET /usage/limits`).
class UsageLimitsRepository {
  /// Create a repository. An [ApiClient] may be injected for testing;
  /// a default client is created when omitted.
  UsageLimitsRepository({ApiClient? apiClient})
    : _apiClient = apiClient ?? ApiClient();

  final ApiClient _apiClient;

  /// Fetch how many trackers the user has, the ceiling they are held to, and
  /// the wait before the next one is allowed.
  ///
  /// Falls back to [DemoData.usageLimits] in demo mode when the backend is
  /// unreachable, matching the fallback convention of the other repositories;
  /// in live mode the [DioException] propagates so callers can render an
  /// honest error state (the Profile tile keeps its last known chip).
  Future<UsageLimits> getUsageLimits() async {
    try {
      final response = await _apiClient.dio.get('/usage/limits');
      if (response.statusCode == 200 && response.data is Map) {
        return UsageLimits.fromJson(
          (response.data as Map).cast<String, dynamic>(),
        );
      }
    } on DioException catch (e) {
      // Fall through to demo fallback below. In demo mode *any* failure
      // (including 401/403) is swallowed and replaced by demo data so the
      // offline UI stays usable; the failure is logged for diagnostics.
      if (AppConfig.demoMode) {
        debugPrint('UsageLimitsRepository: demo fallback after $e');
      }
    }
    if (AppConfig.demoMode) return DemoData.usageLimits;
    throw DioException(
      requestOptions: RequestOptions(path: '/usage/limits'),
      message: 'Failed to load usage limits',
    );
  }
}
