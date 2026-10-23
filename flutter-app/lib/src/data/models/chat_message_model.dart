/// Model for a chat message as returned by the chatbot service.
class ChatMessageModel {
  final int id;
  final int sessionId;
  final String role; // 'user' or 'bot'
  final String content;
  final DateTime createdAt;

  const ChatMessageModel({
    required this.id,
    required this.sessionId,
    required this.role,
    required this.content,
    required this.createdAt,
  });

  factory ChatMessageModel.fromJson(Map<String, dynamic> json) {
    return ChatMessageModel(
      id: (json['id'] as num?)?.toInt() ?? 0,
      sessionId: (json['session_id'] as num?)?.toInt() ?? 0,
      role: json['role'] as String? ?? '',
      content: json['content'] as String? ?? '',
      createdAt: _parseDate(json['created_at']),
    );
  }

  static DateTime? _parseDate(Object? value) {
    if (value == null) return null;
    if (value is DateTime) return value;
    return DateTime.tryParse(value.toString());
  }
}

/// Model for a chat session as returned by the chatbot service.
class ChatSessionModel {
  final int id;
  final int userId;
  final DateTime createdAt;
  final DateTime updatedAt;
  final List<ChatMessageModel> messages;

  const ChatSessionModel({
    required this.id,
    required this.userId,
    required this.createdAt,
    required this.updatedAt,
    this.messages = const [],
  });

  factory ChatSessionModel.fromJson(Map<String, dynamic> json) {
    final messagesList = json['messages'] as List<dynamic>? ?? const [];
    return ChatSessionModel(
      id: (json['id'] as num?)?.toInt() ?? 0,
      userId: (json['user_id'] as num?)?.toInt() ?? 0,
      createdAt: _parseDate(json['created_at']),
      updatedAt: _parseDate(json['updated_at']),
      messages:
          messagesList.map((m) => ChatMessageModel.fromJson(m)).toList(),
    );
  }

  static DateTime? _parseDate(Object? value) {
    if (value == null) return null;
    if (value is DateTime) return value;
    return DateTime.tryParse(value.toString());
  }
}

/// Model for a search result returned by the chatbot service.
class SearchResultModel {
  final String storeId;
  final String storeName;
  final String title;
  final double price;
  final String currency;
  final String url;
  final String imageUrl;
  final bool inStock;

  const SearchResultModel({
    required this.storeId,
    required this.storeName,
    required this.title,
    required this.price,
    required this.currency,
    required this.url,
    required this.imageUrl,
    required this.inStock,
  });

  factory SearchResultModel.fromJson(Map<String, dynamic> json) {
    return SearchResultModel(
      storeId: json['store_id'] as String? ?? '',
      storeName: json['store_name'] as String? ?? '',
      title: json['title'] as String? ?? '',
      price: (json['price'] as num?)?.toDouble() ?? 0.0,
      currency: json['currency'] as String? ?? 'EGP',
      url: json['url'] as String? ?? '',
      imageUrl: json['image_url'] as String? ?? '',
      inStock: json['in_stock'] as bool? ?? true,
    );
  }
}

/// Response model for `POST /chatbot/message`.
class ChatResponseModel {
  final String message;
  final int sessionId;
  final List<SearchResultModel> searchResults;

  const ChatResponseModel({
    required this.message,
    required this.sessionId,
    required this.searchResults,
  });

  factory ChatResponseModel.fromJson(Map<String, dynamic> json) {
    final resultsList = json['search_results'] as List<dynamic>? ?? const [];
    return ChatResponseModel(
      message: json['message'] as String? ?? '',
      sessionId: (json['session_id'] as num?)?.toInt() ?? 0,
      searchResults:
          resultsList.map((r) => SearchResultModel.fromJson(r)).toList(),
    );
  }
}
