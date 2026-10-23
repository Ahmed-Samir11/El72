import 'package:flutter/material.dart';

import '../../../l10n/app_localizations.dart';
import '../../data/repositories/chatbot_repository.dart';
import '../../data/models/chat_message_model.dart';
import '../../data/models/search_result_model.dart';
import '../chatbot/chat_widgets.dart';
import '../chatbot/search_result_card.dart';

/// Main chat screen for searching products and adding them to the feed.
///
/// The user types a natural-language query (e.g. "gaming laptop under 50000 EGP"),
/// the chatbot searches across all supported stores, and results are displayed
/// with an "Add to Feed" button that creates a tracked item via the API service.
class ChatPage extends StatefulWidget {
  const ChatPage({super.key});

  @override
  State<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends State<ChatPage> {
  final TextEditingController _controller = TextEditingController();
  final List<ChatMessageModel> _messages = [];
  final List<SearchResultModel> _searchResults = [];
  bool _isSending = false;
  int? _sessionId;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  /// Generate a random session ID for this chat session.
  int _generateSessionId() {
    final now = DateTime.now();
    return (now.millisecondsSinceEpoch % 1000000).abs();
  }

  /// Send a message to the chatbot and handle the response.
  Future<void> _sendMessage() async {
    final text = _controller.text.trim();
    if (text.isEmpty) return;

    // Generate or reuse session ID
    _sessionId ??= _generateSessionId();

    // Add user message optimistically
    final userMsg = ChatMessageModel(
      id: _messages.length + 1,
      sessionId: _sessionId!,
      role: 'user',
      content: text,
      createdAt: DateTime.now(),
    );
    setState(() {
      _messages.add(userMsg);
      _searchResults.clear();
      _isSending = true;
    });
    _controller.clear();

    try {
      final repository = ChatbotRepository();
      final response = await repository.sendMessage(
        sessionId: _sessionId!,
        userId: 1, // TODO: Replace with actual user ID from auth
        message: text,
      );

      // Add bot message
      final botMsg = ChatMessageModel(
        id: _messages.length + 1,
        sessionId: _sessionId!,
        role: 'bot',
        content: response.message,
        createdAt: DateTime.now(),
      );
      setState(() {
        _messages.add(botMsg);
        _searchResults.addAll(response.searchResults);
        _isSending = false;
      });
    } catch (e) {
      final errorMsg = ChatMessageModel(
        id: _messages.length + 1,
        sessionId: _sessionId!,
        role: 'bot',
        content: 'Sorry, I couldn\'t process your request. Please try again.',
        createdAt: DateTime.now(),
      );
      setState(() {
        _messages.add(errorMsg);
        _isSending = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Error: $e')),
      );
    }
  }

  /// Handle "Add to Feed" tap on a search result.
  Future<void> _addToFeed(SearchResultModel result) async {
    // Send "add to feed" to the chatbot, which creates a tracker via the API.
    setState(() => _isSending = true);

    try {
      final repository = ChatbotRepository();
      await repository.sendMessage(
        sessionId: _sessionId!,
        userId: 1, // TODO: Replace with actual user ID from auth
        message: 'add to feed',
      );

      // Show success
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '${AppLocalizations.of(context).trackerCreated} "${result.title}"',
          ),
        ),
      );
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'Failed to add tracker: $e',
          ),
        ),
      );
    } finally {
      setState(() => _isSending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.chatTitle),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () {
              _controller.clear();
              setState(() {
                _messages.clear();
                _searchResults.clear();
                _sessionId = null;
              });
            },
          ),
        ],
      ),
      body: Column(
        children: [
          // Message list
          Expanded(
            child: _messages.isEmpty
                ? Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Icon(Icons.chat, size: 48, color: Colors.grey),
                        const SizedBox(height: 12),
                        Text(
                          l10n.noMessagesYet,
                          style: Theme.of(context).textTheme.bodyMedium,
                          textAlign: TextAlign.center,
                        ),
                      ],
                    ),
                  )
                : ListView.builder(
                    itemCount: _messages.length,
                    itemBuilder: (context, index) {
                      final msg = _messages[index];
                      return ChatMessageBubble(
                        message: msg,
                        isUser: msg.role == 'user',
                      );
                    },
                  ),
          ),

          // Search results from the last bot response
          if (_searchResults.isNotEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    l10n.searchResults,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 8),
                  ListView.builder(
                    itemCount: _searchResults.length,
                    itemBuilder: (context, index) {
                      final result = _searchResults[index];
                      return SearchResultCard(
                        result: result,
                        onAddToFeed: () => _addToFeed(result),
                      );
                    },
                  ),
                ],
              ),
            ),

          // Bot typing indicator
          if (_isSending)
            BotTypingIndicator(),

          // Input area
          Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _controller,
                    decoration: InputDecoration(
                      hintText: l10n.searchHint,
                      border: const OutlineInputBorder(),
                      contentPadding:
                          const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                    ),
                    onSubmitted: (_) => _sendMessage(),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton(
                  icon: const Icon(Icons.send),
                  onPressed: _isSending ? null : _sendMessage,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}


