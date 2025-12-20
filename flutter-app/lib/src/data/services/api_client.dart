import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class ApiClient {
  static final ApiClient _instance = ApiClient._internal();
  late final Dio _dio;
  final FlutterSecureStorage _storage = const FlutterSecureStorage();

  factory ApiClient() {
    return _instance;
  }

  ApiClient._internal() {
    _dio = Dio(
      BaseOptions(
        // Use your computer's IP address for physical device
        baseUrl: 'http://192.168.1.106:8000',
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
        onError: (error, handler) {
          // Handle errors globally if needed
          return handler.next(error);
        },
      ),
    );
  }

  Dio get dio => _dio;
}
