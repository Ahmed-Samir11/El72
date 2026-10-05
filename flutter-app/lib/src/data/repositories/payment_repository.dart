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

  /// Single error-handling path for all endpoints (review finding #2):
  /// runs [live]; on [DioException] falls back to [demo] in demo mode
  /// (logged, per the other repositories' convention) or rethrows in live
  /// mode. A malformed 200 payload is converted to a [DioException] by the
  /// callers so both failure shapes flow through this one path.
  Future<T> _call<T>({
    required String path,
    required Future<T> Function() live,
    required T Function() demo,
  }) async {
    try {
      return await live();
    } on DioException catch (e) {
      if (!AppConfig.demoMode) rethrow;
      debugPrint('PaymentRepository: demo fallback for $path after $e');
      return demo();
    }
  }

  /// Validate a 200 JSON-object response, converting a malformed body to a
  /// [DioException] so it flows through [_call]'s single failure path.
  Map<String, dynamic> _jsonMap(Response<dynamic> response, String path) {
    if (response.statusCode != 200 || response.data is! Map) {
      throw DioException(
        requestOptions: RequestOptions(path: path),
        response: response,
        message: 'Malformed response from $path',
      );
    }
    return (response.data as Map).cast<String, dynamic>();
  }

  /// Start a payment: create the Paymob customer and return a staging token
  /// (bound to the user server-side, 15-minute TTL, single-use).
  Future<Map<String, String>> startPayment() {
    const path = '/payment/start';
    return _call(
      path: path,
      live: () async {
        final data = _jsonMap(await _apiClient.dio.get(path), path);
        return {
          'staging_token': data['staging_token']?.toString() ?? '',
          'expires_in': data['expires_in']?.toString() ?? '900',
        };
      },
      demo: () => {'staging_token': 'demo_staging', 'expires_in': '900'},
    );
  }

  /// Confirm a wallet payment. [walletNumber] is the user's wallet phone;
  /// the price is server-determined from [packageId] (plan 2.4).
  Future<WalletPaymentResult> confirmWalletPayment({
    required String stagingToken,
    required WalletType walletType,
    required String walletNumber,
    required String packageId,
  }) {
    const path = '/payment/confirm';
    return _call(
      path: path,
      live: () async {
        final data = _jsonMap(
          await _apiClient.dio.post(
            path,
            data: {
              'staging_token': stagingToken,
              'method_type': 'wallet',
              'wallet_type': walletType.apiValue,
              'wallet_number': walletNumber,
              'package': packageId,
            },
          ),
          path,
        );
        return WalletPaymentResult.fromJson(data);
      },
      demo: () => WalletPaymentResult(
        paymentId: 'demo_payment_${walletNumber.hashCode}',
        status: 'pending_otp',
      ),
    );
  }

  /// Submit the OTP for a wallet payment. The OTP crosses the wire in the
  /// request body only — it is never logged or stored client-side.
  Future<OtpResult> confirmWalletOtp({
    required String paymentId,
    required String otp,
  }) {
    const path = '/payment/confirm-otp';
    return _call(
      path: path,
      live: () async {
        final data = _jsonMap(
          await _apiClient.dio.post(
            path,
            data: {'payment_id': paymentId, 'otp': otp},
          ),
          path,
        );
        return OtpResult.fromJson(data);
      },
      demo: () => OtpResult(
        status: otpRegExp.hasMatch(otp) ? 'succeeded' : 'failed',
        attemptsRemaining: otpRegExp.hasMatch(otp) ? null : 2,
      ),
    );
  }

  /// Owner-only payment status. The final state is set by the Paymob
  /// webhook; poll while the status is non-terminal.
  Future<PaymentStatusInfo> getPaymentStatus(String paymentId) {
    final path = '/payment/status/$paymentId';
    return _call(
      path: path,
      live: () async {
        final data = _jsonMap(await _apiClient.dio.get(path), path);
        return PaymentStatusInfo.fromJson(data);
      },
      demo: () => PaymentStatusInfo(
        paymentId: paymentId,
        package: 'standard',
        amountEgp: 30,
        status: 'succeeded',
        createdAt: '',
      ),
    );
  }
}
