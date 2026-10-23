import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../lib/src/data/models/chat_message_model.dart';
import '../../lib/src/data/repositories/chatbot_repository.dart';

/// In-memory stand-in for [FlutterSecureStorage] for tests.
class _FakeSecureStorage extends FlutterSecureStorage {
  final Map<String, String> _map = {};

  @override
  Future<String?> read({required String key, ...}) async => _map[key];

  @override
  Future<void> write({required String key, required String? value, ...}) async {
    if (value == null) {
      _map.remove(key);
    } else {
      _map[key] = value;
    }
  }

  @override
  Future<void> delete({required String key, ...}) async {
    _map.remove(key);
  }
}

/// A Dio adapter that captures requests and returns canned responses.
class _CapturedAdapter extends HttpClientAdapter {
  final Map<String, dynamic> _responses = {};
  final List<Map<String, dynamic>> _captured = [];

  void setResponse(String path, dynamic response, int statusCode: 200) {
    _responses[path] = {'body': response, 'statusCode': statusCode};
  }

  @override
  Future<Response> fetch(Request request) async {
    _captured.add(
      {
        'method': request.method,
        'path': request.path,
        'headers': Map<String, String>.from(request.headers),
        'data': request.data,
      },
    );
    final entry = _responses[request.path];
    if (entry == null) {
      throw DioException(
        requestOptions: request,
        error: 'No mock response for ${request.path}',
      );
    }
    return Response(
      requestOptions: request,
      statusCode: entry['statusCode'],
      data: entry['body'],
    );
  }
}

void main() {
  group('ChatbotRepository', () {
    late Dio dio;
    late _FakeSecureStorage storage;
    late ChatbotRepository repository;
    late _CapturedAdapter adapter;

    setUp(() {
      dio = Dio();
      storage = _FakeSecureStorage();
      adapter = _CapturedAdapter();
      dio.httpClientAdapter = adapter;
      repository = ChatbotRepository(dio: dio, storage: storage);
    });

    group('sendMessage', () {
      test('includes Bearer token in Authorization header', () async {
        // Arrange
        await storage.write(key: 'access_token', value: 'test-token-123');
        adapter.setResponse(
          '/chatbot/message',
          {
            'message': 'Hello!',
            'session_id': 'abc-123',
            'search_results': [],
          },
        );

        // Act
        await repository.sendMessage(sessionId: 'abc-123', message: 'hello');

        // Assert
        final captured = adapter._captured.last;
        expect(
          captured['headers']['Authorization'],
          'Bearer test-token-123',
        );
      });

      test('sends session_id and message in request body', () async {
        // Arrange
        await storage.write(key: 'access_token', value: 'token');
        adapter.setResponse(
          '/chatbot/message',
          {
            'message': 'Hello!',
            'session_id': 'abc-123',
            'search_results': [],
          },
        );

        // Act
        await repository.sendMessage(sessionId: 'abc-123', message: 'test query');

        // Assert
        final captured = adapter._captured.last;
        expect(captured['data']['session_id'], 'abc-123');
        expect(captured['data']['message'], 'test query');
      });

      test('returns parsed ChatResponseModel', () async {
        // Arrange
        await storage.write(key: 'access_token', value: 'token');
        adapter.setResponse(
          '/chatbot/message',
          {
            'message': 'Found 2 products.',
            'session_id': 'abc-123',
            'search_results': [
              {
                'store_id': 'amazon_eg',
                'store_name': 'Amazon Egypt',
                'title': 'Gaming Laptop',
                'price': 55000.0,
                'currency': 'EGP',
                'url': 'https://example.com/laptop',
                'image_url': 'https://example.com/image.jpg',
                'in_stock': true,
              },
            ],
          },
        );

        // Act
        final response = await repository.sendMessage(
          sessionId: 'abc-123',
          message: 'gaming laptop',
        );

        // Assert
        expect(response.message, 'Found 2 products.');
        expect(response.sessionId, 'abc-123');
        expect(response.searchResults.length, 2);
        expect(response.searchResults[0].title, 'Gaming Laptop');
        expect(response.searchResults[0].price, 55000.0);
      });

      test('throws on non-200 response', () async {
        // Arrange
        await storage.write(key: 'access_token', value: 'token');
        adapter.setResponse(
          '/chatbot/message',
          {},
          statusCode: 500,
        );

        // Act & Assert
        expect(
          () => repository.sendMessage(sessionId: 'abc-123', message: 'test'),
          throwsA(isA<DioException>),
        );
      });
    });

    group('getSessions', () {
      test('includes Bearer token in Authorization header', () async {
        // Arrange
        await storage.write(key: 'access_token', value: 'test-token');
        adapter.setResponse('/chatbot/sessions', []);

        // Act
        await repository.getSessions();

        // Assert
        final captured = adapter._captured.last;
        expect(
          captured['headers']['Authorization'],
          'Bearer test-token',
        );
      });

      test('returns parsed list of ChatSessionModel', () async {
        // Arrange
        await storage.write(key: 'access_token', value: 'token');
        adapter.setResponse(
          '/chatbot/sessions',
          [
            {
              'id': 'session-1',
              'user_id': 1,
              'created_at': '2024-01-01T00:00:00Z',
              'updated_at': '2024-01-02T00:00:00Z',
              'messages': [],
            },
          ],
        );

        // Act
        final sessions = await repository.getSessions();

        // Assert
        expect(sessions.length, 1);
        expect(sessions[0].id, 'session-1');
        expect(sessions[0].userId, 1);
      });
    });

    group('getSession', () {
      test('includes Bearer token in Authorization header', () async {
        // Arrange
        await storage.write(key: 'access_token', value: 'test-token');
        adapter.setResponse(
          '/chatbot/sessions/abc-123',
          {
            'id': 'abc-123',
            'user_id': 1,
            'created_at': null,
            'updated_at': null,
            'messages': [],
          },
        );

        // Act
        await repository.getSession(sessionId: 'abc-123');

        // Assert
        final captured = adapter._captured.last;
        expect(
          captured['headers']['Authorization'],
          'Bearer test-token',
        );
      });

      test('returns parsed ChatSessionModel', () async {
        // Arrange
        await storage.write(key: 'access_token', value: 'token');
        adapter.setResponse(
          '/chatbot/sessions/abc-123',
          {
            'id': 'abc-123',
            'user_id': 1,
            'created_at': '2024-01-01T00:00:00Z',
            'updated_at': '2024-01-02T00:00:00Z',
            'messages': [
              {
                'id': 'msg-1',
                'session_id': 'abc-123',
                'role': 'user',
                'content': 'Hello',
                'created_at': '2024-01-01T00:00:00Z',
              },
            ],
          },
        );

        // Act
        final session = await repository.getSession(sessionId: 'abc-123');

        // Assert
        expect(session.id, 'abc-123');
        expect(session.userId, 1);
        expect(session.messages.length, 1);
        expect(session.messages[0].role, 'user');
        expect(session.messages[0].content, 'Hello');
      });
    });
  });
}
