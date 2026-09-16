/// A deal shown in the Deal Discovery feed and the dashboard Deals tab.
///
/// Populated either from `GET /deals/live` (Engineer B's endpoint) or from
/// [DemoData] when the backend is unreachable.
class Deal {
  final String id;
  final String title;
  final String storeName;
  final String imageUrl;
  final String sourceUrl;
  final double price;
  final double originalPrice;
  final double discountPercentage;

  const Deal({
    required this.id,
    required this.title,
    required this.storeName,
    required this.imageUrl,
    this.sourceUrl = '',
    required this.price,
    required this.originalPrice,
    required this.discountPercentage,
  });

  /// Parses a deal from the JSON returned by `GET /deals/live`.
  factory Deal.fromJson(Map<String, dynamic> json) {
    final price = (json['price'] as num?)?.toDouble() ?? 0.0;
    final original = (json['original_price'] as num?)?.toDouble() ?? price;
    final discount =
        (json['discount_percentage'] as num?)?.toDouble() ??
        (original > 0 ? (1 - price / original) * 100 : 0.0);
    return Deal(
      id: json['id']?.toString() ?? '',
      title:
          json['title'] as String? ?? json['product_name'] as String? ?? 'Deal',
      storeName:
          json['store_name'] as String? ?? json['store'] as String? ?? '',
      imageUrl: _imageUrl(json),
      sourceUrl: json['source_url'] as String? ?? json['url'] as String? ?? '',
      price: price,
      originalPrice: original,
      discountPercentage: discount,
    );
  }

  static String _imageUrl(Map<String, dynamic> json) {
    final direct = json['image_url'] ?? json['image'] ?? json['thumbnail'];
    if (direct is String && direct.startsWith('http')) return direct;
    final images = json['images'];
    if (images is List && images.isNotEmpty && images.first is String) {
      final first = images.first as String;
      if (first.startsWith('http')) return first;
    }
    return '';
  }
}
