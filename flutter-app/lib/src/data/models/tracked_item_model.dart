/// Backend fetch-status values for a tracker's store mapping(s), mirroring
/// the Python constants in `services/api/price_fetcher.py` (FETCH_*).
/// `TrackedItem.fetchStatus` is `null` when never fetched / in flight;
/// compare against these constants instead of raw string literals so the
/// allowed states live in one place.
abstract final class FetchStatus {
  /// Price + image extracted successfully.
  static const String ok = 'ok';

  /// Fetched fine but no price on the page — likely not a product link.
  static const String noPriceFound = 'no_price_found';

  /// Store blocked the fetch (bot wall / 403 / 429 / 5xx).
  static const String blocked = 'blocked';

  /// Network/transport failure.
  static const String fetchFailed = 'fetch_failed';

  /// Whether [status] is a failure the user can retry from the card.
  static bool isRetryable(String? status) =>
      status == blocked || status == fetchFailed;
}

/// Model for a tracked item as returned by `GET /tracked-items`.
///
/// The list endpoint returns, per item:
/// ```json
/// {
///   "id": 1,
///   "canonical_product_id": "iphone-15-pro-max-256",
///   "target_price": 125000.0,
///   "is_active": true,
///   "store_count": 3,
///   "lowest_price": {
///     "store_id": "amazon_eg",
///     "price_local": 129999.0,
///     "currency": "EGP",
///     "url": "https://amazon.eg/dp/..."
///   },
///   "created_at": "...",
///   "updated_at": "..."
/// }
/// ```
class TrackedItem {
  final int id;
  final String canonicalProductId;

  /// Product name scraped from the store page; null until a fetch succeeds.
  final String? title;
  final double? targetPrice;
  final bool isActive;
  final int storeCount;
  final TrackedItemLowestPrice? lowestPrice;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  /// Backend fetch status for this tracker's store mapping(s):
  /// `null` (never fetched / in flight), `ok`, `no_price_found`, `blocked`,
  /// or `fetch_failed`. Drives the card's actionable "failed" states so a
  /// bad link is not mistaken for an endless fetch.
  final String? fetchStatus;

  /// Short reason for a non-`ok` [fetchStatus] (log-safe, not user-facing).
  final String? fetchError;

  const TrackedItem({
    required this.id,
    required this.canonicalProductId,
    this.title,
    this.targetPrice,
    required this.isActive,
    required this.storeCount,
    this.lowestPrice,
    this.createdAt,
    this.updatedAt,
    this.fetchStatus,
    this.fetchError,
  });

  /// The product's name: the scraped page title when known, otherwise a
  /// label derived from the canonical id without its `store:` prefix (the
  /// store is not part of the product name, and is `unknown` for stores the
  /// backend does not recognise).
  //
  /// A name is what the card shows, so an id that leaves nothing behind once
  /// the prefix is cut (`"amazon_eg:"`, or a slug that is only separators like
  /// `"amazon_eg:---"`) falls back to the whole id instead of an empty string:
  /// a card with no name at all is worse than one showing its raw identifier,
  /// and inventing a word like "Unknown" would be a new i18n key that needs
  /// its Arabic twin authored.
  String get displayName {
    final scraped = title?.trim();
    if (scraped != null && scraped.isNotEmpty) return scraped;
    final colon = canonicalProductId.indexOf(':');
    final slug = colon >= 0
        ? canonicalProductId.substring(colon + 1)
        : canonicalProductId;
    final words = slug
        .replaceAll(RegExp(r'[_\-]+'), ' ')
        .split(' ')
        .where((w) => w.isNotEmpty)
        .map((w) => w[0].toUpperCase() + w.substring(1));
    final label = words.join(' ').trim();
    if (label.isEmpty) return canonicalProductId;
    return label;
  }

  factory TrackedItem.fromJson(Map<String, dynamic> json) {
    final lowest = json['lowest_price'];
    return TrackedItem(
      id: (json['id'] as num?)?.toInt() ?? 0,
      canonicalProductId: json['canonical_product_id'] as String? ?? '',
      title: json['title'] is String ? json['title'] as String : null,
      targetPrice: (json['target_price'] as num?)?.toDouble(),
      isActive: json['is_active'] as bool? ?? true,
      storeCount: (json['store_count'] as num?)?.toInt() ?? 0,
      lowestPrice: lowest is Map<String, dynamic>
          ? TrackedItemLowestPrice.fromJson(lowest)
          : null,
      createdAt: _parseDate(json['created_at']),
      updatedAt: _parseDate(json['updated_at']),
      fetchStatus: json['fetch_status'] is String
          ? json['fetch_status'] as String
          : null,
      fetchError: json['fetch_error'] is String
          ? json['fetch_error'] as String
          : null,
    );
  }
}

class TrackedItemLowestPrice {
  final String storeId;
  final double priceLocal;
  final String currency;
  final String url;
  final String imageUrl;

  const TrackedItemLowestPrice({
    required this.storeId,
    required this.priceLocal,
    required this.currency,
    required this.url,
    this.imageUrl = '',
  });

  ///       "url": "https://amazon.eg/dp/...",
  ///       "image_url": "https://cdn.example.com/product.jpg"
  factory TrackedItemLowestPrice.fromJson(Map<String, dynamic> json) {
    return TrackedItemLowestPrice(
      storeId: json['store_id'] as String? ?? '',
      priceLocal: (json['price_local'] as num?)?.toDouble() ?? 0.0,
      currency: json['currency'] as String? ?? 'EGP',
      url: json['url'] as String? ?? '',
      imageUrl: json['image_url'] as String? ?? '',
    );
  }
}

DateTime? _parseDate(Object? value) {
  if (value == null) return null;
  if (value is DateTime) return value;
  return DateTime.tryParse(value.toString());
}
