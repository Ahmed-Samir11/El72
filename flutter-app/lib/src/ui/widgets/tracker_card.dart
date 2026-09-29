import 'package:flutter/material.dart';

import '../../../l10n/app_localizations.dart';
import '../../core/format/price_format.dart';
import '../../core/styles/app_colors.dart';
import '../../core/styles/app_theme.dart';
import 'product_image.dart';

/// Product tracker row.
///
/// [hasPrice] drives the pending-price state: when false the card shows a
/// hourglass placeholder and a warning tint, signalling that the background
/// price fetch has not produced a price yet. Callers must pass it explicitly
/// rather than relying on a magic `currentPrice <= 0` check.
class TrackerCard extends StatelessWidget {
  final String imageUrl;
  final String title;
  final double currentPrice;
  final double targetPrice;
  final bool hasPrice;
  final bool isActive;
  final VoidCallback? onTap;

  const TrackerCard({
    super.key,
    required this.imageUrl,
    required this.title,
    required this.currentPrice,
    required this.targetPrice,
    required this.hasPrice,
    required this.isActive,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final tokens = context.appTokens;
    final colorScheme = Theme.of(context).colorScheme;
    final locale = Localizations.localeOf(context);

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: InkWell(
        onTap: onTap,
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
                        ] else ...[
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 8,
                              vertical: 4,
                            ),
                            decoration: BoxDecoration(
                              color: tokens.warning.withValues(alpha: 0.12),
                              borderRadius: BorderRadius.circular(6),
                              border: Border.all(
                                color: tokens.warning.withValues(alpha: 0.4),
                              ),
                            ),
                            child: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                SizedBox(
                                  width: 12,
                                  height: 12,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                    color: tokens.warning,
                                  ),
                                ),
                                const SizedBox(width: 6),
                                Text(
                                  AppLocalizations.of(context).fetchingPrice,
                                  style: TextStyle(
                                    fontSize: 12,
                                    fontWeight: FontWeight.w600,
                                    color: tokens.warning,
                                  ),
                                ),
                              ],
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
