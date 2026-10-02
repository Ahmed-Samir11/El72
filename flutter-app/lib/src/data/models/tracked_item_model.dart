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
    this.targetPrice,
    required this.isActive,
    required this.storeCount,
    this.lowestPrice,
    this.createdAt,
    this.updatedAt,
    this.fetchStatus,
    this.fetchError,
  });

  /// Human-friendly label derived from the canonical id.
  String get displayName {
    final words = canonicalProductId
        .replaceAll(RegExp(r'[_\-]+'), ' ')
        .split(' ')
        .where((w) => w.isNotEmpty)
        .map((w) => w[0].toUpperCase() + w.substring(1));
    return words.join(' ').trim();
  }

  factory TrackedItem.fromJson(Map<String, dynamic> json) {
    final lowest = json['lowest_price'];
    return TrackedItem(
      id: (json['id'] as num?)?.toInt() ?? 0,
      canonicalProductId: json['canonical_product_id'] as String? ?? '',
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
