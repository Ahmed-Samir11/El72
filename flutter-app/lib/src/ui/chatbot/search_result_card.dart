import 'package:flutter/material.dart';

import '../../../l10n/app_localizations.dart';
import '../../data/models/chat_message_model.dart';

/// A single product search result with an "Add to Feed" button.
///
/// Tapping "Add to Feed" sends an `add to feed` message to the chatbot,
/// which creates a tracked item (price monitor) via the API service.
class SearchResultCard extends StatelessWidget {
  const SearchResultCard({
    super.key,
    required this.result,
    required this.onAddToFeed,
    this.isEnabled = true,
  });

  final SearchResultModel result;
  final VoidCallback onAddToFeed;
  final bool isEnabled;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);

    return Card(
      margin: const EdgeInsets.symmetric(vertical: 8),
      child: ListTile(
        leading: result.imageUrl.isNotEmpty
            ? Image.network(
                result.imageUrl,
                width: 60,
                height: 60,
                fit: BoxFit.cover,
                errorBuilder: (_, __, ___) => const Icon(Icons.shopping_cart),
              )
            : const Icon(Icons.shopping_cart),
        title: Text(result.title, maxLines: 2, overflow: TextOverflow.ellipsis),
        subtitle: Text(
          '${result.storeName} • ${result.price.toStringAsFixed(0)} ${result.currency}',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        trailing: FilledButton(
          onPressed: isEnabled ? onAddToFeed : null,
          child: Text(l10n.addToFeed),
        ),
      ),
    );
  }
}
