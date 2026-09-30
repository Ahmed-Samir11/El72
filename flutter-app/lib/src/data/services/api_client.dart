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
  static Future<void> Function()? onUnauthorized;

  factory ApiClient() {
    return _instance;
  }

  /// Test-only constructor that injects an in-memory [storage] so the 401 flow
  /// can be exercised without the secure-storage platform plugin.
  @visibleForTesting
  factory ApiClient.withStorage(FlutterSecureStorage storage) =>
      ApiClient._internal(storage: storage);

  ApiClient._internal({FlutterSecureStorage? storage})
    : _storage = storage ?? const FlutterSecureStorage() {
    _dio = Dio(
      BaseOptions(
        baseUrl: AppConfig.apiBaseUrl,
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
          final path = error.requestOptions.uri.path;
          final isCredentialEndpoint =
              path.startsWith('/auth/login') ||
              path.startsWith('/auth/register');
          if (error.response?.statusCode == 401 && !isCredentialEndpoint) {
            await _storage.delete(key: 'access_token');
            final callback = onUnauthorized;
            if (callback != null) {
              await callback();
            }
          }
          return handler.next(error);
        },
      ),
    );
  }

  Dio get dio => _dio;
}
