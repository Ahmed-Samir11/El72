import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/data/config.dart';
import 'package:elhaq_tracker/src/data/models/credit_balance_model.dart';
import 'package:elhaq_tracker/src/data/repositories/credits_repository.dart';
import 'package:elhaq_tracker/src/data/services/api_client.dart';

/// In-memory stand-in for [FlutterSecureStorage] so no platform channel is
/// touched (the auth interceptor reads the token before every request).
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
  // Each test starts from live mode; the demo-mode test flips the flag.
  setUp(() => AppConfig.demoMode = false);

  test('parses balance and tier from the API payload', () async {
    final client = ApiClient.withStorage(_FakeSecureStorage());
    client.dio.httpClientAdapter = _JsonAdapter(
      200,
      '{"balance": 7, "tier": "standard"}',
    );
    final repo = CreditsRepository(apiClient: client);

    final balance = await repo.getBalance();
    expect(balance.balance, 7);
    expect(balance.tier, 'standard');
  });

  test('demo mode falls back to demo balance on network failure', () async {
    AppConfig.demoMode = true;
    final client = ApiClient.withStorage(_FakeSecureStorage());
    client.dio.httpClientAdapter = _JsonAdapter(503, 'oops');
    final repo = CreditsRepository(apiClient: client);

    final balance = await repo.getBalance();
    expect(balance.balance, 3);
    expect(balance.tier, 'free');
  });

  test('live mode rethrows on network failure', () async {
    final client = ApiClient.withStorage(_FakeSecureStorage());
    client.dio.httpClientAdapter = _JsonAdapter(503, 'oops');
    final repo = CreditsRepository(apiClient: client);

    await expectLater(repo.getBalance(), throwsA(isA<DioException>()));
  });

  test('CreditBalance.fromJson tolerates missing fields', () {
    expect(CreditBalance.fromJson({}).balance, 0);
    expect(CreditBalance.fromJson({}).tier, 'free');
    expect(CreditBalance.fromJson({'balance': 2.0}).balance, 2);
  });
}
