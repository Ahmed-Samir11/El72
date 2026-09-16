/// A single point in a product's price history, as returned by
/// `GET /price-history/{sku}` (Engineer B's endpoint, sourced from the
/// TimescaleDB `price_history` hypertable).
///
/// The endpoint is expected to return a list of points (or an object
/// wrapping a list under `points`/`history`/`data`). Each point:
/// ```json
/// { "time": "2026-06-01T00:00:00Z", "price_local": 129999.0,
///   "price_usd": 2599.98, "in_stock": true }
/// ```
class PricePoint {
  final DateTime time;
  final double priceLocal;
  final double priceUsd;
  final bool inStock;

  const PricePoint({
    required this.time,
    required this.priceLocal,
    required this.priceUsd,
    this.inStock = true,
  });

  factory PricePoint.fromJson(Map<String, dynamic> json) {
    final time = json['time'] ?? json['timestamp'] ?? json['date'];
    return PricePoint(
      time: time is DateTime
          ? time
          : DateTime.tryParse(time.toString()) ?? DateTime.now(),
      priceLocal: (json['price_local'] as num?)?.toDouble() ??
          (json['price'] as num?)?.toDouble() ??
          0.0,
      priceUsd: (json['price_usd'] as num?)?.toDouble() ?? 0.0,
      inStock: json['in_stock'] as bool? ?? true,
    );
  }
}
