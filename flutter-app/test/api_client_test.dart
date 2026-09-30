import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/data/services/api_client.dart';

/// In-memory stand-in for [FlutterSecureStorage] so the 401 flow can be
/// exercised without the secure-storage platform plugin.
class _FakeSecureStorage extends FlutterSecureStorage {
  final Map<String, String> _map = {};

  @override
  Future<String?> read({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async => _map[key];

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
  }) async {
    if (value == null) {
      _map.remove(key);
    } else {
      _map[key] = value;
    }
  }

  @override
  Future<void> delete({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    _map.remove(key);
  }
}

/// Dio adapter that answers every request with a 401, simulating an expired
/// token on the server.
class _UnauthorizedAdapter implements HttpClientAdapter {
  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    return ResponseBody.fromBytes(<int>[], 401);
  }
}

void main() {
  test('a 401 clears the stored token and fires onUnauthorized', () async {
    final storage = _FakeSecureStorage();
    await storage.write(key: 'access_token', value: 'expired-token');

    var unauthorizedCalled = false;
    ApiClient.onUnauthorized = () async {
      unauthorizedCalled = true;
    };
    addTearDown(() => ApiClient.onUnauthorized = null);

    final client = ApiClient.withStorage(storage);
    client.dio.httpClientAdapter = _UnauthorizedAdapter();

    await expectLater(
      client.dio.get('/auth/me'),
      throwsA(
        isA<DioException>().having(
          (e) => e.response?.statusCode,
          'statusCode',
          401,
        ),
      ),
    );

    expect(unauthorizedCalled, isTrue);
    expect(await storage.read(key: 'access_token'), isNull);
  });
}
