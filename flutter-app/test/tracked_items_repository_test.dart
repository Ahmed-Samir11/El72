import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/data/repositories/tracked_items_repository.dart';
import 'package:elhaq_tracker/src/data/services/api_client.dart';

/// In-memory stand-in for [FlutterSecureStorage] so no platform channel is
/// touched (the auth interceptor reads the token before every request).
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

/// Dio adapter answering every request with [statusCode] and a JSON body
/// `{"detail": [detail]}` (or an empty body when [detail] is null). Fair-use
/// refusals send `detail` as an object, and the rate refusal also carries a
/// `Retry-After` header, so both are supported here.
class _DetailAdapter implements HttpClientAdapter {
  _DetailAdapter(this.statusCode, this.detail, {this.retryAfter});
  final int statusCode;
  final Object? detail;
  final String? retryAfter;

  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    final body = detail == null
        ? <int>[]
        : ('{"detail": ${jsonEncodeDetail(detail)}}'.codeUnits);
    final headers = <String, List<String>>{
      'content-type': ['application/json'],
      if (retryAfter != null) 'retry-after': [retryAfter!],
    };
    return ResponseBody.fromBytes(
      Uint8List.fromList(body),
      statusCode,
      headers: headers,
    );
  }
}

/// Minimal JSON encoder for the adapter body: details are strings, numbers,
/// or (for the fair-use contract) a flat object of strings and numbers.
String jsonEncodeDetail(Object? value) {
  if (value is num) return value.toString();
  if (value is Map) {
    final entries = value.entries.map(
      (e) => '"${e.key}": ${jsonEncodeDetail(e.value)}',
    );
    return '{${entries.join(', ')}}';
  }
  return '"$value"';
}

void main() {
  group('createFromUrl error mapping', () {
    test(
      'HTTP 402 raises InsufficientCreditsException with API detail',
      () async {
        final client = ApiClient.withStorage(_FakeSecureStorage());
        client.dio.httpClientAdapter = _DetailAdapter(
          402,
          'Not enough credits',
        );
        final repo = TrackedItemsRepository(apiClient: client);

        await expectLater(
          repo.createFromUrl('https://example.com/x'),
          throwsA(
            isA<InsufficientCreditsException>().having(
              (e) => e.message,
              'message',
              'Not enough credits',
            ),
          ),
        );
      },
    );

    test(
      'HTTP 402 with a non-string detail falls back safely (no TypeError)',
      () async {
        final client = ApiClient.withStorage(_FakeSecureStorage());
        client.dio.httpClientAdapter = _DetailAdapter(402, 42);
        final repo = TrackedItemsRepository(apiClient: client);

        await expectLater(
          repo.createFromUrl('https://example.com/x'),
          throwsA(
            isA<InsufficientCreditsException>().having(
              (e) => e.message,
              'message',
              'Insufficient credits',
            ),
          ),
        );
      },
    );

    test('HTTP 402 with no body falls back to the default message', () async {
      final client = ApiClient.withStorage(_FakeSecureStorage());
      client.dio.httpClientAdapter = _DetailAdapter(402, null);
      final repo = TrackedItemsRepository(apiClient: client);

      await expectLater(
        repo.createFromUrl('https://example.com/x'),
        throwsA(
          isA<InsufficientCreditsException>().having(
            (e) => e.message,
            'message',
            'Insufficient credits',
          ),
        ),
      );
    });

    test('HTTP 500 raises a generic Exception with the API detail', () async {
      final client = ApiClient.withStorage(_FakeSecureStorage());
      client.dio.httpClientAdapter = _DetailAdapter(500, 'Server exploded');
      final repo = TrackedItemsRepository(apiClient: client);

      await expectLater(
        repo.createFromUrl('https://example.com/x'),
        throwsA(
          isA<Exception>().having(
            (e) => e.toString(),
            'message',
            'Exception: Server exploded',
          ),
        ),
      );
    });

    test(
      'HTTP 400 raises a generic Exception, not a credits exception',
      () async {
        final client = ApiClient.withStorage(_FakeSecureStorage());
        client.dio.httpClientAdapter = _DetailAdapter(400, 'Bad URL');
        final repo = TrackedItemsRepository(apiClient: client);

        Object? caught;
        try {
          await repo.createFromUrl('https://example.com/x');
        } catch (e) {
          caught = e;
        }

        expect(caught, isA<Exception>());
        expect(caught, isNot(isA<InsufficientCreditsException>()));
      },
    );
  });

  // The free-tracker contract (plans/p3-free-tracker-model-alignment.md, MS1):
  // a shipped backend answers cap and rate refusals with a structured `detail`
  // object, and the client must tell those two states apart from each other and
  // from the legacy 402 - it cannot render the right copy otherwise.
  group('fair-use error mapping', () {
    test(
      'HTTP 409 with the cap body raises FairUseCapException carrying the numbers',
      () async {
        final client = ApiClient.withStorage(_FakeSecureStorage());
        client.dio.httpClientAdapter = _DetailAdapter(409, {
          'code': 'fair_use_cap',
          'active_trackers': 100,
          'cap': 100,
        });
        final repo = TrackedItemsRepository(apiClient: client);

        await expectLater(
          repo.createFromUrl('https://example.com/x'),
          throwsA(
            isA<FairUseCapException>()
                .having((e) => e.activeTrackers, 'activeTrackers', 100)
                .having((e) => e.cap, 'cap', 100),
          ),
        );
      },
    );

    test(
      'HTTP 429 with the rate body raises RateLimitedException with the countdown',
      () async {
        final client = ApiClient.withStorage(_FakeSecureStorage());
        client.dio.httpClientAdapter = _DetailAdapter(429, {
          'code': 'creation_rate_limit',
          'retry_after_seconds': 2.76,
        }, retryAfter: '3');
        final repo = TrackedItemsRepository(apiClient: client);

        await expectLater(
          repo.createFromUrl('https://example.com/x'),
          throwsA(
            isA<RateLimitedException>().having(
              (e) => e.retryAfterSeconds,
              'retryAfterSeconds',
              2.76,
            ),
          ),
        );
      },
    );

    test(
      'HTTP 429 without a countdown in the body falls back to Retry-After',
      () async {
        final client = ApiClient.withStorage(_FakeSecureStorage());
        client.dio.httpClientAdapter = _DetailAdapter(429, {
          'code': 'creation_rate_limit',
        }, retryAfter: '4');
        final repo = TrackedItemsRepository(apiClient: client);

        await expectLater(
          repo.createFromUrl('https://example.com/x'),
          throwsA(
            isA<RateLimitedException>().having(
              (e) => e.retryAfterSeconds,
              'retryAfterSeconds',
              4.0,
            ),
          ),
        );
      },
    );

    test(
      'HTTP 429 with an HTTP-date Retry-After gives a zero countdown, not a crash',
      () async {
        // A proxy may replace the server's body countdown with an HTTP date.
        // The client cannot resolve it, so it reports 0 = "no usable countdown"
        // rather than inventing a wait; MS2's dialog must then show its copy
        // without a number (recorded in plans/p3 as a separate copy row).
        final client = ApiClient.withStorage(_FakeSecureStorage());
        client.dio.httpClientAdapter = _DetailAdapter(429, {
          'code': 'creation_rate_limit',
        }, retryAfter: 'Wed, 21 Oct 2026 07:28:00 GMT');
        final repo = TrackedItemsRepository(apiClient: client);

        await expectLater(
          repo.createFromUrl('https://example.com/x'),
          throwsA(
            isA<RateLimitedException>()
                .having((e) => e.retryAfterSeconds, 'retryAfterSeconds', 0.0)
                // The original transport error is kept so the UI can render
                // its usual line instead of this exception's internals.
                .having((e) => e.cause, 'cause', isA<DioException>()),
          ),
        );
      },
    );

    test(
      'malformed fair-use numbers degrade to zero instead of crashing',
      () async {
        final client = ApiClient.withStorage(_FakeSecureStorage());
        client.dio.httpClientAdapter = _DetailAdapter(409, {
          'code': 'fair_use_cap',
          'active_trackers': 'many',
          'cap': null,
        });
        final repo = TrackedItemsRepository(apiClient: client);

        await expectLater(
          repo.createFromUrl('https://example.com/x'),
          throwsA(
            isA<FairUseCapException>()
                .having((e) => e.activeTrackers, 'activeTrackers', 0)
                .having((e) => e.cap, 'cap', 0),
          ),
        );
      },
    );

    test(
      'HTTP 409 with a plain string detail is NOT read as the fair-use cap',
      () async {
        // The cap dialog is driven by `detail.code`, never by the status alone:
        // a duplicate-link 409 must not claim the user is at the ceiling.
        final client = ApiClient.withStorage(_FakeSecureStorage());
        client.dio.httpClientAdapter = _DetailAdapter(409, 'Already tracked');
        final repo = TrackedItemsRepository(apiClient: client);

        Object? caught;
        try {
          await repo.createFromUrl('https://example.com/x');
        } catch (e) {
          caught = e;
        }

        expect(caught, isA<Exception>());
        expect(caught, isNot(isA<FairUseCapException>()));
        expect(caught?.toString(), contains('Already tracked'));
      },
    );

    test('HTTP 402 still maps to the legacy credits exception', () async {
      // A build pointed at a CREDITS_ENFORCEMENT=on backend keeps working:
      // the free-model mapping must not swallow the legacy signal.
      final client = ApiClient.withStorage(_FakeSecureStorage());
      client.dio.httpClientAdapter = _DetailAdapter(402, 'Not enough credits');
      final repo = TrackedItemsRepository(apiClient: client);

      await expectLater(
        repo.createFromUrl('https://example.com/x'),
        throwsA(isA<InsufficientCreditsException>()),
      );
    });
  });
}
