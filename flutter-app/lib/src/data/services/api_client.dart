import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../config.dart';

class ApiClient {
  static final ApiClient _instance = ApiClient._internal();
  late final Dio _dio;
  final FlutterSecureStorage _storage;

  /// The base URL this instance's Dio is configured with. Kept so the 401
  /// interceptor can resolve credential paths relative to it (a path-prefixed
  /// base URL, e.g. `https://api.example.com/api`, changes request paths).
  final String _baseUrl;

  /// Fired when the API answers 401 (expired/invalid token). The app wires
  /// this to route back to the login screen. There is no refresh endpoint on
  /// the backend, so clearing the token and re-authenticating is the only path.
  ///
  /// Contract for implementations: set it before any API call, make it
  /// resilient (the interceptor runs it fire-and-forget after the token is
  /// cleared, so navigation errors must be caught inside), and deduplicate
  /// in-flight navigations so a burst of 401s routes to login exactly once.
  /// Tests must reset it to null in teardown.
  static Future<void> Function()? onUnauthorized;

  factory ApiClient() {
    return _instance;
  }

  /// Test-only constructor that injects an in-memory [storage] (and, with
  /// [baseUrl], a custom base URL — e.g. one with a path prefix) so the 401
  /// flow can be exercised without the secure-storage platform plugin.
  @visibleForTesting
  factory ApiClient.withStorage(
    FlutterSecureStorage storage, {
    String? baseUrl,
  }) => ApiClient._internal(storage: storage, baseUrl: baseUrl);

  ApiClient._internal({FlutterSecureStorage? storage, String? baseUrl})
    : _storage = storage ?? const FlutterSecureStorage(),
      _baseUrl = baseUrl ?? AppConfig.apiBaseUrl {
    _dio = Dio(
      BaseOptions(
        baseUrl: baseUrl ?? AppConfig.apiBaseUrl,
        connectTimeout: const Duration(seconds: 30), // Increased for scraper
        receiveTimeout: const Duration(seconds: 30), // Increased for scraper
      ),
    );

    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          final token = await _storage.read(key: 'access_token');
          if (token != null) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          return handler.next(options);
        },
        onError: (error, handler) async {
          // 401 means the stored token is expired or invalid. Clear it and
          // notify the app so it can send the user back to login. `error` is
          // already a DioException in this callback.
          final status = error.response?.statusCode;
          if (status != 401) {
            handler.next(error);
            return;
          }
          // Skip the credential endpoints themselves: a 401 on /auth/login or
          // /auth/register just means bad credentials, which those screens
          // handle directly — firing sign-out there would be a no-op at best
          // and could clobber a freshly-entered login. (Other /auth/* calls,
          // e.g. /auth/me, DO mean an expired token and must sign out.)
          if (_isCredentialPath(error.requestOptions.path)) {
            handler.next(error);
            return;
          }
          // Token-identity check: only act if the token this request was sent
          // with is STILL the stored token. When a token expires, every
          // in-flight request eventually 401s; if the user re-authenticates
          // before a delayed 401 arrives, that delayed 401 must not delete
          // the freshly issued token or yank the user back to login. (The
          // navigation handler's in-flight dedup does not cover this — the
          // second navigation would only start after the first completed.)
          final sentToken = _tokenFromOptions(error.requestOptions);
          // A storage failure must not mask the original 401: if the read
          // fails, assume the identity matches (proceed to clear + navigate —
          // the 401 is real and re-authentication is the safe path).
          String? currentToken = sentToken;
          try {
            currentToken = await _storage.read(key: 'access_token');
          } catch (e) {
            debugPrint('ApiClient: failed to read stored token: $e');
          }
          // No token was sent and none is stored: there is no session to
          // sign out (e.g. a 401 from a public/startup request) — don't
          // route the user to login or reset form state.
          if (sentToken == null && currentToken == null) {
            handler.next(error);
            return;
          }
          if (currentToken != sentToken) {
            handler.next(error);
            return;
          }
          // The security-critical part (token deletion) is awaited; a storage
          // failure must not mask the original 401.
          try {
            await _storage.delete(key: 'access_token');
          } catch (e) {
            debugPrint('ApiClient: failed to clear stored token: $e');
          }
          // The navigation callback is then fire-and-forget so a slow or
          // throwing handler can never delay the Dio error reaching the
          // caller or crash the request pipeline.
          final callback = onUnauthorized;
          if (callback != null) {
            unawaited(() async {
              try {
                await callback();
              } catch (e) {
                // A broken navigation handler must not turn a 401 into
                // an unhandled async crash.
                debugPrint('onUnauthorized handler failed: $e');
              }
            }());
          }
          handler.next(error);
        },
      ),
    );
  }

  /// The bearer token [options] were sent with, or null if the request was
  /// unauthenticated. Dio headers can hold `List<String>` values; the last
  /// entry wins (mirrors HTTP header folding).
  String? _tokenFromOptions(RequestOptions options) {
    final header = options.headers['Authorization'];
    String? value;
    if (header is String) {
      value = header;
    } else if (header is List && header.isNotEmpty) {
      value = header.last.toString();
    }
    if (value != null && value.startsWith('Bearer ')) {
      return value.substring('Bearer '.length);
    }
    return null;
  }

  /// Whether [path] is this client's auth login/register endpoint.
  ///
  /// Dio resolves absolute request paths against the host root (URI resolve
  /// semantics drop the base URL's path component), so a call to
  /// `'/auth/login'` keeps the path `'/auth/login'` even with a path-prefixed
  /// base URL; relative calls (`'auth/login'`) keep the prefix
  /// (`'/api/auth/login'`). Both forms are matched by EXACT comparison only
  /// — which also avoids false positives such as `'/admin/auth/login'` and
  /// `'/admin/api/auth/login'` that a bare suffix match would hit.
  bool _isCredentialPath(String path) {
    const endpoints = ['/auth/login', '/auth/register'];
    String basePath = '';
    try {
      basePath = Uri.parse(_baseUrl).path;
    } catch (_) {
      return false; // malformed base URL: never treat as credential
    }
    if (basePath.endsWith('/')) {
      basePath = basePath.substring(0, basePath.length - 1);
    }
    for (final endpoint in endpoints) {
      // Exact matches only (no bare suffix): '/auth/login' for root bases
      // (avoids '/admin/auth/login'), or the base path prepended for
      // relative calls against a path-prefixed base ('/api/auth/login' —
      // which must not match '/admin/api/auth/login').
      if (path == endpoint) return true;
      if (basePath.isNotEmpty && path == '$basePath$endpoint') {
        return true;
      }
    }
    return false;
  }

  Dio get dio => _dio;
}
