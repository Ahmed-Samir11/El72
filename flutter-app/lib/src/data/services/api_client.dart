import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../config.dart';

class ApiClient {
  static final ApiClient _instance = ApiClient._internal();
  late final Dio _dio;
  final FlutterSecureStorage _storage;

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
    : _storage = storage ?? const FlutterSecureStorage() {
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
          //
          // Skip the credential endpoints themselves: a 401 on /auth/login or
          // /auth/register just means bad credentials, which those screens
          // handle directly — firing sign-out there would be a no-op at best
          // and could clobber a freshly-entered login. (Other /auth/* calls,
          // e.g. /auth/me, DO mean an expired token and must sign out.)
          //
          // Suffix match on the absolute URI path: when the base URL carries
          // a path prefix (e.g. https://api.example.com/api), a login request
          // has the path /api/auth/login — startsWith('/auth/...') would miss
          // it and a bad login would wrongly trigger sign-out. The leading
          // '/' in the suffix also prevents false matches such as
          // /x-auth/login.
          final path = error.requestOptions.uri.path;
          final isCredentialEndpoint =
              path.endsWith('/auth/login') || path.endsWith('/auth/register');
          if (error.response?.statusCode == 401 && !isCredentialEndpoint) {
            // The security-critical part (token deletion) is awaited; the
            // navigation callback is then fire-and-forget so a slow or
            // throwing handler can never delay the Dio error reaching the
            // caller or crash the request pipeline.
            await _storage.delete(key: 'access_token');
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
          }
          return handler.next(error);
        },
      ),
    );
  }

  Dio get dio => _dio;
}
