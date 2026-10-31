/// One row of the `alert_events` table (plans/p2 MS1), as returned by
/// `GET /alerts/recent`.
///
/// The server is the only author of these rows: the stream consumer writes them
/// when a price event happens, and this model only decodes them and derives
/// display values. Nothing here invents an event — a missing price stays null
/// and renders as "no price line", never 0, because a 0 would read as a deal
/// that did not happen.
class AlertEvent {
  /// `alert_events.id` — a UUID under PostgreSQL, an INTEGER under the SQLite
  /// fixtures, a string on the wire either way. Opaque: the app echoes it back
  /// to `POST /alerts/{id}/open` and never parses it.
  final String id;

  /// One of `price_drop`, `threshold_crossed`, `lowest_price_changed`,
  /// `back_in_stock` — the consumer's `VALID_EVENT_TYPES`.
  final String eventType;

  /// Local-currency amounts, the same units `formatPrice` renders (jنيه / EGP).
  /// `referencePriceEgp` is the price the event moved away from, when known.
  final double? priceEgp;
  final double? referencePriceEgp;
  final double? discountPct;

  final String storeId;
  final String category;
  final String sku;

  /// The tracked product's URL, stored by the server ONLY when it matches
  /// `tracked_item_stores.store_url` for that item — so a card can hand a
  /// merchant tap to `MerchantLink` without trusting payload-authored links.
  /// Empty means "no trustworthy URL for this event".
  final String url;

  /// Null means the user has not tapped this alert yet (`opened_at IS NULL`).
  /// The server writes it on `POST /alerts/{id}/open`, idempotently: the first
  /// tap wins, which is what the opened/unopened ratio Gate 2 measures.
  final DateTime? openedAt;
  final DateTime createdAt;

  /// False when the row carried no parseable `created_at`. The repository
  /// drops those rows instead of showing them as "Today": a feed item that
  /// cannot be placed on a timeline is not displayable.
  final bool hasCreatedAt;

  AlertEvent({
    required this.id,
    required this.eventType,
    this.priceEgp,
    this.referencePriceEgp,
    this.discountPct,
    this.storeId = '',
    this.category = '',
    this.sku = '',
    this.url = '',
    this.openedAt,
    required this.createdAt,
    this.hasCreatedAt = true,
  });

  factory AlertEvent.fromJson(Map<String, dynamic> json) {
    final created = _datetime(json['created_at']);
    return AlertEvent(
      id: _string(json['id']),
      eventType: _string(json['event_type']),
      priceEgp: _number(json['price_egp']),
      referencePriceEgp: _number(json['reference_price_egp']),
      discountPct: _number(json['discount_pct']),
      storeId: _string(json['store_id']),
      category: _string(json['category']),
      sku: _string(json['sku']),
      url: _string(json['url']),
      openedAt: _datetime(json['opened_at']),
      // `createdAt` stays non-null so callers never branch on null; the
      // `hasCreatedAt` flag is what tells the repository to drop the row.
      createdAt: created ?? DateTime.now(),
      hasCreatedAt: created != null,
    );
  }

  /// Whether the user has tapped this alert yet.
  bool get isUnopened => openedAt == null;

  /// Whole days between the event and [now], clamped at zero: the card turns
  /// 0 into the "Today" key and anything else into "{days} days ago". A
  /// future-dated row reads as 0 rather than a negative label.
  int daysAgo(DateTime now) {
    final diff = now.difference(createdAt);
    if (diff.isNegative) return 0;
    return diff.inDays;
  }

  /// Whether the card may offer a merchant tap at all.
  bool get hasUrl => url.isNotEmpty;
}

/// The event types the consumer will ever store
/// (`services/api/alert_events_consumer.py::VALID_EVENT_TYPES`). Kept as
/// constants so the card's glyph mapping and the tests cannot drift from the
/// server's enum by spelling it three times. A value outside this set keeps
/// its row (the feed is the server's story) and renders without a glyph.
const String eventTypePriceDrop = 'price_drop';
const String eventTypeThresholdCrossed = 'threshold_crossed';
const String eventTypeLowestPriceChanged = 'lowest_price_changed';
const String eventTypeBackInStock = 'back_in_stock';

/// Display label for a server `store_id` (`compumarts_eg` -> `Compumarts`).
/// Brand names are brand names: never localized, never translated.
String alertStoreLabel(String storeId) {
  final cleaned = storeId.replaceAll(RegExp(r'_eg$'), '');
  if (cleaned.isEmpty) return '';
  final label = cleaned.replaceAll('_', ' ');
  return label.replaceFirst(label[0], label[0].toUpperCase());
}

String _string(Object? value) =>
    value is String ? value : (value?.toString() ?? '');

double? _number(Object? value) {
  if (value is double) return value;
  if (value is int) return value.toDouble();
  if (value is String) return double.tryParse(value);
  return null;
}

DateTime? _datetime(Object? value) {
  if (value is String) return DateTime.tryParse(value);
  return null;
}
