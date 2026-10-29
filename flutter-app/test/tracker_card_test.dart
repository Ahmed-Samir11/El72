import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/l10n/app_localizations.dart';
import 'package:elhaq_tracker/src/core/styles/app_theme.dart';
import 'package:elhaq_tracker/src/ui/common/merchant_link.dart';
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
  String productUrl = '',
  String sku = '',
  MerchantLink? merchantLink,
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
    productUrl: productUrl,
    sku: sku,
    merchantLink: merchantLink,
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

  testWidgets('a retryable failure without onRetry falls back to onTap (never '
      'untappable)', (tester) async {
    var tapped = 0;
    await _pumpCard(
      tester,
      _card(fetchStatus: 'fetch_failed', onTap: () => tapped++),
    );

    await tester.tap(find.byType(TrackerCard));
    await tester.pump();

    expect(tapped, 1);
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

  testWidgets('an anomalous ok-without-price never spins forever', (
    tester,
  ) async {
    await _pumpCard(tester, _card(fetchStatus: 'ok'));
    // Settled state → retry chip, no spinner.
    expect(
      find.text("Couldn't fetch the price - tap to retry."),
      findsOneWidget,
    );
    expect(find.byType(CircularProgressIndicator), findsNothing);
  });

  testWidgets('an unknown status value also settles (no endless spinner)', (
    tester,
  ) async {
    await _pumpCard(tester, _card(fetchStatus: 'some_future_status'));
    expect(
      find.text("Couldn't fetch the price - tap to retry."),
      findsOneWidget,
    );
    expect(find.byType(CircularProgressIndicator), findsNothing);
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

  // --- "Open product" affordance (plan p1: the highest-intent object in
  // the app must be able to generate attributed merchant clicks) ----------

  testWidgets(
    'a tracker with a product url offers Open product, routing the tap '
    'through MerchantLink with tracker context',
    (tester) async {
      final link = _FakeLink(opened: true);
      await _pumpCard(
        tester,
        _card(
          productUrl: 'https://www.amazon.eg/dp/ABC123',
          sku: 'iphone-15-pro-max-256',
          merchantLink: link,
        ),
      );

      expect(find.text('Open product'), findsOneWidget);
      await tester.tap(find.byIcon(Icons.open_in_new));
      await tester.pump();

      expect(link.sources, hasLength(1));
      expect(link.sources.single, 'tracker_card');
      expect(link.targetUrls.single, 'https://www.amazon.eg/dp/ABC123');
      expect(link.skus.single, 'iphone-15-pro-max-256');
      expect(find.byType(SnackBar), findsNothing);
    },
  );

  testWidgets('a tracker without a product url offers no action', (
    tester,
  ) async {
    await _pumpCard(tester, _card());
    expect(find.byIcon(Icons.open_in_new), findsNothing);
    expect(find.text('Open product'), findsNothing);
  });

  testWidgets('a corrupt non-web product url renders no action either', (
    tester,
  ) async {
    // A junk scheme from a corrupt store mapping must not render an affordance
    // that could only fail into a snackbar; isHttpUrl gates the affordance.
    await _pumpCard(tester, _card(productUrl: 'file:///etc/passwd'));
    expect(find.byIcon(Icons.open_in_new), findsNothing);
  });

  testWidgets('a failed Open product tap shows the unableToOpen snackbar', (
    tester,
  ) async {
    final link = _FakeLink(opened: false);
    await _pumpCard(
      tester,
      _card(productUrl: 'https://www.amazon.eg/dp/ABC123', merchantLink: link),
    );

    await tester.tap(find.byIcon(Icons.open_in_new));
    await tester.pump();

    expect(find.text('Unable to open Test Product'), findsOneWidget);
  });
}

/// Records the open call (surface + context) and answers with a canned
/// success/failure, standing in for resolve+launch together.
class _FakeLink extends MerchantLink {
  _FakeLink({required this.opened});

  final bool opened;
  final List<String> sources = [];
  final List<String> targetUrls = [];
  final List<String?> skus = [];

  @override
  Future<bool> open({
    required String targetUrl,
    required String source,
    String? sku,
    String? dealId,
  }) async {
    sources.add(source);
    targetUrls.add(targetUrl);
    skus.add(sku);
    return opened;
  }
}
