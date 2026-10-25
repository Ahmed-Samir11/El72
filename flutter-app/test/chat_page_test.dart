import 'dart:async';

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
import 'package:elhaq_tracker/src/ui/chatbot/chat_widgets.dart';
import 'package:elhaq_tracker/src/ui/chatbot/search_result_card.dart';

/// Returns fixed chatbot answers without touching the network.
///
/// [holdReply] keeps `sendMessage` waiting until the test releases it, which is
/// how a reply that lands after the user reset the chat is exercised.
/// [trackerCreated] drives the add-to-feed outcome, exactly as the service
/// does: 200 either way, the flag says whether a tracker exists.
/// [addFailure] makes the add-to-feed call throw the domain exception the
/// repository maps an HTTP status to.
/// [addExplanation] overrides the sentence the service returns for an add that
/// did not create a tracker (an empty string means "the server said nothing").
class _FakeChatbotRepository extends ChatbotRepository {
  _FakeChatbotRepository({
    List<SearchResultModel>? results,
    bool trackerCreated = false,
    bool holdReply = false,
    Exception? addFailure,
    String? addExplanation,
  }) : _results = results ?? const [],
       _trackerCreated = trackerCreated,
       _holdReply = holdReply,
       _addFailure = addFailure,
       _addExplanation = addExplanation,
       super();

  final List<SearchResultModel> _results;
  final bool _trackerCreated;
  final bool _holdReply;
  final Exception? _addFailure;
  final String? _addExplanation;

  final Completer<ChatResponseModel> _release = Completer<ChatResponseModel>();

  int _addToFeedCalls = 0;
  int get addToFeedCalls => _addToFeedCalls;

  @override
  Future<ChatResponseModel> sendMessage({
    required String sessionId,
    required String message,
  }) async {
    final response = ChatResponseModel(
      message: 'I found ${_results.length} products',
      sessionId: sessionId,
      searchResults: _results,
    );
    if (_holdReply) {
      await _release.future;
    }
    return response;
  }

  /// Lets a held reply land. Used by the reset test.
  void releaseReply() {
    if (!_release.isCompleted) {
      _release.complete(
        ChatResponseModel(
          message: 'A reply that arrived late',
          sessionId: 'late',
          searchResults: _results,
        ),
      );
    }
  }

  @override
  Future<ChatResponseModel> addToFeed({
    required String sessionId,
    String? productUrl,
    double? targetPrice,
  }) async {
    _addToFeedCalls++;
    if (_addFailure != null) throw _addFailure;
    return ChatResponseModel(
      message:
          _addExplanation ??
          (_trackerCreated ? 'Tracker created' : 'No results were added.'),
      sessionId: sessionId,
      searchResults: _results.isEmpty ? const [] : _results.sublist(0, 1),
      trackerCreated: _trackerCreated,
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

ProviderContainer _containerWith(ChatbotRepository repository) {
  final container = ProviderContainer(
    overrides: [chatbotRepositoryProvider.overrideWithValue(repository)],
  );
  addTearDown(container.dispose);
  return container;
}

/// Types a query and sends it, then waits for the reply.
Future<void> _send(WidgetTester tester, String text) async {
  await tester.enterText(find.byType(TextField), text);
  await tester.tap(find.byIcon(Icons.send));
  await tester.pumpAndSettle();
}

/// Tap the first result card's "Add to Feed" button.
Future<void> _addToFeed(WidgetTester tester) async {
  await tester.tap(find.widgetWithText(FilledButton, 'Add to Feed').first);
  await tester.pump();
}

void main() {
  testWidgets('search results render as cards with an add button', (
    tester,
  ) async {
    final results = List.generate(3, _result);
    final container = _containerWith(_FakeChatbotRepository(results: results));
    await tester.pumpWidget(_app(container, const ChatPage()));

    await _send(tester, '2k monitor under 12k');

    // A layout failure (e.g. an unbounded ListView) would surface here.
    expect(tester.takeException(), isNull);
    expect(find.byType(SearchResultCard), findsWidgets);
    expect(find.text('Samsung Odyssey G5 27" 2K Monitor 0'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Add to Feed'), findsWidgets);
    // The input stays on screen below the results.
    expect(find.byType(TextField), findsOneWidget);
  });

  testWidgets('chat survives leaving and returning to the tab', (tester) async {
    final results = List.generate(2, _result);
    final container = _containerWith(_FakeChatbotRepository(results: results));
    await tester.pumpWidget(_app(container, const ChatPage()));

    await _send(tester, '2k monitor under 12k');
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

  testWidgets('a created tracker announces itself, not a result count', (
    tester,
  ) async {
    final repository = _FakeChatbotRepository(
      results: List.generate(1, _result),
      trackerCreated: true,
    );
    final container = _containerWith(repository);
    await tester.pumpWidget(_app(container, const ChatPage()));

    await _send(tester, '2k monitor under 12k');
    await _addToFeed(tester);
    await tester.pumpAndSettle();

    expect(repository.addToFeedCalls, 1);
    final toast =
        (tester.widget<SnackBar>(find.byType(SnackBar)).content as Text).data ??
        '';
    // Localized success text, and which of the several results became a tracker.
    expect(toast, contains('Tracker created!'));
    expect(toast, contains('Samsung Odyssey G5 27" 2K Monitor 0'));
  });

  testWidgets('an add refusal that explains nothing still says it failed', (
    tester,
  ) async {
    final repository = _FakeChatbotRepository(
      results: List.generate(1, _result),
      addExplanation: '',
    );
    final container = _containerWith(repository);
    await tester.pumpWidget(_app(container, const ChatPage()));

    await _send(tester, '2k monitor under 12k');
    await _addToFeed(tester);
    await tester.pumpAndSettle();

    // A toast reading "" would look like a success that did nothing.
    final toast =
        (tester.widget<SnackBar>(find.byType(SnackBar)).content as Text).data ??
        '';
    expect(toast, isNot(isEmpty));
    expect(toast, contains('Failed to add tracker'));
  });

  testWidgets('a failed add shows the chatbot explanation, not success', (
    tester,
  ) async {
    // The service echoes the product back even when it created nothing, so
    // only tracker_created may announce success.
    final repository = _FakeChatbotRepository(
      results: List.generate(1, _result),
      trackerCreated: false,
    );
    final container = _containerWith(repository);
    await tester.pumpWidget(_app(container, const ChatPage()));

    await _send(tester, '2k monitor under 12k');
    await _addToFeed(tester);
    await tester.pumpAndSettle();

    expect(repository.addToFeedCalls, 1);
    expect(find.text('No results were added.'), findsOneWidget);
    expect(find.textContaining('Tracker created for'), findsNothing);
  });

  testWidgets('running out of credits while adding says so', (tester) async {
    final repository = _FakeChatbotRepository(
      results: List.generate(1, _result),
      addFailure: const InsufficientCreditsException(
        'You have run out of credits. Purchase a plan to create trackers.',
      ),
    );
    final container = _containerWith(repository);
    await tester.pumpWidget(_app(container, const ChatPage()));

    await _send(tester, '2k monitor under 12k');
    await _addToFeed(tester);
    await tester.pumpAndSettle();

    expect(
      find.text(
        'You have run out of credits. Purchase a plan to create trackers.',
      ),
      findsOneWidget,
    );
    // The typing indicator is gone: the add finished, it did not hang.
    expect(find.byType(BotTypingIndicator), findsNothing);
  });

  testWidgets('resetting while a reply is in flight drops the reply', (
    tester,
  ) async {
    final repository = _FakeChatbotRepository(
      results: List.generate(2, _result),
      holdReply: true,
    );
    final container = _containerWith(repository);
    await tester.pumpWidget(_app(container, const ChatPage()));

    await tester.enterText(find.byType(TextField), '2k monitor under 12k');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pump();

    // The user clears the chat while the search is still running.
    await tester.tap(find.byIcon(Icons.refresh));
    await tester.pumpAndSettle();

    expect(find.text('No messages yet. Start a conversation.'), findsOneWidget);
    // reset() also abandons the request, so no typing indicator is left.
    expect(find.byType(BotTypingIndicator), findsNothing);

    // The abandoned answer arrives afterwards and must not come back.
    repository.releaseReply();
    await tester.pumpAndSettle();

    expect(find.text('A reply that arrived late'), findsNothing);
    expect(find.text('2k monitor under 12k'), findsNothing);
    expect(find.byType(SearchResultCard), findsNothing);
    expect(find.text('No messages yet. Start a conversation.'), findsOneWidget);
  });

  testWidgets('an invalidated conversation is replaced, not kept', (
    tester,
  ) async {
    final repository = _FakeChatbotRepository(
      results: List.generate(2, _result),
    );
    final container = _containerWith(repository);
    await tester.pumpWidget(_app(container, const ChatPage()));

    await _send(tester, '2k monitor under 12k');
    expect(find.text('I found 2 products'), findsOneWidget);

    // logout/demo invalidates chatConversationProvider; the page must bind to
    // the new instance instead of the disposed one it captured.
    final before = container.read(chatConversationProvider);
    container.invalidate(chatConversationProvider);
    await tester.pumpAndSettle();

    expect(before.isDisposed, true);
    expect(identical(container.read(chatConversationProvider), before), false);
    expect(find.text('No messages yet. Start a conversation.'), findsOneWidget);
    expect(find.byType(SearchResultCard), findsNothing);

    // Typing into the replaced chat drives the draft listener of the live
    // instance; a page still wired to the disposed one trips ChangeNotifier's
    // use-after-dispose guard here.
    await tester.enterText(find.byType(TextField), 'still typing');
    await tester.pump();
    expect(container.read(chatConversationProvider).draft, 'still typing');
  });
}
