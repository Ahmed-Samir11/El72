import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../config.dart';
import '../models/chat_message_model.dart';

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
  /// Throws [DioException] on HTTP errors.
  Future<ChatResponseModel> sendMessage({
    required int sessionId,
    required String message,
  }) async {
    final options = RequestOptions(
      method: 'POST',
      path: '/chatbot/message',
      data: {
        'session_id': sessionId.toString(),
        'message': message,
      },
    );
    await _addAuthHeader(options);

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

    final response = await _dio.fetch(options);

    if (response.statusCode == 200 && response.data is List) {
      return (response.data as List)
          .whereType<Map<String, dynamic>>()
          .map(ChatSessionModel.fromJson)
          .toList();
    }
    throw Exception('Unexpected response from chatbot: ${response.statusCode}');
  }

  /// Get a single chat session with all its messages.
  Future<ChatSessionModel> getSession({required int sessionId}) async {
    final options = RequestOptions(
      method: 'GET',
      path: '/chatbot/sessions/$sessionId',
    );
    await _addAuthHeader(options);

    final response = await _dio.fetch(options);

    if (response.statusCode == 200 && response.data is Map<String, dynamic>) {
      return ChatSessionModel.fromJson(response.data as Map<String, dynamic>);
    }
    throw Exception('Unexpected response from chatbot: ${response.statusCode}');
  }
}
