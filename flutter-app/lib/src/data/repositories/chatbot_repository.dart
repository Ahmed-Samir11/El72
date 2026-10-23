import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../config.dart';
import '../models/chat_message_model.dart';

/// Custom exception for HTTP 402 (insufficient credits) responses.
///
/// The chatbot service returns 402 when the user has no remaining credits
/// to create a tracker. The UI should surface this as an upgrade prompt.
class InsufficientCreditsException implements Exception {
  final String message;

  const InsufficientCreditsException(this.message);

  @override
  String toString() => 'InsufficientCreditsException: $message';
}

/// Custom exception for HTTP 401 (unauthorized) responses.
///
/// The chatbot service returns 401 when the JWT token is missing, expired,
/// or invalid. The UI should prompt the user to re-authenticate.
class UnauthorizedException implements Exception {
  final String message;

  const UnauthorizedException(this.message);

  @override
  String toString() => 'UnauthorizedException: $message';
}

/// Retry a request with exponential backoff for transient failures.
///
/// Only used for idempotent GET requests. POST requests are never retried
/// to avoid creating duplicate side effects (e.g. duplicate trackers).
/// [maxRetries] is the maximum number of attempts (including the first).
/// Backoff: 500ms, 1s, 2s...
Future<T> _retryGet<T>(Future<T> Function() future, int maxRetries) async {
  int attempt = 0;
  while (attempt < maxRetries) {
    try {
      return await future();
    } on DioException catch (e) {
      // Only retry on transient network errors, not HTTP error responses.
      if (e.type == DioExceptionType.connectionTimeout ||
          e.type == DioExceptionType.connectionError ||
          e.type == DioExceptionType.receiveTimeout ||
          e.type == DioExceptionType.sendTimeout) {
        attempt++;
        if (attempt >= maxRetries) rethrow;
        await Future.delayed(Duration(milliseconds: 500) * (1 << attempt));
        continue;
      }
      rethrow;
    }
  }
  // Unreachable but satisfies the analyzer.
  throw StateError('Retry loop exited without result');
}

/// Data source for the chatbot service (`services/chatbot`).
///
/// The chatbot is a standalone FastAPI service that:
/// - Accepts natural-language product searches (e.g. "gaming laptop under 50000 EGP")
/// - Returns product results across all supported stores
/// - Lets users add search results to their tracking feed via the API service
///
/// Communication with the chatbot is server-to-server (Dio), just like the
/// main API client. The chatbot itself calls `/tracked-items/from-url` on the
/// API service to create trackers, so credit checking happens there.
///
/// All requests include the stored JWT access token as a Bearer header so the
/// chatbot can authenticate the caller and resolve the user_id from the token
/// (the token's `sub` claim is the user's phone number).
class ChatbotRepository {
  /// The Dio client configured for the chatbot base URL.
  final Dio _dio;

  /// Secure storage for the JWT access token.
  final FlutterSecureStorage _storage;

  ChatbotRepository({
    Dio? dio,
    FlutterSecureStorage? storage,
  })
    : _dio = dio ?? Dio(BaseOptions(
        baseUrl: AppConfig.chatbotBaseUrl,
        connectTimeout: const Duration(seconds: 30),
        receiveTimeout: const Duration(seconds: 120),
      )),
      _storage = storage ?? const FlutterSecureStorage();

  /// Read the stored JWT access token.
  Future<String?> _getToken() async {
    return await _storage.read(key: 'access_token');
  }

  /// Add the Bearer token to request options if one is stored.
  Future<void> _addAuthHeader(RequestOptions options) async {
    final token = await _getToken();
    if (token != null) {
      options.headers['Authorization'] = 'Bearer $token';
    }
  }

  /// Send a message to the chatbot and get the response with search results.
  ///
  /// POST is not retried (non-idempotent). Throws [UnauthorizedException] on 401,
  /// [InsufficientCreditsException] on 402, [DioException] on other errors.
  Future<ChatResponseModel> sendMessage({
    required String sessionId,
    required String message,
  }) async {
    final options = RequestOptions(
      method: 'POST',
      path: '/chatbot/message',
      data: {
        'session_id': sessionId,
        'message': message,
      },
    );
    await _addAuthHeader(options);

    try {
      final response = await _dio.fetch(options);

      if (response.statusCode == 200 && response.data is Map<String, dynamic>) {
        return ChatResponseModel.fromJson(response.data as Map<String, dynamic>);
      }
      throw Exception('Unexpected response from chatbot: ${response.statusCode}');
    } on DioException catch (e) {
      _handleHttpError(e);
      rethrow; // Unreachable; _handleHttpError always throws.
    }
  }

  /// Convert Dio HTTP errors to domain exceptions.
  ///
  /// 401 → [UnauthorizedException] (token expired/invalid)
  /// 402 → [InsufficientCreditsException] (no credits)
  /// Other → rethrow the original [DioException].
  Never _handleHttpError(DioException e) {
    final status = e.response?.statusCode;
    if (status == 401) {
      throw UnauthorizedException(
        'Your session has expired. Please log in again.',
      );
    }
    if (status == 402) {
      throw InsufficientCreditsException(
        'You have run out of credits. Purchase a plan to create trackers.',
      );
    }
    throw e;
  }

  /// List all chat sessions for the authenticated user.
  ///
  /// GET is retried up to 3 times on transient network failures.
  Future<List<ChatSessionModel>> getSessions() async {
    final options = RequestOptions(method: 'GET', path: '/chatbot/sessions');
    await _addAuthHeader(options);

    return await _retryGet(() => _fetchSessions(options), 3);
  }

  /// Internal fetch for getSessions, extracted for retry.
  Future<List<ChatSessionModel>> _fetchSessions(RequestOptions options) async {
    final response = await _dio.fetch(options);

    if (response.statusCode == 200 && response.data is List) {
      return (response.data as List)
          .whereType<Map<String, dynamic>>()
          .map(ChatSessionModel.fromJson)
          .toList();
    }
    throw Exception('Unexpected response from chatbot: ${response.statusCode}');
  }

  /// Add a search result to the user's tracking feed.
  ///
  /// POST is not retried (non-idempotent — retrying would create duplicate
  /// trackers). Throws [UnauthorizedException] on 401,
  /// [InsufficientCreditsException] on 402, [DioException] on other errors.
  Future<ChatResponseModel> addToFeed({
    required String sessionId,
    String? productUrl,
    double? targetPrice,
  }) async {
    final options = RequestOptions(
      method: 'POST',
      path: '/chatbot/add-to-feed',
      data: {
        'session_id': sessionId,
        ...(productUrl != null ? {'product_url': productUrl} : {}),
        ...(targetPrice != null ? {'target_price': targetPrice} : {}),
      },
    );
    await _addAuthHeader(options);

    try {
      final response = await _dio.fetch(options);

      if (response.statusCode == 200 && response.data is Map<String, dynamic>) {
        return ChatResponseModel.fromJson(response.data as Map<String, dynamic>);
      }
      throw Exception('Unexpected response from chatbot: ${response.statusCode}');
    } on DioException catch (e) {
      _handleHttpError(e);
      rethrow; // Unreachable; _handleHttpError always throws.
    }
  }

  /// Get a single chat session with all its messages.
  ///
  /// GET is retried up to 3 times on transient network failures.
  Future<ChatSessionModel> getSession({required String sessionId}) async {
    final options = RequestOptions(
      method: 'GET',
      path: '/chatbot/sessions/$sessionId',
    );
    await _addAuthHeader(options);

    return await _retryGet(() => _fetchSession(options), 3);
  }

  /// Internal fetch for getSession, extracted for retry.
  Future<ChatSessionModel> _fetchSession(RequestOptions options) async {
    final response = await _dio.fetch(options);

    if (response.statusCode == 200 && response.data is Map<String, dynamic>) {
      return ChatSessionModel.fromJson(response.data as Map<String, dynamic>);
    }
    throw Exception('Unexpected response from chatbot: ${response.statusCode}');
  }
}
