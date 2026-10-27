import 'dart:math';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../l10n/app_localizations.dart';
import '../../core/format/toast_title.dart';
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
/// Fallback shown when adding a result to the feed failed and neither the
/// service nor the exception explained why.
//
// NOTE(i18n): this needs a key in `app_en.arb` + `app_ar.arb`. The Arabic half
// is left to a native speaker — see the i18n rule in `.agents/AGENTS.md`.
const addTrackerFailedText = 'Failed to add tracker. Please try again.';

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
    // A conversation the provider already disposed has no listeners left to
    // take off; asking a disposed ChangeNotifier to forget one is a use-after-
    // dispose of the very object the replacement is meant to leave behind.
    if (!oldWidget.conversation.isDisposed) {
      oldWidget.conversation.removeListener(_onConversationChanged);
    }
    // A replacement instance is normally live, but wiring a listener to one
    // that was disposed in the same tick would throw before the page could
    // repaint; the next rebuild attaches it again.
    if (!widget.conversation.isDisposed) {
      widget.conversation.addListener(_onConversationChanged);
    }
    // The draft belongs to the conversation, so show the new instance's draft.
    _controller.text = widget.conversation.draft;
  }

  @override
  void dispose() {
    if (!_conversation.isDisposed) {
      _conversation.removeListener(_onConversationChanged);
    }
    _controller.dispose();
    super.dispose();
  }

  void _saveDraft() {
    if (_conversation.isDisposed) return;
    _conversation.draft = _controller.text;
  }

  void _onConversationChanged() {
    if (mounted) setState(() {});
  }

  /// Whether a reply that lands now still belongs to the conversation its
  /// request was sent against.
  //
  /// Three ways it can stop belonging: [ChatConversation.reset] (the refresh
  /// button, or a logout) bumps [ChatConversation.revision]; an invalidated
  /// provider replaces the instance outright; and a page whose tab is off screen
  /// keeps holding an instance the provider has already disposed. Either way the
  /// answer must be dropped, not written back into a chat the user cleared or
  /// that no longer exists.
  bool _isCurrent(ChatConversation conversation, int revision) =>
      identical(conversation, _conversation) &&
      !conversation.isDisposed &&
      conversation.revision == revision;

  /// A log line for a failed chat request, without the request itself.
  //
  /// A DioException's text carries the request URL and, for some failure kinds,
  /// its headers — the Bearer token belongs neither in the app's logs nor in a
  /// bug report attached to them.
  String _errorSummary(Object error) {
    if (error is DioException) {
      final status = error.response?.statusCode;
      final suffix = status == null ? '' : ', HTTP $status';
      return 'chat request failed (${error.type.name}$suffix)';
    }
    return error.toString();
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

    // Captured up front: the conversation outlives this page, so a reply that
    // arrives after the user switched tabs is still recorded there; only the
    // snackbars need a mounted page.
    final conversation = _conversation;
    final revision = conversation.revision;

    // A disposed conversation (logout, demo-mode toggle) must not receive a
    // request at all. `sessionId`'s setter silently drops writes once the
    // instance is disposed, so a `conversation.sessionId ??= generate()` here
    // would still hand a fresh id to the service and burn credits on a chat
    // nobody is looking at. Read the id, generate one only if the conversation
    // is still live, and write it back through the guarded setter.
    if (conversation.isDisposed) return;
    var sessionId = conversation.sessionId;
    if (sessionId == null) {
      sessionId = _generateSessionId();
      conversation.sessionId = sessionId;
    }

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

      // Adopt the server's session id only when it has the shape of one: the
      // value arrives from a remote reply and is reused as a path segment later,
      // so a poisoned id is dropped here instead of failing deeper in the stack.
      if (ChatbotRepository.isSessionId(response.sessionId)) {
        conversation.sessionId = response.sessionId;
      } else {
        debugPrint('Ignoring a chatbot session id that is not a UUID');
      }

      // Add bot message — use UUID to avoid collisions
      conversation.addMessage(
        ChatMessageModel(
          id: _generateUuid(),
          sessionId: conversation.sessionId ?? '',
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
      debugPrint('Chatbot error: ${_errorSummary(e)}');

      if (!_isCurrent(conversation, revision)) return;
      conversation.isSending = false;

      if (e is UnauthorizedException) {
        // Token expired or invalid — prompt re-authentication, in the chat as
        // well as in a toast: a tab that is off screen now is reopened to a
        // conversation whose reply otherwise vanished without a trace. Only the
        // toast needs a mounted page.
        conversation.addMessage(
          ChatMessageModel(
            id: _generateUuid(),
            sessionId: conversation.sessionId ?? '',
            role: 'bot',
            content: e.message,
            createdAt: DateTime.now(),
          ),
        );
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

    // The card disables the button when a result's url is not an openable web
    // address, but this is the call that asks the service to create a tracker,
    // so it re-checks: the url was scraped out of a third-party page, and the
    // UI guard is defence in depth, not the only one.
    if (!result.isLaunchable) {
      debugPrint('Refusing to track a url that is not an http/https address');
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            // Titles come from scraped pages and can be arbitrarily long or
            // carry newlines; the success toast below already goes through
            // [toastTitle] for the same reason, so the refusal must not be
            // the one path that dumps a raw page title into a snackbar.
            AppLocalizations.of(context).unableToOpen(toastTitle(result.title)),
          ),
        ),
      );
      return;
    }

    final conversation = _conversation;
    final revision = conversation.revision;

    // A disposed conversation must not receive a tracker request either: its
    // session id is dead and the user is looking at another account's chat.
    if (conversation.isDisposed) return;

    // A session must exist for the tracker to inherit it. The id is checked
    // for shape as well as presence: an empty or poisoned value would otherwise
    // travel to the service and come back as a confusing failure.
    final sessionId = conversation.sessionId;
    if (sessionId == null || !ChatbotRepository.isSessionId(sessionId)) {
      debugPrint('addToFeed called without a usable session id');
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
      // results") is shown instead of a success toast. A blank explanation would
      // be a toast that says nothing, so the generic failure line is used.
      if (!response.trackerCreated) {
        final reason = response.message.trim();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(reason.isEmpty ? addTrackerFailedText : reason),
          ),
        );
        return;
      }

      // Localized success text plus the product the user tapped: which result
      // became a tracker has to be visible when the list carries several.
      final l10n = AppLocalizations.of(context);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('${l10n.trackerCreated}\n${toastTitle(result.title)}'),
        ),
      );
    } catch (e) {
      if (!_isCurrent(conversation, revision)) return;
      if (!mounted) return;

      // Log a summary that carries no request details
      debugPrint('Add to feed error: ${_errorSummary(e)}');

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
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(addTrackerFailedText)));
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
    // The tracker a result creates inherits the current session, so the button
    // is only offered once a usable session id exists. Without this the tap
    // would be silently dropped deeper in [addToFeed], which looks like a dead
    // button rather than a disabled one.
    final canAddToFeed =
        !isSending &&
        ChatbotRepository.isSessionId(_conversation.sessionId ?? '');

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
                            isEnabled: canAddToFeed,
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
