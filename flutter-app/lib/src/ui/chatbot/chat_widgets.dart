import 'package:flutter/material.dart';

import '../../../l10n/app_localizations.dart';
import '../../data/models/chat_message_model.dart';

/// A single chat message bubble.
class ChatMessageBubble extends StatelessWidget {
  const ChatMessageBubble({
    super.key,
    required this.message,
    required this.isUser,
  });

  final ChatMessageModel message;
  final bool isUser;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.8,
        ),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: isUser
              ? Theme.of(context).colorScheme.primaryContainer
              : Theme.of(context).colorScheme.surfaceContainer,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Text(
          message.content,
          textDirection: message.language == 'ar'
              ? TextDirection.rtl
              : TextDirection.ltr,
          style: Theme.of(context).textTheme.bodyMedium,
        ),
      ),
    );
  }
}

/// A "typing" indicator shown when the bot is thinking.
class BotTypingIndicator extends StatelessWidget {
  const BotTypingIndicator({super.key});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        children: [
          const Icon(Icons.chat_bubble, size: 16, color: Colors.grey),
          const SizedBox(width: 6),
          Text(
            AppLocalizations.of(context).botTyping,
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

/// A button to start a new chat session.
class NewChatButton extends StatelessWidget {
  const NewChatButton({super.key, required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return FilledButton(
      onPressed: onPressed,
      child: Text(AppLocalizations.of(context).newChat),
    );
  }
}
