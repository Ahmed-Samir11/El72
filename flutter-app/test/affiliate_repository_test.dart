import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/data/repositories/affiliate_repository.dart';
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

/// Answers every request with [statusCode]/[headers], or throws when
/// [failure] is set. Captures the last [RequestOptions] so the test can pin
/// how the request was built (params + redirect policy).
class _ResponderAdapter implements HttpClientAdapter {
  _ResponderAdapter({
    this.statusCode = 307,
    this.headers = const {},
    this.failure,
  });

  final int statusCode;
  final Map<String, List<String>> headers;
  final Object? failure;

  late RequestOptions lastRequest;

  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    lastRequest = options;
    if (failure != null) throw failure!;
    return ResponseBody.fromBytes(<int>[], statusCode, headers: headers);
  }
}

const originalUrl = 'https://www.amazon.eg/dp/ABC123?ref=search';
const taggedUrl = 'https://www.amazon.eg/dp/ABC123?ref=search&tag=el72-20';

void main() {
  group('resolve', () {
    test(
      'reads the 307 Location header instead of following the redirect',
      () async {
        final adapter = _ResponderAdapter(
          headers: {
            'location': [taggedUrl],
          },
        );
        final client = ApiClient.withStorage(_FakeSecureStorage());
        client.dio.httpClientAdapter = adapter;
        final repo = AffiliateRepository(apiClient: client);

        final resolved = await repo.resolve(
          targetUrl: originalUrl,
          source: 'deal_feed',
          sku: 'ABC123',
          dealId: 'deal-7',
          category: 'laptops',
        );

        expect(resolved, taggedUrl);
        // The tagged URL is the payload: Dio must not follow the 307 (plan
        // p1 risk row — "Dio following the 307 would hide the tagged URL").
        expect(adapter.lastRequest.followRedirects, false);
        expect(adapter.lastRequest.maxRedirects, 0);
      },
    );

    test('serializes the attribution context as query parameters', () async {
      final adapter = _ResponderAdapter(
        statusCode: 307,
        headers: {
          'location': [taggedUrl],
        },
      );
      final client = ApiClient.withStorage(_FakeSecureStorage());
      client.dio.httpClientAdapter = adapter;
      final repo = AffiliateRepository(apiClient: client);

      await repo.resolve(
        targetUrl: originalUrl,
        source: 'search_result',
        sku: 'ABC123',
        dealId: 'deal-7',
        category: 'laptops',
      );

      final params = adapter.lastRequest.queryParameters;
      expect(params['target_url'], originalUrl);
      expect(params['source'], 'search_result');
      expect(params['sku'], 'ABC123');
      expect(params['deal_id'], 'deal-7');
      expect(params['category'], 'laptops');
      // Session id is generated per app run, never empty, so CTR can be
      // measured per session even for unauthenticated callers.
      expect(params['session_id'], isA<String>());
      expect((params['session_id'] as String).length, greaterThan(3));
    });

    test('a refused host (400) still opens the original URL', () async {
      final adapter = _ResponderAdapter(statusCode: 400);
      final client = ApiClient.withStorage(_FakeSecureStorage());
      client.dio.httpClientAdapter = adapter;
      final repo = AffiliateRepository(apiClient: client);

      final resolved = await repo.resolve(
        targetUrl: originalUrl,
        source: 'web',
      );

      // Monetization is an optimization of the tap, never a precondition.
      expect(resolved, originalUrl);
    });

    test(
      'a network failure returns the original URL and never throws',
      () async {
        final adapter = _ResponderAdapter(failure: Exception('offline'));
        final client = ApiClient.withStorage(_FakeSecureStorage());
        client.dio.httpClientAdapter = adapter;
        final repo = AffiliateRepository(apiClient: client);

        final resolved = await repo.resolve(
          targetUrl: originalUrl,
          source: 'tracker_card',
        );
        expect(resolved, originalUrl);
      },
    );

    test(
      'a legacy server (200, no Location) falls back to the original',
      () async {
        final adapter = _ResponderAdapter(statusCode: 200);
        final client = ApiClient.withStorage(_FakeSecureStorage());
        client.dio.httpClientAdapter = adapter;
        final repo = AffiliateRepository(apiClient: client);

        final resolved = await repo.resolve(
          targetUrl: originalUrl,
          source: 'web',
        );
        expect(resolved, originalUrl);
      },
    );

    test('a relative Location is resolved against the merchant URL', () async {
      final adapter = _ResponderAdapter(
        headers: {
          'Location': ['/affiliate-target'],
        },
      );
      final client = ApiClient.withStorage(_FakeSecureStorage());
      client.dio.httpClientAdapter = adapter;
      final repo = AffiliateRepository(apiClient: client);

      final resolved = await repo.resolve(
        targetUrl: 'https://www.noon.com/egypt-en/item/P9',
        source: 'search_result',
      );
      expect(resolved, 'https://www.noon.com/affiliate-target');
    });

    test('the header name casing of Location does not matter', () async {
      final adapter = _ResponderAdapter(
        headers: {
          'LOCATION': [taggedUrl],
        },
      );
      final client = ApiClient.withStorage(_FakeSecureStorage());
      client.dio.httpClientAdapter = adapter;
      final repo = AffiliateRepository(apiClient: client);

      final resolved = await repo.resolve(
        targetUrl: originalUrl,
        source: 'web',
      );
      expect(resolved, taggedUrl);
    });
  });
}
