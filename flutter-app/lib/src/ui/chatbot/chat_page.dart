import 'dart:math';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../l10n/app_localizations.dart';
import '../../data/models/chat_conversation.dart';
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
    // Watched, not read: logout invalidates chatConversationProvider, and the
    // page must bind to the replacement instance instead of holding the disposed
    // conversation. (Chat state changes also repaint through the state's own
    // listener; this watch only covers provider replacement.)
    final conversation = ref.watch(chatConversationProvider);
    return _ChatPageBody(repository: repository, conversation: conversation);
  }
}

/// Stateful UI for the chat page. The conversation itself (messages,
/// results, draft, session, sending flag) lives in [ChatConversation] so it
/// survives tab switches; this state only owns the text field controller.
class _ChatPageBody extends StatefulWidget {
  final ChatbotRepository repository;
  final ChatConversation conversation;

  const _ChatPageBody({required this.repository, required this.conversation});

  @override
  State<_ChatPageBody> createState() => _ChatPageBodyState();
}

class _ChatPageBodyState extends State<_ChatPageBody> {
  late final TextEditingController _controller;

  ChatbotRepository get _repository => widget.repository;
  ChatConversation get _conversation => widget.conversation;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: _conversation.draft);
    _controller.addListener(_saveDraft);
    _conversation.addListener(_onConversationChanged);
  }

  @override
  void didUpdateWidget(_ChatPageBody oldWidget) {
    super.didUpdateWidget(oldWidget);
    // The conversation lives in a provider that logout (and the demo account)
    // invalidates, so this widget can be rebuilt against a different instance.
    // Re-attach to the new one; the old listener would keep a disposed chat
    // repainting this page forever.
    if (identical(oldWidget.conversation, widget.conversation)) return;
    oldWidget.conversation.removeListener(_onConversationChanged);
    widget.conversation.addListener(_onConversationChanged);
    // The draft belongs to the conversation, so show the new instance's draft.
    _controller.text = widget.conversation.draft;
  }

  @override
  void dispose() {
    _conversation.removeListener(_onConversationChanged);
    _controller.dispose();
    super.dispose();
  }

  void _saveDraft() => _conversation.draft = _controller.text;

  void _onConversationChanged() {
    if (mounted) setState(() {});
  }

  /// Whether a reply that lands now still belongs to the conversation its
  /// request was sent against.
  //
  /// Both ways it can stop belonging: [ChatConversation.reset] (the refresh
  /// button, or a logout) bumps [ChatConversation.revision], and an invalidated
  /// provider replaces the instance outright. Either way the answer must be
  /// dropped, not written back into a chat the user already cleared.
  bool _isCurrent(ChatConversation conversation, int revision) =>
      identical(conversation, _conversation) &&
      conversation.revision == revision;

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

    // Captured up front: the conversation outlives this page, so a reply that
    // arrives after the user switched tabs is still recorded there; only the
    // snackbars need a mounted page.
    final conversation = _conversation;
    final revision = conversation.revision;

    // Generate or reuse session ID
    final sessionId = conversation.sessionId ??= _generateSessionId();

    // Add user message optimistically — use UUID to avoid collisions
    conversation.addMessage(
      ChatMessageModel(
        id: _generateUuid(),
        sessionId: sessionId,
        role: 'user',
        content: text,
        createdAt: DateTime.now(),
      ),
    );
    conversation.setSearchResults(const []);
    conversation.isSending = true;
    _controller.clear();

    try {
      final response = await _repository.sendMessage(
        sessionId: sessionId,
        message: text,
      );

      if (!_isCurrent(conversation, revision)) {
        // The user reset the chat (or logged out) while this was in flight.
        debugPrint('Dropping a chat reply that arrived after its conversation');
        return;
      }

      // Adopt the server's session ID — the server may create a new session
      // if the client-generated ID didn't match an existing one.
      conversation.sessionId = response.sessionId;

      // Add bot message — use UUID to avoid collisions
      conversation.addMessage(
        ChatMessageModel(
          id: _generateUuid(),
          sessionId: response.sessionId,
          role: 'bot',
          content: response.message,
          createdAt: DateTime.now(),
          language: response.language,
        ),
      );
      conversation.setSearchResults(response.searchResults);
      conversation.isSending = false;
    } catch (e) {
      // Log the detailed error for debugging, show generic message to user
      debugPrint('Chatbot error: $e');

      if (!_isCurrent(conversation, revision)) return;
      conversation.isSending = false;

      if (e is UnauthorizedException) {
        // Token expired or invalid — prompt re-authentication.
        if (!mounted) return;
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(e.message)));
        return;
      }

      conversation.addMessage(
        ChatMessageModel(
          id: _generateUuid(),
          sessionId: conversation.sessionId ?? '',
          role: 'bot',
          content: 'Sorry, I couldn\'t process your request. Please try again.',
          createdAt: DateTime.now(),
        ),
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('An error occurred. Please try again.')),
      );
    }
  }

  /// Handle "Add to Feed" tap on a search result.
  Future<void> addToFeed(SearchResultModel result) async {
    if (!mounted) return;

    final conversation = _conversation;
    final revision = conversation.revision;

    // Defensive null guard: session ID must be set before adding to feed
    final sessionId = conversation.sessionId;
    if (sessionId == null) {
      debugPrint('addToFeed called without a session ID');
      return;
    }

    conversation.isSending = true;

    try {
      final response = await _repository.addToFeed(
        sessionId: sessionId,
        productUrl: result.url,
      );

      if (!_isCurrent(conversation, revision)) return;

      if (!mounted) return;

      // The chatbot answers 200 whether or not a tracker was created; tracker_created
      // is the answer, so the service's explanation ("couldn't add", "no
      // results") is shown instead of a success toast.
      if (!response.trackerCreated) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(response.message)));
        return;
      }

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'Tracker created for "${result.title}". You will be notified on price changes.',
          ),
        ),
      );
    } catch (e) {
      if (!_isCurrent(conversation, revision)) return;
      if (!mounted) return;

      // Log the detailed error for debugging
      debugPrint('Add to feed error: $e');

      if (e is UnauthorizedException) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(e.message)));
        return;
      }

      // Surface insufficient-credits errors specifically so the user
      // knows to purchase credits or check their balance.
      if (e is InsufficientCreditsException) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(e.message)));
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to add tracker. Please try again.')),
        );
      }
    } finally {
      if (_isCurrent(conversation, revision)) {
        conversation.isSending = false;
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final messages = _conversation.messages;
    final searchResults = _conversation.searchResults;
    final isSending = _conversation.isSending;

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.chatTitle),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () {
              _controller.clear();
              _conversation.reset();
            },
          ),
        ],
      ),
      body: Column(
        children: [
          // Message list — Expanded so it fills available height
          Expanded(
            child: messages.isEmpty
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
                    itemCount: messages.length,
                    itemBuilder: (context, index) {
                      final msg = messages[index];
                      return ChatMessageBubble(
                        message: msg,
                        isUser: msg.role == 'user',
                      );
                    },
                  ),
          ),

          // Search results from the last bot response.
          // Bounded height so it doesn't conflict with the Expanded message list.
          if (searchResults.isNotEmpty)
            Container(
              constraints: BoxConstraints(
                maxHeight: MediaQuery.of(context).size.height * 0.3,
              ),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      l10n.searchResults,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 8),
                    // Flexible + shrinkWrap: a ListView inside a Column needs a
                    // bounded height, otherwise it throws and renders nothing.
                    Flexible(
                      child: ListView.builder(
                        shrinkWrap: true,
                        itemCount: searchResults.length,
                        itemBuilder: (context, index) {
                          final result = searchResults[index];
                          return SearchResultCard(
                            result: result,
                            onAddToFeed: () => addToFeed(result),
                            isEnabled: !isSending,
                          );
                        },
                      ),
                    ),
                  ],
                ),
              ),
            ),

          // Bot typing indicator
          if (isSending) BotTypingIndicator(),

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
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 12,
                      ),
                    ),
                    onSubmitted: (_) => _sendMessage(),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton(
                  icon: const Icon(Icons.send),
                  onPressed: isSending ? null : _sendMessage,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
