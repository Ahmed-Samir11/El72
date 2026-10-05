import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/data/config.dart';
import 'package:elhaq_tracker/src/data/models/payment_models.dart';
import 'package:elhaq_tracker/src/data/repositories/payment_repository.dart';
import 'package:elhaq_tracker/src/data/services/api_client.dart';

/// In-memory stand-in for [FlutterSecureStorage] (the auth interceptor
/// reads the token before every request).
class _FakeSecureStorage extends FlutterSecureStorage {
  @override
  Future<String?> read({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async => null;

  @override
  Future<void> write({
    required String key,
    required String? value,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {}

  @override
  Future<void> delete({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {}
}

/// Dio adapter returning a fixed JSON body with [statusCode].
class _JsonAdapter implements HttpClientAdapter {
  _JsonAdapter(this.statusCode, this.body);
  final int statusCode;
  final String body;

  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    return ResponseBody.fromBytes(
      Uint8List.fromList(body.codeUnits),
      statusCode,
      headers: const {
        'content-type': ['application/json'],
      },
    );
  }
}

void main() {
  // Each test starts from live mode; the demo-mode tests flip the flag.
  setUp(() => AppConfig.demoMode = false);

  PaymentRepository repoWith(int statusCode, String body) {
    final client = ApiClient.withStorage(_FakeSecureStorage());
    client.dio.httpClientAdapter = _JsonAdapter(statusCode, body);
    return PaymentRepository(apiClient: client);
  }

  group('startPayment', () {
    test('parses the staging token', () async {
      final repo = repoWith(
        200,
        '{"staging_token": "stg_123", "expires_in": 900}',
      );
      final result = await repo.startPayment();
      expect(result['staging_token'], 'stg_123');
      expect(result['expires_in'], '900');
    });

    test('demo mode falls back on network failure', () async {
      AppConfig.demoMode = true;
      final repo = repoWith(503, 'oops');
      final result = await repo.startPayment();
      expect(result['staging_token'], 'demo_staging');
    });

    test('live mode rethrows on network failure', () async {
      final repo = repoWith(503, 'oops');
      await expectLater(repo.startPayment(), throwsA(isA<DioException>()));
    });
  });

  group('confirmWalletPayment', () {
    test('parses the payment id and status', () async {
      final repo = repoWith(
        200,
        '{"payment_id": "pay_1", "status": "pending_otp"}',
      );
      final result = await repo.confirmWalletPayment(
        stagingToken: 'stg_123',
        walletType: WalletType.vodafoneCash,
        walletNumber: '01012345678',
        packageId: 'standard',
      );
      expect(result.paymentId, 'pay_1');
      expect(result.status, 'pending_otp');
    });

    test('demo mode simulates pending_otp on network failure', () async {
      AppConfig.demoMode = true;
      final repo = repoWith(503, 'oops');
      final result = await repo.confirmWalletPayment(
        stagingToken: 'stg',
        walletType: WalletType.fawry,
        walletNumber: '01112345678',
        packageId: 'premium',
      );
      expect(result.status, 'pending_otp');
      expect(result.paymentId, isNotEmpty);
    });
  });

  group('confirmWalletOtp', () {
    test('parses success', () async {
      final repo = repoWith(200, '{"status": "processing"}');
      final result = await repo.confirmWalletOtp(
        paymentId: 'pay_1',
        otp: '123456',
      );
      expect(result.status, 'processing');
      expect(result.attemptsRemaining, isNull);
    });

    test('parses failure with attempts remaining', () async {
      final repo = repoWith(
        200,
        '{"status": "failed", "attempts_remaining": 2}',
      );
      final result = await repo.confirmWalletOtp(
        paymentId: 'pay_1',
        otp: '000000',
      );
      expect(result.status, 'failed');
      expect(result.attemptsRemaining, 2);
    });

    test('demo mode succeeds for a well-formed otp', () async {
      AppConfig.demoMode = true;
      final repo = repoWith(503, 'oops');
      final ok = await repo.confirmWalletOtp(paymentId: 'p', otp: '123456');
      expect(ok.status, 'succeeded');
      final bad = await repo.confirmWalletOtp(paymentId: 'p', otp: '12ab');
      expect(bad.status, 'failed');
    });
  });

  group('getPaymentStatus', () {
    test('parses the status payload', () async {
      final repo = repoWith(
        200,
        '{"payment_id": "pay_1", "package": "standard", '
        '"amount_egp": 30, "status": "succeeded", "created_at": "now"}',
      );
      final info = await repo.getPaymentStatus('pay_1');
      expect(info.paymentId, 'pay_1');
      expect(info.package, 'standard');
      expect(info.amountEgp, 30);
      expect(info.status, 'succeeded');
    });

    test('live mode rethrows on 404', () async {
      final repo = repoWith(404, '{"detail": "Payment not found"}');
      await expectLater(
        repo.getPaymentStatus('nope'),
        throwsA(isA<DioException>()),
      );
    });
  });

  group('validation helpers', () {
    test('wallet number regex accepts 010/011/012/015 + 8 digits', () {
      expect(walletNumberRegExp.hasMatch('01012345678'), isTrue);
      expect(walletNumberRegExp.hasMatch('01112345678'), isTrue);
      expect(walletNumberRegExp.hasMatch('01212345678'), isTrue);
      expect(walletNumberRegExp.hasMatch('01512345678'), isTrue);
      expect(walletNumberRegExp.hasMatch('01312345678'), isFalse);
      expect(walletNumberRegExp.hasMatch('0101234567'), isFalse);
      expect(walletNumberRegExp.hasMatch('010123456789'), isFalse);
      expect(walletNumberRegExp.hasMatch('+201012345678'), isFalse);
    });

    test('otp regex accepts 4-8 digits only', () {
      expect(otpRegExp.hasMatch('1234'), isTrue);
      expect(otpRegExp.hasMatch('12345678'), isTrue);
      expect(otpRegExp.hasMatch('123456789'), isFalse);
      expect(otpRegExp.hasMatch('12ab'), isFalse);
    });
  });

  group('PaymentStatus', () {
    test('parses backend values', () {
      expect(PaymentStatus.parse('pending_otp'), PaymentStatus.pendingOtp);
      expect(PaymentStatus.parse('processing'), PaymentStatus.processing);
      expect(PaymentStatus.parse('succeeded'), PaymentStatus.succeeded);
      expect(PaymentStatus.parse('failed'), PaymentStatus.failed);
      expect(PaymentStatus.parse('canceled'), PaymentStatus.canceled);
    });

    test('unknown values map to pending (no crash)', () {
      expect(PaymentStatus.parse('brand_new_status'), PaymentStatus.pending);
      expect(PaymentStatus.parse(''), PaymentStatus.pending);
    });

    test('terminal flag', () {
      expect(PaymentStatus.succeeded.isTerminal, isTrue);
      expect(PaymentStatus.failed.isTerminal, isTrue);
      expect(PaymentStatus.canceled.isTerminal, isTrue);
      expect(PaymentStatus.pending.isTerminal, isFalse);
      expect(PaymentStatus.pendingOtp.isTerminal, isFalse);
      expect(PaymentStatus.processing.isTerminal, isFalse);
    });
  });

  group('CreditPackage', () {
    test('mirrors the server pricing', () {
      expect(CreditPackage.standard.id, 'standard');
      expect(CreditPackage.standard.credits, 10);
      expect(CreditPackage.standard.priceEgp, 30);
      expect(CreditPackage.premium.id, 'premium');
      expect(CreditPackage.premium.credits, 30);
      expect(CreditPackage.premium.priceEgp, 90);
    });
  });
}
