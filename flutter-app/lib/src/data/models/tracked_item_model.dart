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

  const TrackedItem({
    required this.id,
    required this.canonicalProductId,
    this.targetPrice,
    required this.isActive,
    required this.storeCount,
    this.lowestPrice,
    this.createdAt,
    this.updatedAt,
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
