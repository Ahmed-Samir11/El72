import 'package:flutter/foundation.dart';

import 'chat_message_model.dart';

/// Mutable state of the chat tab, kept across tab switches.
///
/// Held by `chatConversationProvider` rather than the chat page's [State],
/// so leaving the tab (which disposes the page) keeps the messages, the
/// latest search results, the unsent draft and the session. A reply that
/// arrives while the tab is not visible is still recorded here and shown
/// when the user comes back.
class ChatConversation extends ChangeNotifier {
  /// Cap on the messages held in memory. The conversation object lives for the
  /// whole app run, so an ever-growing list is a slow leak; the server keeps the
  /// full history regardless. Oldest messages are dropped first.
  static const int maxMessages = 200;

  /// Cap on the results kept from one search. The service answers with a handful
  /// per store; an oversized or hostile response must not be kept alive for the
  /// whole run. The list is ranked best-first, so the extras are the weakest.
  /// One constant, shared with the parser in `chat_message_model.dart`: the
  /// reply is now cut while it is parsed, and trimming here afterwards is the
  /// same limit seen from the other side, so the two cannot drift apart.
  static const int maxSearchResults = maxParsedSearchResults;

  final List<ChatMessageModel> _messages = [];
  final List<SearchResultModel> _searchResults = [];

  // Whether this conversation has been disposed by its provider.
  //
  // Logout, the demo account and similar flows invalidate
  // `chatConversationProvider`, which disposes the instance a page may still
  // hold while its tab is off screen. The flag is the only signal left for an
  // in-flight reply: `identical()` stays true and the revision counter dies with
  // the object, so without it a disposed chat could still be written into.
  // Read-only from outside: only [dispose] may set it.
  bool _isDisposed = false;

  /// Bumped whenever the conversation is cleared while a reply is in flight.
  /// A caller captures it before sending and ignores the response when the value
  /// no longer matches — a chat the user reset must not be repopulated by a
  /// message they abandoned.
  int _revision = 0;

  // Server session id and unsent draft. Both are mutable only by the chat UI,
  // which is the sole writer in `lib/`; the setters below exist so that a
  // disposed conversation cannot be resurrected by a late write from a page
  // whose tab is off screen.
  String? _sessionId;
  String _draft = '';

  bool _isSending = false;

  List<ChatMessageModel> get messages => List.unmodifiable(_messages);

  List<SearchResultModel> get searchResults =>
      List.unmodifiable(_searchResults);

  bool get isDisposed => _isDisposed;

  /// Server session id; null until the first message is sent.
  String? get sessionId => _sessionId;

  set sessionId(String? value) {
    if (_isDisposed) return;
    _sessionId = value;
  }

  /// Text typed into the input but not sent yet. Not notified: the page's
  /// text field already shows it.
  String get draft => _draft;

  set draft(String value) {
    if (_isDisposed) return;
    _draft = value;
  }

  bool get isSending => _isSending;

  /// The revision an in-flight request was started under. Compare it with
  /// [revision] when the reply lands.
  int get revision => _revision;

  set isSending(bool value) {
    if (isDisposed || value == _isSending) return;
    _isSending = value;
    notifyListeners();
  }

  void addMessage(ChatMessageModel message) {
    if (isDisposed) return;
    _messages.add(message);
    if (_messages.length > maxMessages) {
      _messages.removeRange(0, _messages.length - maxMessages);
    }
    notifyListeners();
  }

  void setSearchResults(List<SearchResultModel> results) {
    if (isDisposed) return;
    _searchResults
      ..clear()
      ..addAll(
        results.length <= maxSearchResults
            ? results
            : results.sublist(0, maxSearchResults),
      );
    notifyListeners();
  }

  /// Start a new chat: drop messages, results, draft and session.
  ///
  /// Note: a reset abandons the reply that is already on the wire — it is
  /// recognised as stale and dropped when it lands — but it does not cancel the
  /// HTTP request itself. The service still finishes answering and still bills
  /// that call. Cancelling would need a per-request `AbortSignal`/`Dio` token
  /// threaded through the repository, which is out of scope here.
  void reset() {
    if (isDisposed) return;
    _messages.clear();
    _searchResults.clear();
    sessionId = null;
    draft = '';
    // A reset also abandons the reply that may still be arriving: the typing
    // indicator must stop, and the pending response has to be recognisable as
    // stale to whoever sent it.
    _isSending = false;
    _revision++;
    notifyListeners();
  }

  @override
  void dispose() {
    // The provider disposes this on invalidation, and callers may dispose it
    // directly (tests, an account teardown). Flutter's ChangeNotifier asserts
    // against a second dispose, and because Riverpod wraps the call in
    // runGuarded the assertion would be swallowed into an uncaught zone error
    // instead of failing loudly. Being idempotent removes that trap.
    if (_isDisposed) return;
    _isDisposed = true;
    super.dispose();
  }
}
