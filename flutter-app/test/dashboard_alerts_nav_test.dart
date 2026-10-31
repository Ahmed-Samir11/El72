import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/l10n/app_localizations.dart';
import 'package:elhaq_tracker/src/core/styles/app_theme.dart';
import 'package:elhaq_tracker/src/data/models/alert_event_model.dart';
import 'package:elhaq_tracker/src/data/providers.dart';
import 'package:elhaq_tracker/src/data/models/credit_balance_model.dart';
import 'package:elhaq_tracker/src/data/models/platform_stats_model.dart';
import 'package:elhaq_tracker/src/data/repositories/alert_events_repository.dart';
import 'package:elhaq_tracker/src/ui/dashboard/dashboard_page.dart';

AlertEvent _event({
  String url = 'https://www.amazon.eg/dp/SKU-1',
  double? price = 800.0,
  double? reference = 1000.0,
  DateTime? openedAt,
}) => AlertEvent(
  id: 'evt-1',
  eventType: eventTypePriceDrop,
  priceEgp: price,
  referencePriceEgp: reference,
  discountPct: 20.0,
  storeId: 'amazon_eg',
  category: 'Laptops',
  sku: 'SKU-1',
  url: url,
  openedAt: openedAt,
  createdAt: DateTime.now().toUtc(),
);

Widget _app({Locale? locale, int unopened = 4, List<AlertEvent>? alerts}) {
  final feed = AlertFeed(
    alerts: alerts ?? <AlertEvent>[_event()],
    unopenedTotal: unopened,
  );
  return ProviderScope(
    // The dashboard's other feeds are left alone: they fail offline exactly as
    // they do in the credits test. Only the alert feed is pinned, because that
    // is what the Alerts tab renders.
    // Every user-scoped feed the dashboard can read is pinned to an instant
    // value: an un-pinned repository would start a real Dio request whose
    // connect-timeout timer outlives the test ("a Timer is still pending").
    overrides: [
      alertFeedProvider.overrideWith((_) async => feed),
      trackedItemsProvider.overrideWith((_) async => const <Never>[]),
      liveDealsProvider.overrideWith((_) async => const <Never>[]),
      platformStatsProvider.overrideWith(
        (_) async => const PlatformStats(totalTrackers: 0, dealsToday: 0, totalSavings: 0.0),
      ),
      creditBalanceProvider.overrideWith(
        (_) async => const CreditBalance(balance: 0, tier: 'free'),
      ),
    ],
    child: MaterialApp(
      theme: AppTheme.light(),
      locale: locale,
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: const [Locale('en'), Locale('ar')],
      home: const DashboardPage(),
    ),
  );
}

/// Tapping a bottom-navigation label selects that slot, the way the existing
/// dashboard tests reach Profile.
Future<void> _select(WidgetTester tester, String label) async {
  await tester.tap(find.text(label));
  // Fixed pumps, not pumpAndSettle: the tab being replaced animates a loading
  // spinner, so a settle loop has nothing to settle on and times out.
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 600));
}

void main() {
  testWidgets('Alerts sits ahead of Deals in the navigation', (tester) async {
    await tester.pumpWidget(_app());

    final bar = tester.widget<NavigationBar>(find.byType(NavigationBar));
    // NavigationBar stores destinations as widgets; the label is read
    // through the concrete type.
    final labels = bar.destinations
        .map((d) => (d as NavigationDestination).label)
        .toList();

    expect(labels, ['Trackers', 'Alerts', 'Deals', 'Chat', 'Profile']);
    expect(labels.indexOf('Alerts') < labels.indexOf('Deals'), isTrue);
  });

  testWidgets('the Arabic build navigates by the Arabic label, not hardcoded English', (
    tester,
  ) async {
    await tester.pumpWidget(_app(locale: const Locale('ar')));

    final label = (tester.widget<NavigationBar>(find.byType(NavigationBar))
            .destinations[1] as NavigationDestination)
        .label;
    // Asserted as Arabic script rather than a typed glyph: what matters is that
    // the slot comes from navAlerts in the ARB, never a hardcoded English label.
    expect(RegExp('[؀-ۿ]').hasMatch(label), isTrue);
    expect(find.text('Alerts'), findsNothing);
  });

  testWidgets('the Alerts slot renders the feed, badge and price pair', (
    tester,
  ) async {
    await tester.pumpWidget(_app(unopened: 4));
    await _select(tester, 'Alerts');

    expect(find.textContaining('active alerts'), findsOneWidget);
    expect(find.textContaining('Previous price:'), findsAtLeast(1));
    expect(find.textContaining('Current price:'), findsAtLeast(1));
    expect(find.text('Amazon'), findsAtLeast(1));
    expect(find.text('Today'), findsAtLeast(1));
  });

  testWidgets('a read that failed says it failed, instead of claiming no alerts', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          alertFeedProvider.overrideWith(
            (_) async => throw AlertFeedUnavailable(404),
          ),
          trackedItemsProvider.overrideWith((_) async => const <Never>[]),
          liveDealsProvider.overrideWith((_) async => const <Never>[]),
          platformStatsProvider.overrideWith(
            (_) async => const PlatformStats(
              totalTrackers: 0,
              dealsToday: 0,
              totalSavings: 0.0,
            ),
          ),
          creditBalanceProvider.overrideWith(
            (_) async => const CreditBalance(balance: 0, tier: 'free'),
          ),
        ],
        child: MaterialApp(
          theme: AppTheme.light(),
          localizationsDelegates: const [
            AppLocalizations.delegate,
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
            GlobalCupertinoLocalizations.delegate,
          ],
          supportedLocales: const [Locale('en'), Locale('ar')],
          home: const DashboardPage(),
        ),
      ),
    );
    await _select(tester, 'Alerts');

    expect(find.textContaining('Failed to load alerts.'), findsOneWidget);
    expect(find.textContaining('No price alerts yet.'), findsNothing);
  });

  testWidgets('inserting the slot keeps the tracker + button on Trackers and Deals', (
    tester,
  ) async {
    await tester.pumpWidget(_app());

    // The floating action button is switched by NAV INDEX, not by label, so
    // inserting Alerts would silently un-pair it from Deals: index 1 used to
    // be Deals.
    expect(find.byType(FloatingActionButton), findsOneWidget); // Trackers (0)
    await _select(tester, 'Deals');
    expect(find.byType(FloatingActionButton), findsOneWidget); // Deals (2)
    await _select(tester, 'Alerts');
    expect(find.byType(FloatingActionButton), findsNothing); // Alerts (1)
  });
}
