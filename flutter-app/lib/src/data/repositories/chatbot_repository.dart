import 'package:dio/dio.dart';
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
class ChatbotRepository {
  /// The Dio client configured for the chatbot base URL.
  final Dio _dio;

  ChatbotRepository({Dio? dio})
    : _dio = dio ?? Dio(BaseOptions(
        baseUrl: AppConfig.chatbotBaseUrl,
        connectTimeout: const Duration(seconds: 30),
        receiveTimeout: const Duration(seconds: 30),
      ));

  /// Send a message to the chatbot and get the response with search results.
  ///
  /// Throws [DioException] on HTTP errors.
  Future<ChatResponseModel> sendMessage({
    required int sessionId,
    required int userId,
    required String message,
  }) async {
    final response = await _dio.post(
      '/chatbot/message',
      data: {
        'session_id': sessionId,
        'user_id': userId,
        'message': message,
      },
    );

    if (response.statusCode == 200 && response.data is Map<String, dynamic>) {
      return ChatResponseModel.fromJson(response.data as Map<String, dynamic>);
    }
    throw Exception('Unexpected response from chatbot: ${response.statusCode}');
  }

  /// List all chat sessions for a user.
  Future<List<ChatSessionModel>> getSessions({required int userId}) async {
    final response = await _dio.get(
      '/chatbot/sessions',
      queryParameters: {'user_id': userId},
    );

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
    final response = await _dio.get('/chatbot/sessions/$sessionId');

    if (response.statusCode == 200 && response.data is Map<String, dynamic>) {
      return ChatSessionModel.fromJson(response.data as Map<String, dynamic>);
    }
    throw Exception('Unexpected response from chatbot: ${response.statusCode}');
  }
}
