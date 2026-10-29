import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/l10n/app_localizations.dart';
import 'package:elhaq_tracker/src/core/styles/app_theme.dart';
import 'package:elhaq_tracker/src/data/models/chat_message_model.dart';
import 'package:elhaq_tracker/src/ui/chatbot/search_result_card.dart';
import 'package:elhaq_tracker/src/ui/common/merchant_link.dart';

SearchResultModel _withUrl(String url) => SearchResultModel(
  storeId: '2b_egypt',
  storeName: '2B Egypt',
  title: 'Monitor',
  price: 100.0,
  currency: 'EGP',
  url: url,
  imageUrl: '',
  inStock: true,
);

Widget _cardApp(SearchResultModel result) {
  return MaterialApp(
    theme: AppTheme.light(),
    localizationsDelegates: const [
      AppLocalizations.delegate,
      GlobalMaterialLocalizations.delegate,
      GlobalWidgetsLocalizations.delegate,
      GlobalCupertinoLocalizations.delegate,
    ],
    supportedLocales: const [Locale('en'), Locale('ar')],
    // A Scaffold is required: the card reports a refused launch through the
    // nearest ScaffoldMessenger.
    home: Scaffold(
      body: Center(
        child: SearchResultCard(
          result: result,
          onAddToFeed: () {},
          isEnabled: true,
        ),
      ),
    ),
  );
}

FilledButton _feedButton(WidgetTester tester) =>
    tester.widget<FilledButton>(find.byType(FilledButton));

/// Records the open call and answers with a canned success/failure, standing
/// in for resolve+launch together (the real one hits the API + OS launcher).
class _FakeLink extends MerchantLink {
  _FakeLink({required this.opened});

  final bool opened;
  final List<String> sources = [];

  @override
  Future<bool> open({
    required String targetUrl,
    required String source,
    String? sku,
    String? dealId,
    String? category,
  }) async {
    sources.add(source);
    return opened;
  }
}

Widget _linkedApp(SearchResultModel result, MerchantLink link) {
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
        child: SearchResultCard(
          result: result,
          onAddToFeed: () {},
          isEnabled: true,
          merchantLink: link,
        ),
      ),
    ),
  );
}

void main() {
  testWidgets('a web address is offered for tracking', (tester) async {
    for (final url in const [
      'https://2b.com.eg/en/product.html',
      'http://example.com/product',
    ]) {
      await tester.pumpWidget(_cardApp(_withUrl(url)));
      expect(_withUrl(url).isLaunchable, true, reason: url);
      expect(_feedButton(tester).onPressed, isNotNull, reason: url);
      await tester.pumpWidget(const SizedBox());
    }
  });

  testWidgets(
    'a scraped url that is not a web page is neither offered nor launched',
    (tester) async {
      for (final url in const [
        '',
        'file:///etc/passwd',
        'data:text/html,<script>alert(1)</script>',
        'javascript:alert(1)',
        'app-store://deeplink',
        'not a url',
      ]) {
        await tester.pumpWidget(_cardApp(_withUrl(url)));

        // No tracker can be created from it, so the button is inert...
        expect(_withUrl(url).isLaunchable, false, reason: url);
        expect(_feedButton(tester).onPressed, isNull, reason: url);

        // ...and tapping the card says so instead of handing the address to
        // another program.
        await tester.tap(find.byType(InkWell).first);
        await tester.pump();
        expect(
          find.text('Unable to open Monitor'),
          findsOneWidget,
          reason: url,
        );

        await tester.pumpWidget(const SizedBox());
      }
    },
  );

  testWidgets('a refusal toast never carries a whole scraped title', (
    tester,
  ) async {
    // Titles come from a scraped page and can be arbitrarily long, so the
    // card truncates them the same way the chat page does.
    // 80 characters in total, ellipsis included.
    final filler = 'x' * 71;
    await tester.pumpWidget(
      _cardApp(
        SearchResultModel(
          storeId: '2b_egypt',
          storeName: '2B Egypt',
          title: 'Monitor ${'x' * 200}',
          price: 100.0,
          currency: 'EGP',
          url: 'javascript:alert(1)',
          imageUrl: '',
          inStock: true,
        ),
      ),
    );

    await tester.tap(find.byType(InkWell).first);
    await tester.pump();

    expect(
      find.text('Unable to open Monitor $filler…'),
      findsOneWidget,
      reason: 'the toast must be cut at the shared 80-character limit',
    );
    // The card body still shows the whole title on purpose — it is clipped by
    // the Text widget's maxLines, which bounds the layout, not the string that
    // a snackbar would carry into the rest of the app. So the unbounded-title
    // check has to look inside the toast, not at the page.
    expect(
      find.descendant(
        of: find.byType(SnackBar),
        matching: find.textContaining('x' * 200),
      ),
      findsNothing,
      reason:
          'only the toast is bounded; the card body is clipped by the '
          'Text widget itself',
    );
  });

  testWidgets('a web-address tap resolves through the affiliate link with the '
      'search_result surface before launching', (tester) async {
    final link = _FakeLink(opened: true);
    await tester.pumpWidget(
      _linkedApp(_withUrl('https://2b.com.eg/en/product.html'), link),
    );

    await tester.tap(find.byType(InkWell).first);
    await tester.pump();

    expect(link.sources, const ['search_result']);
    // Success: no failure snackbar.
    expect(find.byType(SnackBar), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('a launch that fails still reports unableToOpen', (tester) async {
    final link = _FakeLink(opened: false);
    await tester.pumpWidget(
      _linkedApp(_withUrl('https://2b.com.eg/en/product.html'), link),
    );

    await tester.tap(find.byType(InkWell).first);
    await tester.pump();

    expect(find.text('Unable to open Monitor'), findsOneWidget);
  });
}
