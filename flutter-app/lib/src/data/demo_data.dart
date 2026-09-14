import 'models/deal_model.dart';
import 'models/platform_stats_model.dart';
import 'models/price_point_model.dart';
import 'models/tracked_item_model.dart';

/// Realistic demo data used when [AppConfig.demoMode] is enabled and the
/// backend is unreachable. Mirrors the JSON shapes the API returns so the UI
/// renders identically whether data comes from the network or from here.
class DemoData {
  static const List<TrackedItem> trackedItems = [
    TrackedItem(
      id: 1,
      canonicalProductId: 'iphone-15-pro-max-256gb',
      targetPrice: 125000.0,
      isActive: true,
      storeCount: 3,
      lowestPrice: TrackedItemLowestPrice(
        storeId: 'amazon_eg',
        priceLocal: 129999.0,
        currency: 'EGP',
        url: 'https://amazon.eg/dp/B0C9L8XYZ',
      ),
    ),
    TrackedItem(
      id: 2,
      canonicalProductId: 'playstation-5-slim-bundle',
      targetPrice: 11000.0,
      isActive: true,
      storeCount: 2,
      lowestPrice: TrackedItemLowestPrice(
        storeId: 'jumia_eg',
        priceLocal: 11499.0,
        currency: 'EGP',
        url: 'https://www.jumia.com.eg/playstation-5',
      ),
    ),
    TrackedItem(
      id: 3,
      canonicalProductId: 'nvidia-rtx-4060-8gb',
      targetPrice: 14500.0,
      isActive: true,
      storeCount: 4,
      lowestPrice: TrackedItemLowestPrice(
        storeId: 'noon_eg',
        priceLocal: 14999.0,
        currency: 'EGP',
        url: 'https://www.noon.com/egypt-en/rtx-4060',
      ),
    ),
  ];

  static const List<Deal> deals = [
    Deal(
      id: '1',
      title: 'iPhone 15 Pro Max 256GB',
      storeName: 'Amazon EG',
      imageUrl: '',
      price: 129999.0,
      originalPrice: 149999.0,
      discountPercentage: 13.3,
    ),
    Deal(
      id: '2',
      title: 'PlayStation 5 Slim Bundle',
      storeName: 'Jumia EG',
      imageUrl: '',
      price: 11499.0,
      originalPrice: 13499.0,
      discountPercentage: 14.8,
    ),
    Deal(
      id: '3',
      title: 'NVIDIA RTX 4060 8GB',
      storeName: 'Noon EG',
      imageUrl: '',
      price: 14999.0,
      originalPrice: 19999.0,
      discountPercentage: 25.0,
    ),
    Deal(
      id: '4',
      title: 'Samsung 55" 4K Crystal TV',
      storeName: 'Carrefour EG',
      imageUrl: '',
      price: 24999.0,
      originalPrice: 31999.0,
      discountPercentage: 21.9,
    ),
    Deal(
      id: '5',
      title: 'MacBook Air M2 13"',
      storeName: 'iStyle EG',
      imageUrl: '',
      price: 42999.0,
      originalPrice: 46999.0,
      discountPercentage: 8.5,
    ),
  ];

  static const PlatformStats stats = PlatformStats(
    totalTrackers: 128,
    dealsToday: 47,
    totalSavings: 2847.5,
  );

  /// Deterministic 90-day price history for a given [sku].
  ///
  /// Generates a plausible downward-trending series (with small noise) so the
  /// chart looks realistic and is stable across rebuilds for the same sku.
  static List<PricePoint> priceHistory(String sku) {
    final seed = sku.hashCode & 0x7fffffff;
    final base = 120000.0 + (seed % 40) * 1000.0;
    final days = 90;
    final now = DateTime.now();
    final points = <PricePoint>[];
    for (var i = 0; i < days; i++) {
      final t = now.subtract(Duration(days: days - 1 - i));
      // Gentle downward trend with a couple of dips and small noise.
      final trend = base * (1.0 - 0.12 * (i / days));
      final noise = _noise(seed + i) * base * 0.02;
      final dip = (i % 23 == 10) ? -base * 0.05 : 0.0;
      final price = (trend + noise + dip).roundToDouble();
      points.add(PricePoint(
        time: DateTime(t.year, t.month, t.day),
        priceLocal: price,
        priceUsd: price / 48.0,
        inStock: true,
      ));
    }
    return points;
  }

  static double _noise(int n) {
    // Cheap deterministic pseudo-random in [-1, 1].
    final x = (n * 9301 + 49297) % 233280;
    return (x / 233280.0) * 2.0 - 1.0;
  }
}
