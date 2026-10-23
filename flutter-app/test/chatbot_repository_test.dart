import 'package:flutter_test/flutter_test.dart';
import 'package:dio/dio.dart';

import 'package:elhaq_tracker/src/data/repositories/chatbot_repository.dart';

void main() {
  group('ChatbotRepository', () {
    test('creates repository with default config', () {
      // Repository should construct without errors using default Dio and storage.
      final repo = ChatbotRepository();
      expect(repo, isA<ChatbotRepository>());
    });

    test('creates repository with custom Dio', () {
      final dio = Dio();
      final repo = ChatbotRepository(dio: dio);
      expect(repo, isA<ChatbotRepository>());
    });
  });
}
