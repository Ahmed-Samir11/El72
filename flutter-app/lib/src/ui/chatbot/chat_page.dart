import 'dart:math';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../l10n/app_localizations.dart';
import '../../data/models/chat_message_model.dart';
import '../../data/repositories/chatbot_repository.dart';
import '../../data/providers.dart';
import '../chatbot/chat_widgets.dart';
import '../chatbot/search_result_card.dart';

/// Main chat screen for searching products and adding them to the feed.
///
/// The user types a natural-language query (e.g. "gaming laptop under 50000 EGP"),
/// the chatbot searches across all supported stores, and results are displayed
/// with an "Add to Feed" button that creates a tracked item via the API service.
///
/// Authentication: all requests include the stored JWT access token as a
/// Bearer header (added by [ChatbotRepository]). The chatbot validates the
/// token and resolves the user_id from the token's `sub` claim (phone number)
/// by looking up the user in the shared operational database. The client never
/// supplies a user_id.
class ChatPage extends ConsumerWidget {
  const ChatPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repository = ref.read(chatbotRepositoryProvider);
    return _ChatPageBody(repository: repository);
  }
}

/// Stateful UI for the chat page. Holds all mutable state (messages, input,
/// session id, sending flag).
class _ChatPageBody extends StatefulWidget {
  final ChatbotRepository repository;

  const _ChatPageBody({required this.repository, super.key});

  @override
  State<_ChatPageBody> createState() => _ChatPageBodyState(repository);
}

class _ChatPageBodyState extends State<_ChatPageBody> {
  final TextEditingController _controller = TextEditingController();
  final List<ChatMessageModel> _messages = [];
  final List<SearchResultModel> _searchResults = [];
  bool _isSending = false;
  String? _sessionId;

  final ChatbotRepository _repository;

  _ChatPageBodyState(this._repository);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  /// Generate a cryptographically secure random UUID v4 string.
  /// Used for message IDs and session IDs.
  String _generateUuid() {
    final random = Random.secure();
    final bytes = List<int>.generate(16, (_) => random.nextInt(256));
    // Set version (4) and variant (10) bits per UUID v4 spec
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    final sb = StringBuffer();
    for (int i = 0; i < 16; i++) {
      sb.write(bytes[i].toRadixString(16).padLeft(2, '0'));
      if (i == 3 || i == 5 || i == 7 || i == 9) {
        sb.write('-');
      }
    }
    return sb.toString();
  }

  /// Generate a client-side session ID using a cryptographically secure
  /// random UUID v4 format.
  /// The server validates the session exists and belongs to the authenticated
  /// user (derived from the JWT).
  String _generateSessionId() => _generateUuid();

  /// Send a message to the chatbot and handle the response.
  Future<void> _sendMessage() async {
    if (!mounted) return;

    final text = _controller.text.trim();
    if (text.isEmpty) return;

    // Generate or reuse session ID
    _sessionId ??= _generateSessionId();

    // Add user message optimistically — use UUID to avoid collisions
    final userMsg = ChatMessageModel(
      id: _generateUuid(),
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
      final response = await _repository.sendMessage(
        sessionId: _sessionId!,
        message: text,
      );

      if (!mounted) return;

      // Adopt the server's session ID — the server may create a new session
      // if the client-generated ID didn't match an existing one.
      _sessionId = response.sessionId;

      // Add bot message — use UUID to avoid collisions
      final botMsg = ChatMessageModel(
        id: _generateUuid(),
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
      if (!mounted) return;

      // Log the detailed error for debugging, show generic message to user
      debugPrint('Chatbot error: $e');

      if (e is UnauthorizedException) {
        // Token expired or invalid — prompt re-authentication.
        setState(() => _isSending = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(e.message),
          ),
        );
        return;
      }

      final errorMsg = ChatMessageModel(
        id: _generateUuid(),
        sessionId: _sessionId ?? '',
        role: 'bot',
        content:
            'Sorry, I couldn\'t process your request. Please try again.',
        createdAt: DateTime.now(),
      );
      setState(() {
        _messages.add(errorMsg);
        _isSending = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('An error occurred. Please try again.'),
        ),
      );
    }
  }

  /// Handle "Add to Feed" tap on a search result.
  Future<void> addToFeed(SearchResultModel result) async {
    if (!mounted) return;

    // Defensive null guard: session ID must be set before adding to feed
    if (_sessionId == null) {
      debugPrint('addToFeed called without a session ID');
      return;
    }

    setState(() => _isSending = true);

    try {
      await _repository.addToFeed(
        sessionId: _sessionId!,
        productUrl: result.url,
      );

      if (!mounted) return;

      // Show success
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'Tracker created for "${result.title}". You will be notified on price changes.',
          ),
        ),
      );
    } catch (e) {
      if (!mounted) return;

      // Log the detailed error for debugging
      debugPrint('Add to feed error: $e');

      if (e is UnauthorizedException) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e.message)),
        );
        return;
      }

      // Surface insufficient-credits errors specifically so the user
      // knows to purchase credits or check their balance.
      if (e is InsufficientCreditsException) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(e.toString()),
          ),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to add tracker. Please try again.'),
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isSending = false);
      }
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
          // Message list — Expanded so it fills available height
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

          // Search results from the last bot response.
          // Bounded height so it doesn't conflict with the Expanded message list.
          if (_searchResults.isNotEmpty)
            Container(
              constraints: BoxConstraints(
                maxHeight: MediaQuery.of(context).size.height * 0.3,
              ),
              child: Padding(
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
                          onAddToFeed: () => addToFeed(result),
                          isEnabled: !_isSending,
                        );
                      },
                    ),
                  ],
                ),
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
