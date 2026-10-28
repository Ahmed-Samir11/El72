import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../core/url_guard.dart';
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
      // Anything else — including the ArgumentError the session-id path guard
      // raises — propagates on the first attempt: a bad id is not a condition
      // that a retry can fix.
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

  ChatbotRepository({Dio? dio, FlutterSecureStorage? storage})
    : _dio =
          dio ??
          Dio(
            BaseOptions(
              baseUrl: AppConfig.chatbotBaseUrl,
              connectTimeout: const Duration(seconds: 30),
              receiveTimeout: const Duration(seconds: 120),
            ),
          ),
      _storage = storage ?? const FlutterSecureStorage();

  /// Read the stored JWT access token.
  Future<String?> _getToken() async {
    return await _storage.read(key: 'access_token');
  }

  /// Rejects a session id that is not a UUID, and returns it unchanged.
  //
  /// The app generates a UUID, but the value is overwritten with whatever the
  /// chatbot echoes back, so this is checked wherever one leaves the app:
  //
  ///  * interpolated into `/chatbot/sessions/<id>`, where an id carrying `/`,
  ///    `?`, `#` or `..` would silently move the request to another route of
  ///    the proxied service instead of staying an identifier;
  ///  * in a JSON body, where it cannot affect routing but a non-UUID means the
  ///    conversation state was poisoned upstream — better a local ArgumentError
  ///    than a confusing 4xx from the chatbot.
  static final _uuidPattern = RegExp(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    caseSensitive: false,
  );

  /// Whether a value has the shape the chatbot uses for session ids.
  static bool isSessionId(String sessionId) => _uuidPattern.hasMatch(sessionId);

  static String _requireSessionId(String sessionId) {
    if (_uuidPattern.hasMatch(sessionId)) return sessionId;
    throw ArgumentError.value(
      sessionId,
      'sessionId',
      'must be a UUID before it leaves the app',
    );
  }

  /// Reject a scraped product url that the app may not forward at all.
  ///
  /// The value is copied straight out of a third-party page, and it is
  /// forwarded to the tracker service, which is the component that will go and
  /// fetch it. A relative url would be resolved against the API base by the
  /// service, a non-web scheme (`file:`, `data:`, some app's custom scheme) is
  /// not something that can ever be priced, and a link longer than
  /// [maxResultUrlLength] is payload rather than an address — the model parser
  /// already refuses such a link on the way in, and this path must not be able
  /// to smuggle one through.
  ///
  /// [SearchResultCard] already disables its button on the same rule, but
  /// `addToFeed` is public API, so the repository refuses it rather than trusting
  /// its caller.
  //
  ///  Note what this is *not*: a client-side check is defence in depth, bypassed
  ///  by anyone who builds their own request. The authoritative fetch policy is
  ///  `services/common/url_policy.py`, enforced by the API service before it visits
  ///  a url. Both sides call the shared [isHttpUrl] helper so the UI promise and
  ///  this check cannot drift apart from each other.
  static String _requireHttpUrl(String productUrl) {
    if (!isHttpUrl(productUrl) || productUrl.length > maxResultUrlLength) {
      throw ArgumentError.value(
        productUrl,
        'productUrl',
        'must be an absolute http/https url no longer than '
            '$maxResultUrlLength characters',
      );
    }
    return productUrl;
  }

  /// Request [Options] carrying the Bearer token, if one is stored.
  ///
  /// Requests go through `_dio.get`/`_dio.post` with these options so the
  /// client's `baseUrl` applies; a bare `RequestOptions` passed to
  /// `_dio.fetch` has no host.
  Future<Options> _authOptions() async {
    // Trimmed, not passed through: a token read back from secure storage with
    // stray whitespace around it would send `Authorization: Bearer  <jwt> `, which
    // the service reads as a malformed token rather than as "unauthenticated".
    final raw = await _getToken();
    final token = raw?.trim();
    // An empty string would send `Authorization: Bearer `, which the service
    // reads as a malformed token rather than as "unauthenticated".
    return Options(
      headers: {
        if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
      },
    );
  }

  /// Refuse a message longer than the app's own turn bound.
  //
  /// The chat page cuts what it sends to [maxChatContentLength] before building
  /// the request, but `sendMessage` is public API, so the bound is enforced here
  /// as well rather than trusting the caller: an oversized payload would be
  /// billed by the service and could never be read by the model behind it. A
  /// rejection rather than a silent cut — a caller that hands over more than one
  //  turn is holding text the app should not have kept.
  static String _requireMessage(String message) {
    if (message.length > maxChatContentLength) {
      throw ArgumentError.value(
        message.length,
        'message',
        'must not exceed $maxChatContentLength characters',
      );
    }
    return message;
  }

  /// Send a message to the chatbot and get the response with search results.
  ///
  /// POST is not retried (non-idempotent). Throws [UnauthorizedException] on 401,
  /// [InsufficientCreditsException] on 402, [DioException] on other errors.
  Future<ChatResponseModel> sendMessage({
    required String sessionId,
    required String message,
  }) async {
    _requireSessionId(sessionId);
    _requireMessage(message);
    final options = await _authOptions();

    try {
      final response = await _dio.post(
        '/chatbot/message',
        data: {'session_id': sessionId, 'message': message},
        options: options,
      );

      if (response.statusCode == 200 && response.data is Map<String, dynamic>) {
        return ChatResponseModel.fromJson(
          response.data as Map<String, dynamic>,
        );
      }
      throw Exception(
        'Unexpected response from chatbot: ${response.statusCode}',
      );
    } on DioException catch (e) {
      // _handleHttpError is a Never-returning function: it always throws
      // (UnauthorizedException, InsufficientCreditsException, or rethrows).
      _handleHttpError(e);
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
    final options = await _authOptions();

    return await _retryGet(() => _fetchSessions(options), 3);
  }

  /// Internal fetch for getSessions, extracted for retry.
  Future<List<ChatSessionModel>> _fetchSessions(Options options) async {
    final response = await _dio.get('/chatbot/sessions', options: options);

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
    _requireSessionId(sessionId);
    if (productUrl != null) _requireHttpUrl(productUrl);
    final options = await _authOptions();

    try {
      final response = await _dio.post(
        '/chatbot/add-to-feed',
        data: {
          'session_id': sessionId,
          ...(productUrl != null ? {'product_url': productUrl} : {}),
          ...(targetPrice != null ? {'target_price': targetPrice} : {}),
        },
        options: options,
      );

      if (response.statusCode == 200 && response.data is Map<String, dynamic>) {
        return ChatResponseModel.fromJson(
          response.data as Map<String, dynamic>,
        );
      }
      throw Exception(
        'Unexpected response from chatbot: ${response.statusCode}',
      );
    } on DioException catch (e) {
      _handleHttpError(e);
    }
  }

  /// Get a single chat session with all its messages.
  ///
  /// GET is retried up to 3 times on transient network failures.
  Future<ChatSessionModel> getSession({required String sessionId}) async {
    final options = await _authOptions();

    return await _retryGet(() => _fetchSession(sessionId, options), 3);
  }

  /// Internal fetch for getSession, extracted for retry.
  Future<ChatSessionModel> _fetchSession(
    String sessionId,
    Options options,
  ) async {
    final response = await _dio.get(
      '/chatbot/sessions/${_requireSessionId(sessionId)}',
      options: options,
    );

    if (response.statusCode == 200 && response.data is Map<String, dynamic>) {
      return ChatSessionModel.fromJson(response.data as Map<String, dynamic>);
    }
    throw Exception('Unexpected response from chatbot: ${response.statusCode}');
  }
}
