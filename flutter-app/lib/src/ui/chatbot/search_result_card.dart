import 'package:flutter/material.dart';

import '../../../l10n/app_localizations.dart';
import '../../core/format/price_format.dart';
import '../../core/format/toast_title.dart';
import '../../core/styles/app_colors.dart';
import '../../data/models/chat_message_model.dart';
import '../common/merchant_link.dart';
import '../widgets/product_image.dart';

/// A single product search result with an "Add to Feed" button.
///
/// Shows the product image, title, store and price like the tracker/deal
/// cards. Tapping the card opens the product page; tapping "Add to Feed"
/// creates a tracked item (price monitor) via the chatbot service.
class SearchResultCard extends StatelessWidget {
  SearchResultCard({
    super.key,
    required this.result,
    required this.onAddToFeed,
    this.isEnabled = true,
    MerchantLink? merchantLink,
  }) : merchantLink = merchantLink ?? MerchantLink.shared;

  final SearchResultModel result;
  final VoidCallback onAddToFeed;
  final bool isEnabled;

  /// The component that resolves the tap through the affiliate redirect
  /// before opening it (plan p1). Injected in tests; the default performs
  /// the real resolve + external-browser launch.
  final MerchantLink merchantLink;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final colorScheme = Theme.of(context).colorScheme;
    final locale = Localizations.localeOf(context);

    void unableToOpen(ScaffoldMessengerState messenger) {
      // The title is scraped, so it can be a paragraph with newlines. The
      // chat page's own toasts already bound it; the card must not be the
      // path that leaves a hostile title unbounded.
      messenger.showSnackBar(
        SnackBar(content: Text(l10n.unableToOpen(toastTitle(result.title)))),
      );
    }

    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () async {
          // Taken before any await: if the user navigates away while the browser
          // is starting, this context is no longer in the tree and looking the
          // messenger up again would throw; the instance taken now is still the
          // live one.
          final messenger = ScaffoldMessenger.of(context);
          // The url was scraped out of a third-party page, so it may be empty,
          // malformed or not a web address at all (`file:`, `data:`, some app's
          // custom scheme). Only absolute http/https may leave the app; anything
          // else is reported instead of being handed to another program.
          if (!result.isLaunchable) {
            unableToOpen(messenger);
            return;
          }
          // Resolve through GET /affiliate/redirect first: the opened URL
          // carries the store's affiliate tag and the tap writes an
          // attributable affiliate_clicks row (plan p1, Gate 3). On any
          // resolve failure MerchantLink falls back to the original URL,
          // so attribution can never block the user's tap; it returns false
          // only for a URL that must not be handed to a browser at all.
          final opened = await merchantLink.open(
            targetUrl: result.url,
            source: sourceSearchResult,
          );
          // The resolve request can outlive the card: if the chat page was
          // disposed while it was in flight, the captured messenger belongs
          // to a disposed ScaffoldMessenger and showSnackBar would throw.
          if (!opened && context.mounted) {
            unableToOpen(messenger);
          }
        },
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              ProductImage(imageUrl: result.imageUrl, size: 64),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      result.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      result.storeName,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      result.price > 0
                          ? formatPrice(result.price, locale: locale)
                          : '—',
                      style: AppColors.priceTextStyle(
                        colorScheme.onSurface,
                      ).copyWith(fontSize: 16, fontWeight: FontWeight.bold),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              FilledButton(
                // The tracker is created from this url, so an unopenable url
                // cannot be tracked either — the button is disabled with it.
                onPressed: (isEnabled && result.isLaunchable)
                    ? onAddToFeed
                    : null,
                child: Text(l10n.addToFeed),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
