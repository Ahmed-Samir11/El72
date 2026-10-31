import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/data/models/alert_event_model.dart';
import 'package:elhaq_tracker/src/data/repositories/alert_events_repository.dart';
import 'package:elhaq_tracker/src/data/services/api_client.dart';

/// In-memory stand-in for [FlutterSecureStorage] (the auth interceptor reads
/// the token before every request) — same shape as the tracked-items tests.
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
  }) async => 'token';

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

/// Answers with [body] at [statusCode], and remembers the path and query so a
/// test can assert what the client actually asked for.
class _Adapter implements HttpClientAdapter {
  _Adapter(this.statusCode, this.body);

  int statusCode;
  String body;
  final List<String> paths = [];
  final List<Map<String, dynamic>> queries = [];

  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    paths.add(options.path);
    queries.add(options.queryParameters);
    return ResponseBody.fromString(
      body,
      statusCode,
      headers: const {'content-type': ['application/json']},
    );
  }
}

/// A client whose Dio answers through [_Adapter].
(AlertEventsRepository, _Adapter) _repo() {
  final client = ApiClient.withStorage(_FakeSecureStorage());
  final adapter = _Adapter(200, '{}');
  client.dio.httpClientAdapter = adapter;
  return (AlertEventsRepository(apiClient: client), adapter);
}

const twoRowsEnvelope = '''
{"alerts": [
   {"id": "6f2b1a9c-0000-4f18-9b2e-1c2d3e4f5060",
    "tracked_item_id": 11,
    "sku": "SKU-1", "store_id": "amazon_eg", "category": "Laptops",
    "url": "https://www.amazon.eg/dp/SKU-1",
    "event_type": "price_drop",
    "price_egp": 800.0, "reference_price_egp": 1000.0, "discount_pct": 20.0,
    "channel": "in_app",
    "created_at": "2026-06-24T09:10:00", "opened_at": null},
   {"id": 7,
    "sku": "SKU-2", "store_id": "compumarts_eg", "category": null,
    "url": "", "event_type": "back_in_stock",
    "price_egp": null, "reference_price_egp": null, "discount_pct": null,
    "channel": "in_app",
    "created_at": "2026-06-25T09:10:00", "opened_at": "2026-06-25T10:00:00"}
 ],
 "unopened_total": 9,
 "limit": 50}
''';

void main() {
  group('getRecentAlerts', () {
    test('parses the envelope and keeps the server order', () async {
      final (repo, adapter) = _repo();
      adapter.body = twoRowsEnvelope;

      final feed = await repo.getRecentAlerts();

      expect(feed.alerts.length, 2);
      // The repository preserves the server's array order (the router orders
      // by created_at desc) and never re-sorts locally: the server owns the
      // timeline, the client only displays it.
      expect(feed.alerts.map((e) => e.id).toList(), [
        '6f2b1a9c-0000-4f18-9b2e-1c2d3e4f5060',
        '7',
      ]);
      // A UUID id (PostgreSQL) and an INTEGER id (the SQLite fixtures) are
      // both opaque strings, and the price pair survives.
      expect(feed.alerts[0].eventType, eventTypePriceDrop);
      expect(feed.alerts[0].priceEgp, 800.0);
      expect(feed.alerts[0].referencePriceEgp, 1000.0);
    });

    test('the badge is the server total, not a count of the window', () async {
      final (repo, adapter) = _repo();
      adapter.body = twoRowsEnvelope;

      final feed = await repo.getRecentAlerts(limit: 2);

      // The router documents the split (its test name says "counts the account,
      // not the window"): a clipped list must never shrink the badge, which is
      // the opened/unopened ratio Gate 2 measures.
      expect(feed.alerts.length, 2);
      expect(feed.unopenedTotal, 9);
    });

    test('a price of null stays null instead of becoming a fake 0', () async {
      final (repo, adapter) = _repo();
      adapter.body = twoRowsEnvelope;

      final feed = await repo.getRecentAlerts();
      final noPrice = feed.alerts.singleWhere((e) => e.id == '7');

      expect(noPrice.priceEgp, isNull);
      expect(noPrice.discountPct, isNull);
    });

    test('asks within the server limit so the query cannot be rejected (422)', () async {
      final (repo, adapter) = _repo();
      adapter.body = twoRowsEnvelope;

      await repo.getRecentAlerts(limit: 5000);
      expect(adapter.queries.last['limit'], maxAlertsLimit);

      await repo.getRecentAlerts(limit: 0);
      expect(adapter.queries.last['limit'], minAlertsLimit);

      await repo.getRecentAlerts();
      expect(adapter.queries.last['limit'], defaultAlertsLimit);
    });

    test('HTTP 404 (a server older than plans/p2) is a failure, not emptiness', () async {
      final (repo, adapter) = _repo();
      adapter.statusCode = 404;
      adapter.body = '{"detail": "Not Found"}';

      await expectLater(
        repo.getRecentAlerts(),
        throwsA(
          isA<AlertFeedUnavailable>().having(
            (e) => e.statusCode,
            'statusCode',
            404,
          ),
        ),
      );
    });

    test('junk in the envelope drops rows instead of throwing the feed away', () async {
      final (repo, adapter) = _repo();
      adapter.body = jsonEncode({
        'alerts': [
          {'id': 1, 'created_at': 'not-a-time'}, // unplaceable on a timeline
          'not-an-object',
          {'id': 2, 'created_at': '2026-06-25T08:00:00', 'store_id': 42},
        ],
        'unopened_total': '3',
      });

      final feed = await repo.getRecentAlerts();

      expect(feed.alerts.length, 1); // the unparseable row is dropped
      expect(feed.unopenedTotal, 3); // a string number still counts
    });

    test('an empty array with no failure means the empty state', () async {
      final (repo, adapter) = _repo();
      adapter.body = '{"alerts": [], "unopened_total": 0}';

      final feed = await repo.getRecentAlerts();
      expect(feed.alerts, isEmpty);
      expect(feed.unopenedTotal, 0);
    });
  });

  group('markOpened', () {
    test('addresses the open endpoint for the caller\'s own event id', () async {
      final (repo, adapter) = _repo();
      adapter.statusCode = 200;
      adapter.body = '{"opened_at": "2026-06-25T10:00:00"}';

      final marked = await repo.markOpened('6f2b1a9c-0000-4f18-9b2e-1c2d3e4f5060');

      expect(marked, isTrue);
      expect(adapter.paths.last, '/alerts/6f2b1a9c-0000-4f18-9b2e-1c2d3e4f5060/open');
    });

    test('an id that is not an id shape never reaches the network', () async {
      final (repo, adapter) = _repo();

      for (final bad in ['..', '../other', 'a/b', 'x?y', '', 'z' * 65]) {
        expect(await repo.markOpened(bad), isFalse, reason: bad);
      }
      expect(adapter.paths, isEmpty);
    });

    test('a refused open (404, another user\'s row) answers false', () async {
      final (repo, adapter) = _repo();
      adapter.statusCode = 404;
      adapter.body = '{"detail": "Not Found"}';

      expect(await repo.markOpened('123'), isFalse);
    });
  });
}
