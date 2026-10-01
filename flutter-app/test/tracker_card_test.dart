import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/l10n/app_localizations.dart';
import 'package:elhaq_tracker/src/core/styles/app_theme.dart';
import 'package:elhaq_tracker/src/ui/widgets/tracker_card.dart';

Widget _wrap(TrackerCard card) {
  return MaterialApp(
    theme: AppTheme.light(),
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

Future<void> _pumpCard(WidgetTester tester, TrackerCard card) async {
  // Widen the surface: the default test font renders square glyphs, so the
  // chip text needs more room than a phone-width surface would give it.
  tester.view.physicalSize = const Size(1280, 1024);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(_wrap(card));
}

TrackerCard _card({
  String? fetchStatus,
  VoidCallback? onTap,
  VoidCallback? onRetry,
}) {
  return TrackerCard(
    imageUrl: '',
    title: 'Test Product',
    currentPrice: 0.0,
    targetPrice: 0.0,
    hasPrice: false,
    isActive: true,
    fetchStatus: fetchStatus,
    onTap: onTap,
    onRetry: onRetry,
  );
}

void main() {
  testWidgets('no status yet shows the fetching chip', (tester) async {
    await _pumpCard(tester, _card());
    expect(find.text('Fetching live price...'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
  });

  testWidgets('no_price_found shows the not-a-product chip', (tester) async {
    await _pumpCard(tester, _card(fetchStatus: 'no_price_found'));
    expect(
      find.text("This page doesn't look like a product - check the link."),
      findsOneWidget,
    );
    // No spinner in a definitive failure state.
    expect(find.byType(CircularProgressIndicator), findsNothing);
  });

  testWidgets('fetch_failed shows the retry chip', (tester) async {
    await _pumpCard(tester, _card(fetchStatus: 'fetch_failed'));
    expect(
      find.text("Couldn't fetch the price - tap to retry."),
      findsOneWidget,
    );
  });

  testWidgets('blocked shows the retry chip', (tester) async {
    await _pumpCard(tester, _card(fetchStatus: 'blocked'));
    expect(
      find.text("Couldn't fetch the price - tap to retry."),
      findsOneWidget,
    );
  });

  testWidgets('tap in failure state calls onRetry, not onTap', (tester) async {
    var tapped = 0;
    var retried = 0;
    await _pumpCard(
      tester,
      _card(
        fetchStatus: 'fetch_failed',
        onTap: () => tapped++,
        onRetry: () => retried++,
      ),
    );

    await tester.tap(find.byType(TrackerCard));
    await tester.pump();

    expect(retried, 1);
    expect(tapped, 0);
  });

  testWidgets('tap in fetching state calls onTap, not onRetry', (tester) async {
    var tapped = 0;
    var retried = 0;
    await _pumpCard(
      tester,
      _card(onTap: () => tapped++, onRetry: () => retried++),
    );

    await tester.tap(find.byType(TrackerCard));
    await tester.pump();

    expect(tapped, 1);
    expect(retried, 0);
  });

  testWidgets('a card with a price shows the price, no chip', (tester) async {
    await _pumpCard(
      tester,
      TrackerCard(
        imageUrl: '',
        title: 'Test Product',
        currentPrice: 1250.0,
        targetPrice: 1000.0,
        hasPrice: true,
        isActive: true,
        fetchStatus: 'ok',
      ),
    );
    expect(find.textContaining('1,250'), findsOneWidget);
    expect(find.text('Fetching live price...'), findsNothing);
  });
}
