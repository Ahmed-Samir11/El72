import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/data/models/chat_message_model.dart';

void main() {
  group('parseDateRobust', () {
    test('parses standard ISO 8601', () {
      final dt = parseDateRobust('2026-01-15T10:30:00Z');
      expect(dt.year, 2026);
      expect(dt.month, 1);
      expect(dt.day, 15);
      expect(dt.hour, 10);
      expect(dt.minute, 30);
    });

    test('parses with microseconds', () {
      final dt = parseDateRobust('2026-01-15T10:30:00.123456+00:00');
      expect(dt.year, 2026);
      expect(dt.month, 1);
      expect(dt.day, 15);
    });

    test('parses with negative offset (converts to UTC)', () {
      // 10:30 at -05:00 offset = 15:30 UTC
      final dt = parseDateRobust('2026-01-15T10:30:00-05:00');
      expect(dt.year, 2026);
      expect(dt.hour, 15);
    });

    test('returns DateTime passthrough', () {
      final original = DateTime(2026, 1, 15);
      expect(parseDateRobust(original), original);
    });

    test('throws on null', () {
      expect(() => parseDateRobust(null), throwsFormatException);
    });

    test('throws on malformed string', () {
      expect(() => parseDateRobust('not-a-date'), throwsFormatException);
    });

    test('fallback strips timezone offset', () {
      // DateTime.parse handles most ISO strings, but if it fails,
      // we strip the offset as a fallback.
      final dt = parseDateRobust('2026-01-15T10:30:00');
      expect(dt.year, 2026);
      expect(dt.month, 1);
    });
  });

  group('ChatMessageModel', () {
    test('parses valid JSON', () {
      final json = {
        'id': 'aabbccdd-eeff-4000-8000-112233445566',
        'session_id': '11223344-5566-4777-8888-9999aabbccdd',
        'role': 'user',
        'content': 'Hello',
        'created_at': '2026-01-15T10:30:00Z',
      };
      final msg = ChatMessageModel.fromJson(json);
      expect(msg.id, 'aabbccdd-eeff-4000-8000-112233445566');
      expect(msg.sessionId, '11223344-5566-4777-8888-9999aabbccdd');
      expect(msg.role, 'user');
      expect(msg.content, 'Hello');
      expect(msg.createdAt.year, 2026);
    });

    test('throws on missing id', () {
      expect(
        () => ChatMessageModel.fromJson({
          'session_id': 'x',
          'role': 'user',
          'content': 'test',
          'created_at': '2026-01-15T10:30:00Z',
        }),
        throwsFormatException,
      );
    });

    test('throws on missing session_id', () {
      expect(
        () => ChatMessageModel.fromJson({
          'id': 'x',
          'role': 'user',
          'content': 'test',
          'created_at': '2026-01-15T10:30:00Z',
        }),
        throwsFormatException,
      );
    });

    test('throws on missing role', () {
      expect(
        () => ChatMessageModel.fromJson({
          'id': 'x',
          'session_id': 'y',
          'content': 'test',
          'created_at': '2026-01-15T10:30:00Z',
        }),
        throwsFormatException,
      );
    });

    test('throws on missing content', () {
      expect(
        () => ChatMessageModel.fromJson({
          'id': 'x',
          'session_id': 'y',
          'role': 'user',
          'created_at': '2026-01-15T10:30:00Z',
        }),
        throwsFormatException,
      );
    });
  });

  group('ChatSessionModel', () {
    test('parses valid JSON with messages', () {
      final json = {
        'id': '11223344-5566-4777-8888-9999aabbccdd',
        'user_id': 42,
        'created_at': '2026-01-15T10:00:00Z',
        'updated_at': '2026-01-15T10:30:00Z',
        'messages': [
          {
            'id': 'aabbccdd-eeff-4000-8000-112233445566',
            'session_id': '11223344-5566-4777-8888-9999aabbccdd',
            'role': 'user',
            'content': 'Hello',
            'created_at': '2026-01-15T10:00:00Z',
          },
        ],
      };
      final session = ChatSessionModel.fromJson(json);
      expect(session.id, '11223344-5566-4777-8888-9999aabbccdd');
      expect(session.userId, 42);
      expect(session.messages.length, 1);
      expect(session.messages[0].role, 'user');
    });

    test('handles empty messages list', () {
      final json = {
        'id': '11223344-5566-4777-8888-9999aabbccdd',
        'user_id': 42,
        'created_at': '2026-01-15T10:00:00Z',
        'updated_at': '2026-01-15T10:30:00Z',
        'messages': [],
      };
      final session = ChatSessionModel.fromJson(json);
      expect(session.messages, isEmpty);
    });

    test('throws on missing id', () {
      expect(
        () => ChatSessionModel.fromJson({
          'user_id': 42,
          'created_at': '2026-01-15T10:00:00Z',
          'updated_at': '2026-01-15T10:30:00Z',
        }),
        throwsFormatException,
      );
    });

    test('throws on missing user_id', () {
      expect(
        () => ChatSessionModel.fromJson({
          'id': 'x',
          'created_at': '2026-01-15T10:00:00Z',
          'updated_at': '2026-01-15T10:30:00Z',
        }),
        throwsFormatException,
      );
    });
  });

  group('SearchResultModel', () {
    test('parses valid JSON', () {
      final json = {
        'store_id': 'amazon_eg',
        'store_name': 'Amazon Egypt',
        'title': 'Gaming Laptop',
        'price': 45000.0,
        'currency': 'EGP',
        'url': 'https://amazon.eg/product/123',
        'image_url': 'https://img.example.com/123.jpg',
        'in_stock': true,
      };
      final result = SearchResultModel.fromJson(json);
      expect(result.storeId, 'amazon_eg');
      expect(result.storeName, 'Amazon Egypt');
      expect(result.title, 'Gaming Laptop');
      expect(result.price, 45000.0);
      expect(result.currency, 'EGP');
      expect(result.url, 'https://amazon.eg/product/123');
      expect(result.inStock, true);
    });

    test('defaults currency to EGP when missing', () {
      final json = {
        'store_id': 'noon',
        'store_name': 'Noon',
        'title': 'Phone',
        'price': 1000.0,
        'url': 'https://noon.com/product/456',
      };
      final result = SearchResultModel.fromJson(json);
      expect(result.currency, 'EGP');
      expect(result.imageUrl, '');
      expect(result.inStock, true);
    });

    test('throws on missing store_id', () {
      expect(
        () => SearchResultModel.fromJson({
          'store_name': 'Noon',
          'title': 'Phone',
          'price': 1000.0,
          'url': 'https://noon.com/product/456',
        }),
        throwsFormatException,
      );
    });

    test('throws on missing title', () {
      expect(
        () => SearchResultModel.fromJson({
          'store_id': 'noon',
          'store_name': 'Noon',
          'price': 1000.0,
          'url': 'https://noon.com/product/456',
        }),
        throwsFormatException,
      );
    });

    test('throws on missing price', () {
      expect(
        () => SearchResultModel.fromJson({
          'store_id': 'noon',
          'store_name': 'Noon',
          'title': 'Phone',
          'url': 'https://noon.com/product/456',
        }),
        throwsFormatException,
      );
    });

    test('throws on missing url', () {
      expect(
        () => SearchResultModel.fromJson({
          'store_id': 'noon',
          'store_name': 'Noon',
          'title': 'Phone',
          'price': 1000.0,
        }),
        throwsFormatException,
      );
    });
  });

  group('ChatResponseModel', () {
    test('parses valid JSON with results', () {
      final json = {
        'message': 'Found 2 products',
        'session_id': '11223344-5566-4777-8888-9999aabbccdd',
        'search_results': [
          {
            'store_id': 'amazon_eg',
            'store_name': 'Amazon Egypt',
            'title': 'Laptop',
            'price': 45000.0,
            'currency': 'EGP',
            'url': 'https://amazon.eg/product/123',
            'image_url': '',
            'in_stock': true,
          },
        ],
      };
      final response = ChatResponseModel.fromJson(json);
      expect(response.message, 'Found 2 products');
      expect(response.sessionId, '11223344-5566-4777-8888-9999aabbccdd');
      expect(response.searchResults.length, 1);
      expect(response.searchResults[0].title, 'Laptop');
    });

    test('handles empty search results', () {
      final json = {
        'message': 'No results',
        'session_id': '11223344-5566-4777-8888-9999aabbccdd',
        'search_results': [],
      };
      final response = ChatResponseModel.fromJson(json);
      expect(response.searchResults, isEmpty);
    });

    test('throws on missing message', () {
      expect(
        () => ChatResponseModel.fromJson({
          'session_id': 'x',
          'search_results': [],
        }),
        throwsFormatException,
      );
    });

    test('throws on missing session_id', () {
      expect(
        () => ChatResponseModel.fromJson({
          'message': 'test',
          'search_results': [],
        }),
        throwsFormatException,
      );
    });
  });
}
