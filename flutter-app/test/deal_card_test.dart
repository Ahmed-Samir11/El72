import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/l10n/app_localizations.dart';
import 'package:elhaq_tracker/src/core/styles/app_theme.dart';
import 'package:elhaq_tracker/src/data/models/deal_model.dart';
import 'package:elhaq_tracker/src/ui/common/merchant_link.dart';
import 'package:elhaq_tracker/src/ui/widgets/deal_card.dart';

Deal _deal() => Deal(
  id: 'deal-7',
  title: 'Test Deal',
  storeName: 'Amazon.eg',
  imageUrl: '',
  sourceUrl: 'https://www.amazon.eg/dp/ABC123?ref=search',
  sku: 'ABC123',
  price: 100.0,
  originalPrice: 120.0,
  discountPercentage: 17.0,
);

Widget _cardApp(Deal deal, MerchantLink link) {
  return MaterialApp(
    theme: AppTheme.light(),
    localizationsDelegates: const [
      AppLocalizations.delegate,
      GlobalMaterialLocalizations.delegate,
      GlobalWidgetsLocalizations.delegate,
      GlobalCupertinoLocalizations.delegate,
    ],
    supportedLocales: const [Locale('en'), Locale('ar')],
    home: Scaffold(
      body: Center(
        child: DealCard(deal: deal, merchantLink: link),
      ),
    ),
  );
}

/// Records every open call (surface + context) and answers with a canned
/// success/failure, standing in for resolve+launch together.
class _FakeLink extends MerchantLink {
  _FakeLink({required this.opened});

  final bool opened;
  final List<OpenCall> calls = [];

  @override
  Future<bool> open({
    required String targetUrl,
    required String source,
    String? sku,
    String? dealId,
  }) async {
    calls.add(
      OpenCall(targetUrl: targetUrl, source: source, sku: sku, dealId: dealId),
    );
    return opened;
  }
}

class OpenCall {
  OpenCall({
    required this.targetUrl,
    required this.source,
    this.sku,
    this.dealId,
  });

  final String targetUrl;
  final String source;
  final String? sku;
  final String? dealId;
}

void main() {
  testWidgets(
    'a deal tap resolves through the affiliate redirect with deal context',
    (tester) async {
      final link = _FakeLink(opened: true);
      await tester.pumpWidget(_cardApp(_deal(), link));

      await tester.tap(find.byType(InkWell).first);
      await tester.pump();

      expect(link.calls, hasLength(1));
      final call = link.calls.single;
      expect(call.targetUrl, _deal().sourceUrl);
      // The stable surface label is what makes affiliate CTR measurable
      // per surface (plan p1 / report §11).
      expect(call.source, 'deal_feed');
      expect(call.sku, 'ABC123');
      expect(call.dealId, 'deal-7');
      // Success: no failure snackbar.
      expect(find.byType(SnackBar), findsNothing);
    },
  );

  testWidgets('a failed launch keeps the unableToOpen snackbar', (
    tester,
  ) async {
    final link = _FakeLink(opened: false);
    await tester.pumpWidget(_cardApp(_deal(), link));

    await tester.tap(find.byType(InkWell).first);
    await tester.pump();

    expect(find.text('Unable to open Test Deal'), findsOneWidget);
  });

  testWidgets('a deal with no source url reports instead of launching', (
    tester,
  ) async {
    // The real MerchantLink refuses non-web urls before even resolving;
    // this guards the card still shows an actionable message.
    final link = _FakeLink(opened: false);
    await tester.pumpWidget(
      _cardApp(
        Deal(
          id: 'deal-9',
          title: 'No Link Deal',
          storeName: 'Amazon.eg',
          imageUrl: '',
          price: 100.0,
          originalPrice: 100.0,
          discountPercentage: 0.0,
        ),
        link,
      ),
    );

    await tester.tap(find.byType(InkWell).first);
    await tester.pump();

    expect(find.text('Unable to open No Link Deal'), findsOneWidget);
  });
}
