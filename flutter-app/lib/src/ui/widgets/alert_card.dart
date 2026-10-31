import 'package:flutter/material.dart';

import '../../../l10n/app_localizations.dart';
import '../../core/format/price_format.dart';
import '../../core/styles/app_colors.dart';
import '../../core/styles/app_theme.dart';
import '../../data/models/alert_event_model.dart';
import '../common/merchant_link.dart';

/// One event in the Alerts tab (plans/p2 MS2).
///
/// The card never claims a channel: no push, no WhatsApp, no email. It says
/// what the server recorded (a price event on a product this user tracks), shows
/// the prices that moved, and taps through [MerchantLink] so the departure is
/// attributable (`affiliate_clicks.source = 'alert_card'`, report §11's
/// per-surface CTR).
///
/// Riverpod-free by design: the tab owns the provider and injects [onOpened],
/// so a card cannot invalidate state behind its own back button.
class AlertCard extends StatelessWidget {
  final AlertEvent event;

  /// Injected in tests; production uses the shared link (one Dio pool).
  final MerchantLink merchantLink;

  /// Called when the card is tapped, before the merchant opens: the tab uses
  /// it to `POST /alerts/{id}/open` and invalidate its feed. Null for cards
  /// shown without a tab (previews), which then cannot mark anything opened.
  final void Function(String eventId)? onOpened;

  AlertCard({
    super.key,
    required this.event,
    MerchantLink? merchantLink,
    this.onOpened,
  }) : merchantLink = merchantLink ?? MerchantLink.shared;

  @override
  Widget build(BuildContext context) {
    final tokens = context.appTokens;
    final colorScheme = Theme.of(context).colorScheme;
    final locale = Localizations.localeOf(context);
    final strings = AppLocalizations.of(context);
    final store = alertStoreLabel(event.storeId);

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      elevation: event.isUnopened ? 2 : 0,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () async {
          // Taken before any await: the resolve request can outlive the card,
          // and re-looking the messenger up on a disposed context throws
          // (same rule as the deal and search-result cards).
          final messenger = ScaffoldMessenger.of(context);

          // Bookkeeping first, and never blocking the tap: a failed open-mark
          // (offline, rate-limited, an id that is no longer mine) must not
          // stop the merchant from opening. The feed refresh is the tab's
          // business, so it happens in the callback.
          if (event.id.isNotEmpty) onOpened?.call(event.id);

          if (!event.hasUrl) {
            // No trustworthy URL for this event: the server only stores `url`
            // when it matches tracked_item_stores.store_url for that item, so
            // a card without one must not invent a destination. State it.
            if (!context.mounted) return;
            messenger.showSnackBar(
              SnackBar(content: Text(strings.alertNoLink)),
            );
            return;
          }

          final opened = await merchantLink.open(
            targetUrl: event.url,
            source: sourceAlertCard,
            sku: event.sku.isEmpty ? null : event.sku,
          );
          if (!opened) {
            if (!context.mounted) return;
            messenger.showSnackBar(
              SnackBar(
                content: Text(strings.unableToOpen(store.isEmpty ? event.sku : store)),
              ),
            );
          }
        },
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(
                    _glyph(event.eventType),
                    size: 22,
                    color: _glyphColor(event.eventType, tokens),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      store.isEmpty ? event.category : store,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(
                        context,
                      ).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  // Un-opened marker. Counted by the server's badge; shown per
                  // card so a long list does not hide which rows are new.
                  if (event.isUnopened)
                    Icon(
                      Icons.circle,
                      size: 10,
                      color: colorScheme.primary,
                    ),
                ],
              ),
              const SizedBox(height: 8),

              // The prices that moved. A null price renders NO line at all:
              // "0" would read as a price that never existed.
              if (event.referencePriceEgp != null)
                Text(
                  strings.alertPreviousPrice(
                    formatPrice(event.referencePriceEgp!, locale: locale),
                  ),
                  style: TextStyle(
                    fontSize: 14,
                    color: colorScheme.onSurfaceVariant,
                    decoration: TextDecoration.lineThrough,
                  ),
                ),
              if (event.priceEgp != null)
                Text(
                  strings.alertCurrentPrice(
                    formatPrice(event.priceEgp!, locale: locale),
                  ),
                  style: AppColors.priceTextStyle(
                    colorScheme.onSurface,
                  ).copyWith(fontSize: 18, fontWeight: FontWeight.bold),
                ),
              if (event.discountPct != null)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                    strings.alertDiscountLine(
                      event.discountPct!.toStringAsFixed(0),
                    ),
                    style: TextStyle(
                      fontSize: 12,
                      color: tokens.priceDown,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),

              const SizedBox(height: 8),
              Text(
                _whenLabel(context, event),
                style: TextStyle(
                  fontSize: 12,
                  color: colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// "Today" for an event from the current day, otherwise the counted form.
/// The count comes from [AlertEvent.daysAgo], never from a formatted date, so
/// the label matches the server's UTC day arithmetic that dedupes events.
String _whenLabel(BuildContext context, AlertEvent event) {
  final days = event.daysAgo(DateTime.now());
  if (days <= 0) return AppLocalizations.of(context).alertWhenToday;
  return AppLocalizations.of(context).alertWhenDaysAgo(days.toString());
}

/// The event-type glyph. Unknown types keep their row and fall back to a
/// neutral mark rather than disappearing from the feed.
IconData _glyph(String eventType) {
  switch (eventType) {
    case eventTypePriceDrop:
      return Icons.trending_down;
    case eventTypeThresholdCrossed:
      return Icons.flag;
    case eventTypeLowestPriceChanged:
      return Icons.arrow_downward;
    case eventTypeBackInStock:
      return Icons.shopping_bag;
    default:
      return Icons.help_outline;
  }
}

Color _glyphColor(String eventType, AppThemeData tokens) {
  // A drop is the money the user gains; a return to stock is neutral. Colours
  // come from the theme's own price tokens so dark and light stay in step.
  switch (eventType) {
    case eventTypePriceDrop:
    case eventTypeLowestPriceChanged:
    case eventTypeThresholdCrossed:
      return tokens.priceDown;
    default:
      return tokens.info;
  }
}
