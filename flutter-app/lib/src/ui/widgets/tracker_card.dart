import 'package:flutter/material.dart';

import '../../../l10n/app_localizations.dart';
import '../../core/format/price_format.dart';
import '../../core/styles/app_colors.dart';
import '../../core/styles/app_theme.dart';
import 'product_image.dart';

/// Product tracker row.
///
/// [hasPrice] drives the pending-price state: when false the card shows a
/// status chip instead of a price. Callers must pass it explicitly rather
/// than relying on a magic `currentPrice <= 0` check.
///
/// [fetchStatus] refines the no-price state (backend fetch classification):
/// - `null` (or `ok` with no price yet) → warning "fetching" chip,
/// - `no_price_found` → error "not a product page" chip (the link is wrong),
/// - `blocked` / `fetch_failed` → error "couldn't fetch — tap to retry" chip.
/// [onRetry] is invoked when the card is tapped in a retryable failure state.
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
  });

  /// True when the card shows a retryable failure (tap triggers [onRetry]).
  bool get _retryableFailure =>
      !hasPrice && (fetchStatus == 'blocked' || fetchStatus == 'fetch_failed');

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

  @override
  Widget build(BuildContext context) {
    final tokens = context.appTokens;
    final colorScheme = Theme.of(context).colorScheme;
    final locale = Localizations.localeOf(context);

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: InkWell(
        onTap: _retryableFailure ? onRetry : onTap,
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
                        ] else if (fetchStatus == 'no_price_found') ...[
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
                        ] else if (_retryableFailure) ...[
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
            ],
          ),
        ),
      ),
    );
  }
}
