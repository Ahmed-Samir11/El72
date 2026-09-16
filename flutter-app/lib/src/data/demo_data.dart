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
      canonicalProductId: 'rtx-5060-compumarts',
      targetPrice: 19000.0,
      isActive: true,
      storeCount: 4,
      lowestPrice: TrackedItemLowestPrice(
        storeId: 'compumarts_eg',
        priceLocal: 19900.0,
        currency: 'EGP',
        url:
            'https://www.compumarts.com/products/zotac-gaming-rtx-5060-twin-edge-8gb-egypt',
        imageUrl:
            'https://www.compumarts.com/cdn/shop/files/ZOTAC-GAMING-GeForce-RTX-5060-Twin-Edge_01.jpg?v=1767519263&width=600',
      ),
    ),
  ];

  static const List<Deal> deals = [
    Deal(
      id: '3',
      title: 'Gigabyte RTX 5060 WINDFORCE MAX OC 8GB',
      storeName: 'El Badr Group',
      imageUrl:
          'https://elbadrgroupeg.store/image/cache/catalog/products_2026/T17M1ZRxF4mkemQhgK1CO6lOgm-550x550.png',
      sourceUrl:
          'https://elbadrgroupeg.store/gigabyte-geforce-rtx-5060-windforce-max-oc-8gb-gddr7',
      price: 22499.0,
      originalPrice: 22499.0,
      discountPercentage: 0.0,
    ),
    Deal(
      id: 'rtx-5060-compumarts',
      title: 'ZOTAC RTX 5060 Twin Edge 8GB',
      storeName: 'CompuMarts',
      imageUrl:
          'https://www.compumarts.com/cdn/shop/files/ZOTAC-GAMING-GeForce-RTX-5060-Twin-Edge_01.jpg?v=1767519263&width=600',
      sourceUrl:
          'https://www.compumarts.com/products/zotac-gaming-rtx-5060-twin-edge-8gb-egypt',
      price: 19900.0,
      originalPrice: 19900.0,
      discountPercentage: 0.0,
    ),
    Deal(
      id: 'tie-house-3-shirts-999',
      title: '3 Classic Shirts for 999 LE',
      storeName: 'Tie House',
      imageUrl:
          'https://images.unsplash.com/photo-1602810318383-e386cc2a3ccf?auto=format&fit=crop&w=600&q=80',
      sourceUrl:
          'https://tie-house.com/products/classic-shirt-regular-fit-gray-1',
      price: 999.0,
      originalPrice: 1299.0,
      discountPercentage: 23.1,
    ),
    Deal(
      id: 'asus-rog-hatsune-miku-xg27acmeg-g',
      title: 'ASUS ROG Strix Hatsune Miku 27 XG27ACMEG-G',
      storeName: 'Geeks Store',
      imageUrl:
          'https://bunny-wp-pullzone-ekicvdt3ci.b-cdn.net/wp-content/uploads/2026/01/ASUS-XG27ACMEG-G-06-1-600x600.webp',
      sourceUrl:
          'https://geeksstoreeg.com/product/asus-rog-strix-hatsune-miku-27-xg27acmeg-g/',
      price: 19500.0,
      originalPrice: 20999.0,
      discountPercentage: 7.1,
    ),
    Deal(
      id: 'ravin-white-fruit-print-tee-r219636',
      title: 'White Oversized Fresh and Tasty Graphic Tee',
      storeName: 'Ravin',
      imageUrl:
          'https://shop.iravin.com/cdn/shop/files/r219636a.jpg?v=1788688999',
      sourceUrl:
          'https://shop.iravin.com/products/white-oversized-graphic-fruit-print-tee-r219636',
      price: 337.50,
      originalPrice: 749.99,
      discountPercentage: 55.0,
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
      points.add(
        PricePoint(
          time: DateTime(t.year, t.month, t.day),
          priceLocal: price,
          priceUsd: price / 48.0,
          inStock: true,
        ),
      );
    }
    return points;
  }

  static double _noise(int n) {
    // Cheap deterministic pseudo-random in [-1, 1].
    final x = (n * 9301 + 49297) % 233280;
    return (x / 233280.0) * 2.0 - 1.0;
  }
}
