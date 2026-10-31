import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/l10n/app_localizations.dart';
import 'package:elhaq_tracker/src/core/styles/app_theme.dart';
import 'package:elhaq_tracker/src/data/models/alert_event_model.dart';
import 'package:elhaq_tracker/src/ui/common/merchant_link.dart';
import 'package:elhaq_tracker/src/ui/widgets/alert_card.dart';

AlertEvent _event({
  String url = 'https://www.amazon.eg/dp/ABC123',
  String id = '6f2b1a9c-0000-4f18-9b2e-1c2d3e4f5060',
  double? price = 800.0,
  double? reference = 1000.0,
  double? discount = 20.0,
  DateTime? openedAt,
  String storeId = 'amazon_eg',
  String eventType = eventTypePriceDrop,
  DateTime? createdAt,
}) => AlertEvent(
  id: id,
  eventType: eventType,
  priceEgp: price,
  referencePriceEgp: reference,
  discountPct: discount,
  storeId: storeId,
  category: 'Laptops',
  sku: 'ABC123',
  url: url,
  openedAt: openedAt,
  createdAt: createdAt ?? DateTime.now().toUtc(),
);

/// Records every resolve+open and answers with a canned result — the same
/// stand-in the deal card test uses.
class _FakeLink extends MerchantLink {
  _FakeLink({required this.opened});

  final bool opened;
  final List<String> sources = [];
  final List<String> urls = [];

  @override
  Future<bool> open({
    required String targetUrl,
    required String source,
    String? sku,
    String? dealId,
  }) async {
    sources.add(source);
    urls.add(targetUrl);
    return opened;
  }
}

Widget _app(AlertCard card, {Locale? locale}) {
  return MaterialApp(
    theme: AppTheme.light(),
    locale: locale,
    localizationsDelegates: const [
      AppLocalizations.delegate,
      GlobalMaterialLocalizations.delegate,
      GlobalWidgetsLocalizations.delegate,
      GlobalCupertinoLocalizations.delegate,
    ],
    supportedLocales: const [Locale('en'), Locale('ar')],
    home: Scaffold(body: Center(child: card)),
  );
}

void main() {
  testWidgets('tap attributes the alert surface and marks the event opened', (
    tester,
  ) async {
    final link = _FakeLink(opened: true);
    final marked = <String>[];

    await tester.runAsync(() async {
      await tester.pumpWidget(
        _app(
          AlertCard(
            event: _event(),
            merchantLink: link,
            onOpened: (eventId) => marked.add(eventId),
          ),
        ),
      );
      await tester.tap(find.byType(Card));
    });
    await tester.pump();

    // The affiliate dimension that lets report §11 measure CTR per surface:
    // an alert-originated tap must be separable from a deal-feed tap.
    expect(link.sources, [sourceAlertCard]);
    expect(link.urls, ['https://www.amazon.eg/dp/ABC123']);
    expect(marked, ['6f2b1a9c-0000-4f18-9b2e-1c2d3e4f5060']);
  });

  testWidgets('an event with no trustworthy URL opens no merchant and says so', (
    tester,
  ) async {
    final link = _FakeLink(opened: true);
    var marked = 0;

    await tester.runAsync(() async {
      await tester.pumpWidget(
        _app(
          AlertCard(
            event: _event(url: ''),
            merchantLink: link,
            onOpened: (_) => marked++,
          ),
        ),
      );
      await tester.tap(find.byType(Card));
    });
    await tester.pump();

    // The server only stores `url` when it matches tracked_item_stores.store_url,
    // so a card without one must not invent a destination.
    expect(link.sources, isEmpty);
    expect(marked, 1);
    expect(find.text('No merchant link for this alert.'), findsOneWidget);
  });

  testWidgets('null prices render no price line at all', (tester) async {
    await tester.runAsync(() async {
      await tester.pumpWidget(
        _app(
          AlertCard(
            event: _event(price: null, reference: null, discount: null),
          ),
        ),
      );
    });
    await tester.pump();

    expect(find.textContaining('Previous price:'), findsNothing);
    expect(find.textContaining('Current price:'), findsNothing);
    expect(find.textContaining('Discount:'), findsNothing);
    // The event is still in the feed: what happened is the server's story.
    expect(find.text('Amazon'), findsOneWidget);
  });

  testWidgets('prices that exist render the localized price pair', (
    tester,
  ) async {
    await tester.runAsync(() async {
      await tester.pumpWidget(_app(AlertCard(event: _event())));
    });
    await tester.pump();

    expect(find.textContaining('Previous price:'), findsAtLeast(1));
    expect(find.textContaining('Current price:'), findsAtLeast(1));
    expect(find.textContaining('Discount:'), findsAtLeast(1));
    expect(find.text('Today'), findsOneWidget);
  });

  group('event age', () {
    DateTime ago(int days) =>
        DateTime.now().toUtc().subtract(Duration(days: days, hours: 1));

    testWidgets('one day reads in the singular', (tester) async {
      await tester.pumpWidget(
        _app(AlertCard(event: _event(createdAt: ago(1)))),
      );
      expect(find.text('1 day ago'), findsOneWidget);
      expect(find.text('1 days ago'), findsNothing);
    });

    testWidgets('several days read in the plural', (tester) async {
      await tester.pumpWidget(
        _app(AlertCard(event: _event(createdAt: ago(3)))),
      );
      expect(find.text('3 days ago'), findsOneWidget);
    });

    testWidgets('Arabic uses the dual and the few forms', (tester) async {
      const arabic = Locale('ar');
      await tester.pumpWidget(
        _app(
          AlertCard(event: _event(createdAt: ago(2))),
          locale: arabic,
        ),
      );
      expect(find.text('منذ يومين'), findsOneWidget);

      await tester.pumpWidget(
        _app(
          AlertCard(event: _event(createdAt: ago(5))),
          locale: arabic,
        ),
      );
      expect(find.text('منذ 5 أيام'), findsOneWidget);
    });
  });

  group('server timestamps', () {
    Map<String, dynamic> json(String createdAt) => {
      'id': '6f2b1a9c-0000-4f18-9b2e-1c2d3e4f5060',
      'event_type': eventTypePriceDrop,
      'created_at': createdAt,
    };

    test('a naive server timestamp is read as UTC, not device-local', () {
      final event = AlertEvent.fromJson(json('2026-10-31T09:15:00'));
      expect(event.createdAt.isUtc, isTrue);
      expect(event.createdAt, DateTime.utc(2026, 10, 31, 9, 15));
    });

    test('a timestamp that carries an offset keeps it', () {
      final event = AlertEvent.fromJson(json('2026-10-31T11:15:00+02:00'));
      expect(event.createdAt.toUtc(), DateTime.utc(2026, 10, 31, 9, 15));
    });

    test('an unparseable timestamp is still flagged as missing', () {
      final event = AlertEvent.fromJson(json('not a date'));
      expect(event.hasCreatedAt, isFalse);
    });
  });
}
