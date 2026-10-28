import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/l10n/app_localizations.dart';
import 'package:elhaq_tracker/src/core/format/toast_title.dart';
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
    bool holdAdd = false,
    Exception? addFailure,
    String? addExplanation,
  }) : _results = results ?? const [],
       _trackerCreated = trackerCreated,
       _holdReply = holdReply,
       _holdAdd = holdAdd,
       _addFailure = addFailure,
       _addExplanation = addExplanation,
       super();

  final List<SearchResultModel> _results;
  final bool _trackerCreated;
  final bool _holdReply;
  final bool _holdAdd;
  final Exception? _addFailure;
  final String? _addExplanation;

  final Completer<ChatResponseModel> _release = Completer<ChatResponseModel>();
  final Completer<ChatResponseModel> _releaseAdd =
      Completer<ChatResponseModel>();

  int _addToFeedCalls = 0;
  int get addToFeedCalls => _addToFeedCalls;

  int _sendMessageCalls = 0;
  int get sendMessageCalls => _sendMessageCalls;

  // What the page handed the service, so a test can tell "bounded inside the
  // app" apart from "truncated before it left".
  int _lastSentLength = 0;
  int get lastSentLength => _lastSentLength;

  @override
  Future<ChatResponseModel> sendMessage({
    required String sessionId,
    required String message,
  }) async {
    _sendMessageCalls++;
    _lastSentLength = message.length;
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

  /// Lets a held tracker answer land. Used by the reset-mid-add test.
  void releaseAdd() {
    if (!_releaseAdd.isCompleted) {
      _releaseAdd.complete(
        ChatResponseModel(
          message: 'Tracker created! Samsung Odyssey G5 27" 2K Monitor 0',
          sessionId: 'late',
          searchResults: [_result(1)],
          trackerCreated: true,
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
    if (_holdAdd) {
      await _releaseAdd.future;
    }
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

    // The toast shows the copy the app owns and both locales already translate,
    // not the English sentence baked into the exception. The exception text stays
    // in the log line the page writes for the failure.
    expect(
      find.text(
        'You\'ve used all your available price trackers. '
        'Upgrade your plan to keep tracking prices and get more trackers.',
      ),
      findsOneWidget,
    );
    // The typing indicator is gone: the add finished, it did not hang.
    expect(find.byType(BotTypingIndicator), findsNothing);
  });

  testWidgets('no live send path is left open while a reply is in flight', (
    tester,
  ) async {
    // The send button is disabled once a request starts, and so must the input
    // submit path: a keyboard Enter that lands during that window would spend
    // another credit on the same session and interleave two answers into one chat.
    final repository = _FakeChatbotRepository(
      results: List.generate(2, _result),
      holdReply: true,
    );
    final container = _containerWith(repository);
    await tester.pumpWidget(_app(container, const ChatPage()));

    await tester.enterText(find.byType(TextField), '2k monitor under 12k');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pump();

    // Both ways out of the field are closed for the duration of the request.
    final field = tester.widget<TextField>(find.byType(TextField));
    expect(field.onSubmitted, isNull);
    final button = tester.widget<IconButton>(
      find.widgetWithIcon(IconButton, Icons.send),
    );
    expect(button.onPressed, isNull);

    // And the request that is in flight is still exactly one.
    await tester.tap(find.byIcon(Icons.send));
    await tester.pumpAndSettle();
    expect(repository.sendMessageCalls, 1);
    expect(find.byType(BotTypingIndicator), findsOneWidget);
  });

  testWidgets('a page-sized failure explanation becomes one bounded toast', (
    tester,
  ) async {
    // The service's explanation of an add that created nothing is remote text,
    // and a hostile upstream can answer with a page of it: the toast must stay
    // one line whatever arrives.
    final repository = _FakeChatbotRepository(
      results: List.generate(1, _result),
      trackerCreated: false,
      addExplanation: "couldn't reach the store\n" * 200,
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
    expect(toast.length, lessThanOrEqualTo(maxToastTitleLength));
    expect(toast.contains('\n'), false);
    expect(toast.endsWith('…'), true);
    expect(find.textContaining('Tracker created for'), findsNothing);
  });

  testWidgets(
    'a conversation the provider already retired still paints a chat tab',
    (tester) async {
      // Logout disposes the conversation the tab was showing. A page built in
      // that same tick is handed the dead instance, and ChangeNotifier refuses
      // listeners after dispose, which used to take the tab down before it
      // painted.
      final container = _containerWith(
        _FakeChatbotRepository(results: List.generate(1, _result)),
      );
      final dead = container.read(chatConversationProvider);
      // The state logout leaves behind: the provider still hands out the
      // instance, but the conversation itself has been retired.
      dead.dispose();
      await tester.pumpWidget(_app(container, const ChatPage()));

      expect(find.byType(TextField), findsOneWidget);
      expect(find.text('Chat'), findsWidgets);

      // And the tab ignores it: tapping send neither crashes nor sends.
      await tester.tap(find.byIcon(Icons.send));
      await tester.pumpAndSettle();
    },
  );

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

  testWidgets('resetting while a tracker request is in flight drops it', (
    tester,
  ) async {
    final repository = _FakeChatbotRepository(
      results: [_result(1)],
      trackerCreated: true,
      holdAdd: true,
    );
    final container = _containerWith(repository);
    await tester.pumpWidget(_app(container, const ChatPage()));

    await _send(tester, 'gaming monitor');
    await _addToFeed(tester);

    // The user clears the chat while the tracker request is still running.
    await tester.tap(find.byIcon(Icons.refresh));
    await tester.pumpAndSettle();

    expect(find.text('No messages yet. Start a conversation.'), findsOneWidget);
    expect(find.byType(BotTypingIndicator), findsNothing);
    expect(find.byType(SnackBar), findsNothing);

    repository.releaseAdd();
    await tester.pumpAndSettle();

    // The abandoned answer must not announce a tracker into a chat the user
    // cleared: a toast naming a tracker whose result card is gone reads as a
    // phantom success.
    expect(find.byType(SnackBar), findsNothing);
    expect(find.text('Tracker created!'), findsNothing);
    expect(find.text('No messages yet. Start a conversation.'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('a reply that lands after logout is kept out of the new chat', (
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

    // Logout invalidates the provider mid-flight: the old chat is disposed and
    // the page rebinds to a brand-new one whose revision counter restarts at 0
    // — the same value the request was started under, which is why staleness
    // has to be decided by object identity as well as by revision.
    final retired = container.read(chatConversationProvider);
    container.invalidate(chatConversationProvider);
    await tester.pumpAndSettle();

    expect(retired.isDisposed, isTrue);
    final live = container.read(chatConversationProvider);
    expect(identical(live, retired), isFalse);
    expect(live.revision, retired.revision);

    repository.releaseReply();
    await tester.pumpAndSettle();

    // The retired instance still holds the turn the user typed before logging
    // out — invalidating drops the chat from the provider, it does not blank the
    // object a page may still be holding. What must not happen is the late
    // answer landing in either chat.
    expect(retired.messages.length, 1);
    expect(retired.messages.single.content, '2k monitor under 12k');
    expect(live.messages, isEmpty);
    expect(live.searchResults, isEmpty);
    expect(find.text('A reply that arrived late'), findsNothing);
    expect(find.text('2k monitor under 12k'), findsNothing);
    expect(find.byType(SearchResultCard), findsNothing);
    expect(find.text('No messages yet. Start a conversation.'), findsOneWidget);
    expect(tester.takeException(), isNull);
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

  testWidgets(
    'a result is only trackable once the chat has a usable session id',
    (tester) async {
      final results = List.generate(1, _result);
      final container = _containerWith(
        _FakeChatbotRepository(results: results),
      );
      await tester.pumpWidget(_app(container, const ChatPage()));

      // Results without a session: the tracker a tap creates inherits the
      // current session, so there is nothing to inherit yet.
      container.read(chatConversationProvider).setSearchResults(results);
      await tester.pumpAndSettle();

      expect(find.byType(SearchResultCard), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Add to Feed'),
            )
            .onPressed,
        isNull,
        reason:
            'a tap would be dropped deeper in addToFeed, looking like a '
            'dead button',
      );

      // Sending a query establishes the session; the same card becomes live.
      await _send(tester, '2k monitor under 12k');
      expect(
        ChatbotRepository.isSessionId(
          container.read(chatConversationProvider).sessionId ?? '',
        ),
        true,
      );
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Add to Feed'),
            )
            .onPressed,
        isNotNull,
      );
    },
  );

  testWidgets('a tap that lands on a disposed conversation issues no request', (
    tester,
  ) async {
    final repository = _FakeChatbotRepository(results: [_result(1)]);
    final container = _containerWith(repository);
    await tester.pumpWidget(_app(container, const ChatPage()));

    await _send(tester, 'gaming monitor');
    await _addToFeed(tester);
    expect(repository.sendMessageCalls, 1);
    expect(repository.addToFeedCalls, 1);

    // Signing out disposes the conversation the page is wired to. A queued
    // tap must not spend an API call against it: its session id is dead, and
    // the guarded sessionId setter would silently drop a new id while the
    // request still went out carrying a freshly generated one. The provider
    // is left alone on purpose, so the page keeps showing the retired chat
    // and its buttons still route to the disposed instance.
    container.read(chatConversationProvider).dispose();
    expect(container.read(chatConversationProvider).isDisposed, isTrue);

    await tester.tap(find.byIcon(Icons.send));
    await tester.pump();
    await _addToFeed(tester);
    await tester.pumpAndSettle();

    expect(
      repository.sendMessageCalls,
      1,
      reason: 'a disposed conversation must not receive chat requests',
    );
    expect(
      repository.addToFeedCalls,
      1,
      reason: 'a disposed conversation must not receive tracker requests',
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('a refusal toast truncates a hostile scraped title', (
    tester,
  ) async {
    final nasty = 'Monitor\n\n${'x' * 300}';
    await tester.pumpWidget(
      _app(
        _containerWith(_FakeChatbotRepository(results: [])),
        Scaffold(
          body: Center(
            child: SearchResultCard(
              result: SearchResultModel(
                storeId: '2b_egypt',
                storeName: '2B Egypt',
                title: nasty,
                price: 100.0,
                currency: 'EGP',
                url: 'javascript:alert(1)',
                imageUrl: '',
                inStock: true,
              ),
              onAddToFeed: () {},
              isEnabled: true,
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.byType(InkWell).first);
    await tester.pump();

    // 'Monitor ' plus 300 x's folds onto one line, is cut at 80 characters
    // and gets the ellipsis, so the toast stays bounded and single-line.
    final filler = 'x' * 71;
    expect(find.text('Unable to open Monitor $filler…'), findsOneWidget);
  });

  testWidgets('a pasted wall of text is bounded where the app keeps it', (
    tester,
  ) async {
    final repository = _FakeChatbotRepository();
    final container = _containerWith(repository);
    await tester.pumpWidget(_app(container, const ChatPage()));

    // Typed text is not remote text, so it never passes through the model
    // parser that clips what the service hands over. Untyped it would sit in
    // the draft and in the chat history for as long as the signed-in session
    // lives, which is what makes the "keep the last 200 turns" cap dishonest.
    final pasted = 'x' * (maxChatContentLength + 5000);

    // Typing without sending: the draft is the copy re-shown when the tab is
    // reopened, so it is stored bounded.
    await tester.enterText(find.byType(TextField), pasted);
    await tester.pump();
    expect(
      container.read(chatConversationProvider).draft.length,
      maxChatContentLength,
      reason: 'the retained draft must not be the whole paste',
    );

    // Sending it: the history keeps a bounded copy of the user's turn...
    await tester.tap(find.byIcon(Icons.send));
    await tester.pumpAndSettle();
    final messages = container.read(chatConversationProvider).messages;
    expect(messages.first.role, 'user');
    expect(messages.first.content.length, maxChatContentLength);
    expect(tester.takeException(), isNull);

    // ...while the service still receives what the user actually typed. The
    // bound is on what the app retains, not on what the user may submit.
    expect(repository.lastSentLength, pasted.length);
  });
}
