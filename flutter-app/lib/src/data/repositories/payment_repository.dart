import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../config.dart';
import '../models/payment_models.dart';
import '../services/api_client.dart';

/// Data source for the Paymob wallet payment flow (Feature 2).
///
/// Endpoints (all Bearer-authenticated via [ApiClient]):
/// - `GET /payment/start` → staging token
/// - `POST /payment/confirm` (wallet) → payment id + initial status
/// - `POST /payment/confirm-otp` → OTP verification result
/// - `GET /payment/status/{payment_id}` → owner-only status
///
/// The OTP is sent to the backend over TLS only; it is never persisted or
/// logged by the app (plan 2.6). In demo mode the flow is simulated so the
/// offline UI stays usable, matching the other repositories' convention.
class PaymentRepository {
  /// Create a repository. [apiClient] is injectable for tests; defaults to
  /// the shared [ApiClient].
  PaymentRepository({ApiClient? apiClient})
    : _apiClient = apiClient ?? ApiClient();

  final ApiClient _apiClient;

  /// Start a payment: create the Paymob customer and return a staging token
  /// (bound to the user server-side, 15-minute TTL, single-use).
  Future<Map<String, String>> startPayment() async {
    try {
      final response = await _apiClient.dio.get('/payment/start');
      if (response.statusCode == 200 && response.data is Map) {
        final data = (response.data as Map).cast<String, dynamic>();
        final stagingToken = data['staging_token']?.toString() ?? '';
        if (stagingToken.isNotEmpty) {
          return {
            'staging_token': stagingToken,
            'expires_in': data['expires_in']?.toString() ?? '900',
          };
        }
      }
    } on DioException catch (e) {
      if (AppConfig.demoMode) {
        debugPrint('PaymentRepository: demo fallback after $e');
      } else {
        rethrow;
      }
    }
    if (AppConfig.demoMode) {
      return {'staging_token': 'demo_staging', 'expires_in': '900'};
    }
    throw DioException(
      requestOptions: RequestOptions(path: '/payment/start'),
      message: 'Failed to start payment',
    );
  }

  /// Confirm a wallet payment. [walletNumber] is the user's wallet phone;
  /// the price is server-determined from [packageId] (plan 2.4).
  Future<WalletPaymentResult> confirmWalletPayment({
    required String stagingToken,
    required WalletType walletType,
    required String walletNumber,
    required String packageId,
  }) async {
    try {
      final response = await _apiClient.dio.post(
        '/payment/confirm',
        data: {
          'staging_token': stagingToken,
          'method_type': 'wallet',
          'wallet_type': walletType.apiValue,
          'wallet_number': walletNumber,
          'package': packageId,
        },
      );
      if (response.statusCode == 200 && response.data is Map) {
        return WalletPaymentResult.fromJson(
          (response.data as Map).cast<String, dynamic>(),
        );
      }
    } on DioException catch (e) {
      if (AppConfig.demoMode) {
        debugPrint('PaymentRepository: demo fallback after $e');
      } else {
        rethrow;
      }
    }
    if (AppConfig.demoMode) {
      return WalletPaymentResult(
        paymentId: 'demo_payment_${walletNumber.hashCode}',
        status: 'pending_otp',
      );
    }
    throw DioException(
      requestOptions: RequestOptions(path: '/payment/confirm'),
      message: 'Failed to confirm payment',
    );
  }

  /// Submit the OTP for a wallet payment. The OTP crosses the wire in the
  /// request body only — it is never logged or stored client-side.
  Future<OtpResult> confirmWalletOtp({
    required String paymentId,
    required String otp,
  }) async {
    try {
      final response = await _apiClient.dio.post(
        '/payment/confirm-otp',
        data: {'payment_id': paymentId, 'otp': otp},
      );
      if (response.statusCode == 200 && response.data is Map) {
        return OtpResult.fromJson(
          (response.data as Map).cast<String, dynamic>(),
        );
      }
    } on DioException catch (e) {
      if (AppConfig.demoMode) {
        debugPrint('PaymentRepository: demo fallback after $e');
      } else {
        rethrow;
      }
    }
    if (AppConfig.demoMode) {
      return OtpResult(
        status: otpRegExp.hasMatch(otp) ? 'succeeded' : 'failed',
        attemptsRemaining: otpRegExp.hasMatch(otp) ? null : 2,
      );
    }
    throw DioException(
      requestOptions: RequestOptions(path: '/payment/confirm-otp'),
      message: 'Failed to verify OTP',
    );
  }

  /// Owner-only payment status. The final state is set by the Paymob
  /// webhook; poll while the status is non-terminal.
  Future<PaymentStatusInfo> getPaymentStatus(String paymentId) async {
    try {
      final response = await _apiClient.dio.get('/payment/status/$paymentId');
      if (response.statusCode == 200 && response.data is Map) {
        return PaymentStatusInfo.fromJson(
          (response.data as Map).cast<String, dynamic>(),
        );
      }
    } on DioException catch (e) {
      if (AppConfig.demoMode) {
        debugPrint('PaymentRepository: demo fallback after $e');
      } else {
        rethrow;
      }
    }
    if (AppConfig.demoMode) {
      return PaymentStatusInfo(
        paymentId: paymentId,
        package: 'standard',
        amountEgp: 30,
        status: 'succeeded',
        createdAt: '',
      );
    }
    throw DioException(
      requestOptions: RequestOptions(path: '/payment/status/$paymentId'),
      message: 'Failed to load payment status',
    );
  }
}
