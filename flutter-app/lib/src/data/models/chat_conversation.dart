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
  final List<ChatMessageModel> _messages = [];
  final List<SearchResultModel> _searchResults = [];

  /// Server session id; null until the first message is sent.
  String? sessionId;

  /// Text typed into the input but not sent yet. Not notified: the page's
  /// text field already shows it.
  String draft = '';

  bool _isSending = false;

  List<ChatMessageModel> get messages => List.unmodifiable(_messages);

  List<SearchResultModel> get searchResults =>
      List.unmodifiable(_searchResults);

  bool get isSending => _isSending;

  set isSending(bool value) {
    if (_isSending == value) return;
    _isSending = value;
    notifyListeners();
  }

  void addMessage(ChatMessageModel message) {
    _messages.add(message);
    notifyListeners();
  }

  void setSearchResults(List<SearchResultModel> results) {
    _searchResults
      ..clear()
      ..addAll(results);
    notifyListeners();
  }

  /// Start a new chat: drop messages, results, draft and session.
  void reset() {
    _messages.clear();
    _searchResults.clear();
    sessionId = null;
    draft = '';
    notifyListeners();
  }
}
