import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/data/services/api_client.dart';

/// In-memory stand-in for [FlutterSecureStorage] so the 401 flow can be
/// exercised without the secure-storage platform plugin.
class _FakeSecureStorage extends FlutterSecureStorage {
  final Map<String, String> _map = {};

  /// When true, [delete] throws — to prove a storage failure never masks the
  /// original 401.
  bool deleteShouldThrow = false;

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
    if (deleteShouldThrow) {
      throw StateError('storage failure');
    }
    _map.remove(key);
  }
}

/// Dio adapter that answers 401 and rewrites the Authorization header to a
/// fixed stale token — simulating a DELAYED 401 response from a request that
/// was sent with an older token (the in-flight request keeps its original
/// headers while a newer token is stored in the meantime).
class _StaleTokenAdapter implements HttpClientAdapter {
  _StaleTokenAdapter(this.staleToken);
  final String staleToken;

  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    options.headers['Authorization'] = 'Bearer $staleToken';
    return ResponseBody.fromBytes(<int>[], 401);
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
    // The callback runs fire-and-forget after the token is deleted; flush the
    // microtask queue so any delayed invocation has landed before asserting.
    await pumpEventQueue();

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

  test('a 401 on the register endpoint does not fire onUnauthorized', () async {
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
      client.dio.post('/auth/register', data: {}),
      throwsA(isA<DioException>()),
    );
    await pumpEventQueue();

    expect(unauthorizedCalled, isFalse);
    expect(await storage.read(key: 'access_token'), 'stale-token');
  });

  group('with a path-prefixed base URL', () {
    // When API_BASE_URL carries a path prefix (e.g. a reverse proxy at
    // /api), the credential-endpoint skip must still match. Note that Dio
    // resolves absolute request paths against the host root (URI resolve
    // semantics), so '/auth/login' keeps its path even with a prefixed base;
    // the matcher handles both that and prefix-retaining relative calls.
    final String baseUrl = 'https://api.example.com/api';

    test(
      'a 401 on /auth/me fires onUnauthorized and clears the token',
      () async {
        final storage = _FakeSecureStorage();
        await storage.write(key: 'access_token', value: 'expired-token');

        var unauthorizedCalled = false;
        ApiClient.onUnauthorized = () async {
          unauthorizedCalled = true;
        };
        addTearDown(() => ApiClient.onUnauthorized = null);

        final client = ApiClient.withStorage(storage, baseUrl: baseUrl);
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
        await pumpEventQueue();

        expect(unauthorizedCalled, isTrue);
        expect(await storage.read(key: 'access_token'), isNull);
      },
    );

    test('a 401 on /auth/login still does not fire onUnauthorized', () async {
      final storage = _FakeSecureStorage();
      await storage.write(key: 'access_token', value: 'stale-token');

      var unauthorizedCalled = false;
      ApiClient.onUnauthorized = () async {
        unauthorizedCalled = true;
      };
      addTearDown(() => ApiClient.onUnauthorized = null);

      final client = ApiClient.withStorage(storage, baseUrl: baseUrl);
      client.dio.httpClientAdapter = _StatusAdapter(401);

      await expectLater(
        client.dio.post('/auth/login', data: {}),
        throwsA(isA<DioException>()),
      );
      await pumpEventQueue();

      expect(unauthorizedCalled, isFalse);
      expect(await storage.read(key: 'access_token'), 'stale-token');
    });
  });

  test(
    'a throwing onUnauthorized handler does not mask the Dio error',
    () async {
      final storage = _FakeSecureStorage();
      await storage.write(key: 'access_token', value: 'expired-token');

      ApiClient.onUnauthorized = () async {
        throw StateError('broken navigation handler');
      };
      addTearDown(() => ApiClient.onUnauthorized = null);

      final client = ApiClient.withStorage(storage);
      client.dio.httpClientAdapter = _StatusAdapter(401);

      // The original 401 must still reach the caller, and the handler failure
      // must be swallowed (not an unhandled async error — flutter_test would
      // fail this test if one escaped into the zone).
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
      await pumpEventQueue();

      // Token deletion (security-critical) still happened.
      expect(await storage.read(key: 'access_token'), isNull);
    },
  );

  test(
    'a delayed 401 from an old request does not clobber a new token',
    () async {
      final storage = _FakeSecureStorage();
      await storage.write(key: 'access_token', value: 'old-token');

      var unauthorizedCalls = 0;
      ApiClient.onUnauthorized = () async {
        unauthorizedCalls++;
      };
      addTearDown(() => ApiClient.onUnauthorized = null);

      final client = ApiClient.withStorage(storage);
      client.dio.httpClientAdapter = _StaleTokenAdapter('old-token');

      // First wave: the 401 was sent with the stored token — clear + navigate.
      await expectLater(
        client.dio.get('/api/prices'),
        throwsA(isA<DioException>()),
      );
      await pumpEventQueue();
      expect(unauthorizedCalls, 1);
      expect(await storage.read(key: 'access_token'), isNull);

      // The user re-authenticates and a new token is stored.
      await storage.write(key: 'access_token', value: 'new-token');

      // A delayed 401 from the older in-flight request arrives.
      await expectLater(
        client.dio.get('/api/prices'),
        throwsA(isA<DioException>()),
      );
      await pumpEventQueue();

      // The new token must survive and the user must not be routed back to
      // login a second time.
      expect(await storage.read(key: 'access_token'), 'new-token');
      expect(unauthorizedCalls, 1);
    },
  );

  test('a token-delete failure does not mask the original 401', () async {
    final storage = _FakeSecureStorage();
    storage.deleteShouldThrow = true;
    await storage.write(key: 'access_token', value: 'expired-token');

    var unauthorizedCalled = false;
    ApiClient.onUnauthorized = () async {
      unauthorizedCalled = true;
    };
    addTearDown(() => ApiClient.onUnauthorized = null);

    final client = ApiClient.withStorage(storage);
    client.dio.httpClientAdapter = _StatusAdapter(401);

    // The original 401 must still reach the caller with its own status even
    // though the secure-storage delete threw.
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
    await pumpEventQueue();

    // The storage failure was swallowed; the callback still fired.
    expect(unauthorizedCalled, isTrue);
  });

  test(
    'a 401 on a non-credential /auth-looking path still signs out',
    () async {
      // /admin/auth/login is NOT this client's login endpoint (root base URL):
      // the anchored credential match must not skip sign-out for it (a bare
      // suffix match would have).
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
        client.dio.get('/admin/auth/login'),
        throwsA(isA<DioException>()),
      );
      await pumpEventQueue();

      expect(unauthorizedCalled, isTrue);
      expect(await storage.read(key: 'access_token'), isNull);
    },
  );
}
