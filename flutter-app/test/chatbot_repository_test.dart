import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/data/repositories/chatbot_repository.dart';

/// In-memory stand-in for [FlutterSecureStorage]: no platform channel is touched,
/// and it reports no stored token, which is enough to reach the path guard.
class _FakeSecureStorage extends FlutterSecureStorage {
  @override
  Future<String?> read({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async => null;

  @override
  Future<void> write({
    required String key,
    required String? value,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {}

  @override
  Future<void> delete({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {}
}

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

    test('refuses a session id that is not a UUID before naming the path', () async {
      // The id is interpolated into `/chatbot/sessions/<id>`, and the value the
      // app holds can be the one the chatbot echoed back. A slash, a `..` or a
      // `?` in it would move the request to a different endpoint of the proxied
      // service, so it is rejected before any request is built: Dio is a fresh
      // client here, and no transport is reached.
      final repo = ChatbotRepository(dio: Dio(), storage: _FakeSecureStorage());
      for (final bad in const [
        '',
        'session/../../x',
        '550e8400-e59b-4f0f-9249-6b1f1de2e80x',
        '550e8400-e59b-4f0f-9249-6b1f1de2e80a?x=1',
        '550e8400-e59b-4f0f-9249-6b1f1de2e80a#frag',
      ]) {
        await expectLater(
          repo.getSession(sessionId: bad),
          throwsA(isA<ArgumentError>()),
          reason: bad,
        );
      }
    });

    test(
      'rejects a session id that is not a UUID on the write calls too',
      () async {
        // The body of a POST cannot change routing the way a path segment can,
        // but a non-UUID id means the conversation was handed something the
        // chatbot never issues: failing here beats a confusing 4xx from the
        // service, and the check is one call rather than one per endpoint.
        final repo = ChatbotRepository(
          dio: Dio(),
          storage: _FakeSecureStorage(),
        );
        for (final bad in const ['', 'not-a-uuid', 'x/../../y']) {
          await expectLater(
            repo.sendMessage(sessionId: bad, message: 'gaming laptop'),
            throwsA(isA<ArgumentError>()),
            reason: bad,
          );
          await expectLater(
            repo.addToFeed(sessionId: bad, productUrl: 'https://2b.com.eg/p/1'),
            throwsA(isA<ArgumentError>()),
            reason: bad,
          );
        }
        expect(
          ChatbotRepository.isSessionId('550e8400-e59b-4f0f-9249-6b1f1de2e80a'),
          true,
        );
      },
    );
  });
}
