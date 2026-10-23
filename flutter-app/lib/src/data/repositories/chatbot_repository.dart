import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../config.dart';
import '../models/chat_message_model.dart';

/// Retry a request with exponential backoff for transient failures.
///
/// [maxRetries] is the maximum number of attempts (including the first).
/// Backoff: 1s, 2s, 4s...
Future<T> _retry<T>(Future<T> Function() future, int maxRetries) async {
  int attempt = 0;
  while (attempt < maxRetries) {
    try {
      return await future();
    } catch (e) {
      attempt++;
      if (attempt >= maxRetries) rethrow;
      // Exponential backoff: 1s, 2s, 4s...
      await Future.delayed(const Duration(seconds: 1) << attempt);
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
        receiveTimeout: const Duration(seconds: 30),
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
  /// Retries transient failures up to 3 times with exponential backoff.
  /// Throws [DioException] on HTTP errors after retries are exhausted.
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

    return await _retry(() => _fetchMessage(options), 3);
  }

  /// Internal fetch for sendMessage, extracted for retry.
  Future<ChatResponseModel> _fetchMessage(RequestOptions options) async {
    final response = await _dio.fetch(options);

    if (response.statusCode == 200 && response.data is Map<String, dynamic>) {
      return ChatResponseModel.fromJson(response.data as Map<String, dynamic>);
    }
    throw Exception('Unexpected response from chatbot: ${response.statusCode}');
  }

  /// List all chat sessions for the authenticated user.
  Future<List<ChatSessionModel>> getSessions() async {
    final options = RequestOptions(method: 'GET', path: '/chatbot/sessions');
    await _addAuthHeader(options);

    return await _retry(() => _fetchSessions(options), 3);
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
  /// Uses a dedicated endpoint instead of encoding the action in message text.
  /// Throws [DioException] on HTTP errors (e.g., 402 for insufficient credits).
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

    return await _retry(() => _fetchAddToFeed(options), 3);
  }

  /// Internal fetch for addToFeed, extracted for retry.
  Future<ChatResponseModel> _fetchAddToFeed(RequestOptions options) async {
    final response = await _dio.fetch(options);

    if (response.statusCode == 200 && response.data is Map<String, dynamic>) {
      return ChatResponseModel.fromJson(response.data as Map<String, dynamic>);
    }
    // Re-throw non-2xx responses so the caller can handle 402, etc.
    throw Exception('Unexpected response from chatbot: ${response.statusCode}');
  }

  /// Get a single chat session with all its messages.
  Future<ChatSessionModel> getSession({required String sessionId}) async {
    final options = RequestOptions(
      method: 'GET',
      path: '/chatbot/sessions/$sessionId',
    );
    await _addAuthHeader(options);

    return await _retry(() => _fetchSession(options), 3);
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
