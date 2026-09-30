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

/// Dio adapter that answers every request with [statusCode].
class _StatusAdapter implements HttpClientAdapter {
  _StatusAdapter(this.statusCode);
  final int statusCode;

  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    return ResponseBody.fromBytes(<int>[], statusCode);
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
    client.dio.httpClientAdapter = _StatusAdapter(401);

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

  test(
    'a non-401 error neither clears the token nor fires onUnauthorized',
    () async {
      final storage = _FakeSecureStorage();
      await storage.write(key: 'access_token', value: 'valid-token');

      var unauthorizedCalled = false;
      ApiClient.onUnauthorized = () async {
        unauthorizedCalled = true;
      };
      addTearDown(() => ApiClient.onUnauthorized = null);

      final client = ApiClient.withStorage(storage);
      client.dio.httpClientAdapter = _StatusAdapter(500);

      await expectLater(
        client.dio.get('/auth/me'),
        throwsA(isA<DioException>()),
      );

      expect(unauthorizedCalled, isFalse);
      expect(await storage.read(key: 'access_token'), 'valid-token');
    },
  );

  test('a 401 on the login endpoint does not fire onUnauthorized', () async {
    final storage = _FakeSecureStorage();
    await storage.write(key: 'access_token', value: 'stale-token');

    var unauthorizedCalled = false;
    ApiClient.onUnauthorized = () async {
      unauthorizedCalled = true;
    };
    addTearDown(() => ApiClient.onUnauthorized = null);

    final client = ApiClient.withStorage(storage);
    client.dio.httpClientAdapter = _StatusAdapter(401);

    await expectLater(
      client.dio.post('/auth/login', data: {}),
      throwsA(isA<DioException>()),
    );

    // A login 401 is just bad credentials; the login screen handles it and we
    // must not trigger sign-out (or clobber the token) from the interceptor.
    expect(unauthorizedCalled, isFalse);
    expect(await storage.read(key: 'access_token'), 'stale-token');
  });
}
