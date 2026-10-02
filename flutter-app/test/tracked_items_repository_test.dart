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
/// `{"detail": [detail]}` (or an empty body when [detail] is null).
class _DetailAdapter implements HttpClientAdapter {
  _DetailAdapter(this.statusCode, this.detail);
  final int statusCode;
  final Object? detail;

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
    return ResponseBody.fromBytes(
      Uint8List.fromList(body),
      statusCode,
      headers: const {'content-type': ['application/json']},
    );
  }
}

/// Minimal JSON string-encoder for the adapter body (details are strings
/// or numbers in these tests).
String jsonEncodeDetail(Object? value) {
  if (value is num) return value.toString();
  return '"$value"';
}

void main() {
  group('createFromUrl error mapping', () {
    test('HTTP 402 raises InsufficientCreditsException with API detail',
        () async {
      final client = ApiClient.withStorage(_FakeSecureStorage());
      client.dio.httpClientAdapter = _DetailAdapter(402, 'Not enough credits');
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
    });

    test('HTTP 402 with a non-string detail falls back safely (no TypeError)',
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
    });

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

    test('HTTP 400 raises a generic Exception, not a credits exception',
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
    });
  });
}
