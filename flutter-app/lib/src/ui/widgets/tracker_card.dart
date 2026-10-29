import 'package:flutter/material.dart';

import '../../../l10n/app_localizations.dart';
import '../../core/format/price_format.dart';
import '../../core/styles/app_colors.dart';
import '../../core/styles/app_theme.dart';
import '../../data/models/tracked_item_model.dart';
import '../common/merchant_link.dart';
import '../../core/url_guard.dart';
import 'product_image.dart';

/// Product tracker row.
///
/// [hasPrice] drives the pending-price state: when false the card shows a
/// status chip instead of a price. Callers must pass it explicitly rather
/// than relying on a magic `currentPrice <= 0` check.
///
/// [fetchStatus] refines the no-price state (backend fetch classification):
/// - `null` → warning "fetching" chip (in flight),
/// - `no_price_found` → error "not a product page" chip (the link is wrong),
/// - any other settled status (`blocked`, `fetch_failed`, or an anomalous
///   `ok`/unknown value without a price) → error "couldn't fetch — tap to
///   retry" chip; settled states never show an endless spinner.
/// [onRetry] is invoked when the card is tapped in a settled-without-price
/// state (falling back to [onTap] when [onRetry] is null).
///
/// [productUrl] enables the "Open product" affordance (plan p1): the highest-
/// intent object in the app must be able to generate attributed merchant
/// clicks. Keep it a secondary affordance (icon + label, not a full-width
/// button) so its CTR stays separable by `source=tracker_card`. Empty
/// [productUrl] renders no action.
class TrackerCard extends StatelessWidget {
  final String imageUrl;
  final String title;
  final double currentPrice;
  final double targetPrice;
  final bool hasPrice;
  final bool isActive;
  final String? fetchStatus;
  final VoidCallback? onTap;
  final VoidCallback? onRetry;
  final String productUrl;
  final String sku;

  /// Injected in tests; the real one resolves through the affiliate redirect
  /// before opening the merchant URL.
  final MerchantLink? merchantLink;

  const TrackerCard({
    super.key,
    required this.imageUrl,
    required this.title,
    required this.currentPrice,
    required this.targetPrice,
    required this.hasPrice,
    required this.isActive,
    this.fetchStatus,
    this.onTap,
    this.onRetry,
    this.productUrl = '',
    this.sku = '',
    this.merchantLink,
  });

  /// True when the card can offer "Open product": a non-empty url that
  /// passes the shared [isHttpUrl] rule. A junk/off-scheme url from a
  /// corrupt mapping renders no action at all instead of one that can only
  /// fail into a snackbar.
  bool get _canOpenProduct => productUrl.isNotEmpty && isHttpUrl(productUrl);

  /// Open the tracked product page at the merchant through [MerchantLink]
  /// (GET /affiliate/redirect first: the tap writes an attributable
  /// affiliate_clicks row and the opened URL carries the store's tag).
  void _openProduct(BuildContext context) async {
    // Messenger captured before the await: the resolve request can outlive
    // the card, and re-looking it up on a disposed context throws.
    final messenger = ScaffoldMessenger.of(context);
    final opened = await (merchantLink ?? MerchantLink.shared).open(
      targetUrl: productUrl,
      source: sourceTrackerCard,
      sku: sku.isEmpty ? null : sku,
    );
    if (!opened && context.mounted) {
      messenger.showSnackBar(
        SnackBar(
          content: Text(AppLocalizations.of(context).unableToOpen(title)),
        ),
      );
    }
  }

  /// True when the backend fetch has SETTLED (non-null status) but no price
  /// exists: blocked, fetch_failed, or an anomalous/unknown status such as
  /// 'ok' without a price row. Such states show a failure chip whose tap
  /// triggers [onRetry]; only `fetchStatus == null` (in flight) shows the
  /// fetching spinner — a settled state must never spin forever.
  bool get _settledWithoutPrice => !hasPrice && fetchStatus != null;

  /// Status chip shown while a tracker has no price: a spinner for the
  /// in-flight "fetching" state, an alert icon for the error states.
  Widget _statusChip(
    BuildContext context,
    String label,
    Color color, {
    required bool fetching,
  }) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (fetching)
            SizedBox(
              width: 12,
              height: 12,
              child: CircularProgressIndicator(strokeWidth: 2, color: color),
            )
          else
            Icon(Icons.error_outline, size: 14, color: color),
          const SizedBox(width: 6),
          Text(
            label,
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: color,
            ),
          ),
        ],
      ),
    );
  }

  /// The trailing "Open product" action: icon + label (NOT a full-width
  /// button — plan p1 keeps its CTR separable and the free tracker free of
  /// purchase-CTA pressure). Its tap opens the product through
  /// [MerchantLink], i.e. through the affiliate redirect (`source=tracker_card`).
  Widget _openProductAction(BuildContext context, ColorScheme colorScheme) {
    return InkWell(
      borderRadius: BorderRadius.circular(6),
      onTap: () => _openProduct(context),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.open_in_new,
              size: 16,
              color: colorScheme.onSurfaceVariant,
            ),
            const SizedBox(width: 4),
            Text(
              AppLocalizations.of(context).openProduct,
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final tokens = context.appTokens;
    final colorScheme = Theme.of(context).colorScheme;
    final locale = Localizations.localeOf(context);

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: InkWell(
        // A settled-without-price failure without an onRetry callback falls
        // back to the normal tap (the card must never become untappable).
        onTap: _settledWithoutPrice ? (onRetry ?? onTap) : onTap,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              ProductImage(imageUrl: imageUrl, size: 60),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        if (currentPrice > 0) ...[
                          Text(
                            formatPrice(currentPrice, locale: locale),
                            style: AppColors.priceTextStyleLarge(
                              colorScheme.onSurface,
                            ),
                          ),
                          const SizedBox(width: 8),
                          Container(
                            width: 8,
                            height: 8,
                            decoration: BoxDecoration(
                              color: isActive ? tokens.success : tokens.error,
                              shape: BoxShape.circle,
                            ),
                          ),
                        ] else if (fetchStatus == FetchStatus.noPriceFound) ...[
                          // Flexible so the message wraps on narrow screens
                          // instead of overflowing the row.
                          Flexible(
                            child: _statusChip(
                              context,
                              AppLocalizations.of(context).notAProductPage,
                              tokens.error,
                              fetching: false,
                            ),
                          ),
                        ] else if (_settledWithoutPrice) ...[
                          // Settled failure (blocked / fetch_failed / an
                          // unknown or contradictory status such as 'ok'
                          // without a price): tap to retry the fetch.
                          Flexible(
                            child: _statusChip(
                              context,
                              AppLocalizations.of(context).priceFetchFailed,
                              tokens.error,
                              fetching: false,
                            ),
                          ),
                        ] else ...[
                          Flexible(
                            child: _statusChip(
                              context,
                              AppLocalizations.of(context).fetchingPrice,
                              tokens.warning,
                              fetching: true,
                            ),
                          ),
                        ],
                      ],
                    ),
                    if (targetPrice > 0) ...[
                      const SizedBox(height: 4),
                      Text(
                        AppLocalizations.of(
                          context,
                        ).targetLabel(formatPrice(targetPrice, locale: locale)),
                        style: TextStyle(
                          fontSize: 14,
                          color: colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              // "Open product": the card's merchant affordance (plan p1). Only
              // rendered when a product URL exists; secondary by design (icon
              // + label) so its CTR stays separable by source.
              if (_canOpenProduct) ...[
                const SizedBox(width: 8),
                _openProductAction(context, colorScheme),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
