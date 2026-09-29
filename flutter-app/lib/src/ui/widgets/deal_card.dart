import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../l10n/app_localizations.dart';
import '../../core/format/price_format.dart';
import '../../core/styles/app_colors.dart';
import '../../core/styles/app_theme.dart';
import '../../data/models/deal_model.dart';
import 'product_image.dart';

class DealCard extends StatelessWidget {
  final Deal deal;

  const DealCard({super.key, required this.deal});

  @override
  Widget build(BuildContext context) {
    final tokens = context.appTokens;
    final colorScheme = Theme.of(context).colorScheme;
    final locale = Localizations.localeOf(context);

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      elevation: 2,
      child: InkWell(
        onTap: () async {
          final uri = Uri.tryParse(deal.sourceUrl);
          if (uri == null || !await launchUrl(uri)) {
            if (!context.mounted) return;
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(
                  AppLocalizations.of(context).unableToOpen(deal.title),
                ),
              ),
            );
          }
        },
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              ProductImage(imageUrl: deal.imageUrl, size: 60),
              const SizedBox(width: 16),

              // Center Content
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Title
                    Text(
                      deal.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 4),

                    // Store Name
                    Text(
                      deal.storeName,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 16),

              // Right Content
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  // Price
                  Text(
                    formatPrice(deal.price, locale: locale),
                    style: AppColors.priceTextStyle(
                      colorScheme.onSurface,
                    ).copyWith(fontSize: 18, fontWeight: FontWeight.bold),
                  ),

                  // Original Price (strikethrough)
                  if (deal.originalPrice > deal.price)
                    Text(
                      formatPrice(deal.originalPrice, locale: locale),
                      style: TextStyle(
                        fontSize: 14,
                        color: colorScheme.onSurfaceVariant,
                        decoration: TextDecoration.lineThrough,
                      ),
                    ),

                  const SizedBox(height: 8),

                  // Discount Badge
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 4,
                    ),
                    decoration: BoxDecoration(
                      color: tokens.priceDown,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      '-${deal.discountPercentage.toStringAsFixed(0)}%',
                      style: TextStyle(
                        color: colorScheme.onPrimary,
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
