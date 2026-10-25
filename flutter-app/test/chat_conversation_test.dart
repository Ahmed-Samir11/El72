import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/data/models/chat_conversation.dart';
import 'package:elhaq_tracker/src/data/models/chat_message_model.dart';

ChatMessageModel _message(int i) => ChatMessageModel(
  id: 'id-$i',
  sessionId: 'session-1',
  role: 'user',
  content: 'message $i',
  createdAt: DateTime.utc(2026, 10, 24),
);

SearchResultModel _result(int i) => SearchResultModel(
  storeId: '2b_egypt',
  storeName: '2B Egypt',
  title: 'Monitor $i',
  price: 1000.0 + i,
  currency: 'EGP',
  url: 'https://2b.com.eg/p/$i',
  imageUrl: '',
  inStock: true,
);

void main() {
  test('the chat holds a bounded history and drops the oldest first', () {
    final chat = ChatConversation();
    for (var i = 0; i < ChatConversation.maxMessages + 7; i++) {
      chat.addMessage(_message(i));
    }

    // The conversation lives for the whole app run, so an unbounded list is a
    // slow leak; the cap trims from the front, the half the user is least likely
    // to still be reading, and keeps the newest exchanges intact.
    expect(chat.messages.length, ChatConversation.maxMessages);
    expect(chat.messages.first.content, 'message 7');
    expect(
      chat.messages.last.content,
      'message ${ChatConversation.maxMessages + 6}',
    );
  });

  test('reset empties the chat and marks in-flight replies stale', () {
    final chat = ChatConversation()
      ..addMessage(_message(0))
      ..draft = 'half typed'
      ..sessionId = 'session-1';
    chat.isSending = true;
    final revisionUnderRequest = chat.revision;

    chat.reset();

    expect(chat.messages, isEmpty);
    expect(chat.searchResults, isEmpty);
    expect(chat.sessionId, isNull);
    expect(chat.draft, isEmpty);
    // The typing indicator must not stay lit on a chat the user cleared...
    expect(chat.isSending, isFalse);
    // ...and the request that was still arriving is recognisable as abandoned.
    expect(chat.revision, revisionUnderRequest + 1);
  });

  test('a disposed conversation ignores late writes', () {
    final chat = ChatConversation()..addMessage(_message(0));
    final revision = chat.revision;

    // Invalidating chatConversationProvider disposes the instance, while a chat
    // page whose tab is off screen keeps holding it. A reply that lands after
    // that must not resurrect a chat that no longer exists, and must not trip
    // ChangeNotifier's use-after-dispose guard.
    chat.dispose();
    expect(chat.isDisposed, isTrue);

    chat
      ..addMessage(_message(1))
      ..reset();
    chat.isSending = true;

    expect(chat.messages.length, 1);
    expect(chat.messages.first.content, 'message 0');
    expect(chat.revision, revision);
    expect(chat.isSending, isFalse);
  });
  test('a hostile search response is trimmed to the strongest results', () {
    final chat = ChatConversation();

    chat.setSearchResults(
      List.generate(ChatConversation.maxSearchResults + 30, _result),
    );

    // The service answers with a handful per store; the extras are the weakest
    // ranked, and keeping all of them alive for the whole app run is a leak.
    expect(chat.searchResults.length, ChatConversation.maxSearchResults);
    expect(chat.searchResults.first.title, 'Monitor 0');
    expect(
      chat.searchResults.last.title,
      'Monitor ${ChatConversation.maxSearchResults - 1}',
    );
  });
}
