import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/l10n/app_localizations.dart';
import 'package:elhaq_tracker/src/core/styles/app_theme.dart';
import 'package:elhaq_tracker/src/data/models/chat_message_model.dart';
import 'package:elhaq_tracker/src/data/providers.dart';
import 'package:elhaq_tracker/src/data/repositories/chatbot_repository.dart';
import 'package:elhaq_tracker/src/ui/chatbot/chat_page.dart';
import 'package:elhaq_tracker/src/ui/chatbot/search_result_card.dart';

/// Returns a fixed search response without touching the network.
class _FakeChatbotRepository extends ChatbotRepository {
  _FakeChatbotRepository(this.results);

  final List<SearchResultModel> results;

  @override
  Future<ChatResponseModel> sendMessage({
    required String sessionId,
    required String message,
  }) async {
    return ChatResponseModel(
      message: 'I found ${results.length} products',
      sessionId: sessionId,
      searchResults: results,
    );
  }
}

SearchResultModel _result(int i) => SearchResultModel(
  storeId: '2b_egypt',
  storeName: '2B Egypt',
  title: 'Samsung Odyssey G5 27" 2K Monitor $i',
  price: 8399.0 + i,
  currency: 'EGP',
  url: 'https://2b.com.eg/en/product-$i.html',
  imageUrl: '',
  inStock: true,
);

Widget _app(ProviderContainer container, Widget home) {
  return UncontrolledProviderScope(
    container: container,
    child: MaterialApp(
      theme: AppTheme.light(),
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: const [Locale('en'), Locale('ar')],
      home: home,
    ),
  );
}

ProviderContainer _container(List<SearchResultModel> results) {
  final container = ProviderContainer(
    overrides: [
      chatbotRepositoryProvider.overrideWithValue(
        _FakeChatbotRepository(results),
      ),
    ],
  );
  addTearDown(container.dispose);
  return container;
}

void main() {
  testWidgets('search results render as cards with an add button', (
    tester,
  ) async {
    final results = List.generate(3, _result);
    await tester.pumpWidget(_app(_container(results), const ChatPage()));

    await tester.enterText(find.byType(TextField), '2k monitor under 12k');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pumpAndSettle();

    // A layout failure (e.g. an unbounded ListView) would surface here.
    expect(tester.takeException(), isNull);
    expect(find.byType(SearchResultCard), findsWidgets);
    expect(find.text('Samsung Odyssey G5 27" 2K Monitor 0'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Add to Feed'), findsWidgets);
    // The input stays on screen below the results.
    expect(find.byType(TextField), findsOneWidget);
  });

  testWidgets('chat survives leaving and returning to the tab', (
    tester,
  ) async {
    final container = _container(List.generate(2, _result));
    await tester.pumpWidget(_app(container, const ChatPage()));

    await tester.enterText(find.byType(TextField), '2k monitor under 12k');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), 'unsent draft');

    // Switching tabs disposes the chat page (the dashboard rebuilds tabs).
    await tester.pumpWidget(_app(container, const SizedBox()));
    expect(find.byType(ChatPage), findsNothing);
    await tester.pumpWidget(_app(container, const ChatPage()));
    await tester.pumpAndSettle();

    expect(find.text('2k monitor under 12k'), findsOneWidget);
    expect(find.text('I found 2 products'), findsOneWidget);
    expect(find.byType(SearchResultCard), findsNWidgets(2));
    expect(find.text('unsent draft'), findsOneWidget);
  });
}
