// Unit tests for the Elhaq data layer: model parsing and demo data.
//
// These tests exercise the JSON parsing and demo-data generation that back
// the Flutter app, so the demo works whether data comes from the network or
// from the in-memory fallback.

import 'package:flutter_test/flutter_test.dart';
import 'package:elhaq_tracker/src/data/demo_data.dart';
import 'package:elhaq_tracker/src/data/models/deal_model.dart';
import 'package:elhaq_tracker/src/data/models/platform_stats_model.dart';
import 'package:elhaq_tracker/src/data/models/price_point_model.dart';
import 'package:elhaq_tracker/src/data/models/tracked_item_model.dart';

void main() {
  group('TrackedItem.fromJson', () {
    test('parses a tracked item with a lowest price', () {
      final item = TrackedItem.fromJson({
        'id': 1,
        'canonical_product_id': 'iphone-15-pro-max-256gb',
        'target_price': 125000.0,
        'is_active': true,
        'store_count': 3,
        'lowest_price': {
          'store_id': 'amazon_eg',
          'price_local': 129999.0,
          'currency': 'EGP',
          'url': 'https://amazon.eg/dp/B0C9L8XYZ',
          'image_url': 'https://cdn.example.com/iphone.jpg',
        },
      });

      expect(item.id, 1);
      expect(item.canonicalProductId, 'iphone-15-pro-max-256gb');
      expect(item.targetPrice, 125000.0);
      expect(item.isActive, true);
      expect(item.storeCount, 3);
      expect(item.lowestPrice?.storeId, 'amazon_eg');
      expect(item.lowestPrice?.priceLocal, 129999.0);
      expect(item.lowestPrice?.imageUrl, 'https://cdn.example.com/iphone.jpg');
    });

    test('handles a missing lowest price', () {
      final item = TrackedItem.fromJson({
        'id': 2,
        'canonical_product_id': 'playstation-5-slim-bundle',
        'target_price': null,
        'is_active': false,
        'store_count': 0,
      });

      expect(item.targetPrice, isNull);
      expect(item.isActive, false);
      expect(item.lowestPrice, isNull);
    });
  });

  group('PricePoint.fromJson', () {
    test('parses snake_case fields', () {
      final point = PricePoint.fromJson({
        'time': '2024-01-15T00:00:00Z',
        'price_local': 129999.0,
        'price_usd': 2708.31,
        'in_stock': true,
      });

      expect(point.priceLocal, 129999.0);
      expect(point.priceUsd, 2708.31);
      expect(point.inStock, true);
      expect(point.time, isNotNull);
    });
  });

  group('PlatformStats.fromJson', () {
    test('parses stats', () {
      final stats = PlatformStats.fromJson({
        'total_trackers': 128,
        'deals_today': 47,
        'total_savings': 2847.5,
      });

      expect(stats.totalTrackers, 128);
      expect(stats.dealsToday, 47);
      expect(stats.totalSavings, 2847.5);
    });
  });

  group('Deal.fromJson', () {
    test('parses a deal', () {
      final deal = Deal.fromJson({
        'id': '1',
        'title': 'iPhone 15 Pro Max 256GB',
        'store_name': 'Amazon EG',
        'image_url': 'https://cdn.example.com/iphone.jpg',
        'price': 129999.0,
        'original_price': 149999.0,
        'discount_percentage': 13.3,
      });

      expect(deal.id, '1');
      expect(deal.title, 'iPhone 15 Pro Max 256GB');
      expect(deal.storeName, 'Amazon EG');
      expect(deal.imageUrl, 'https://cdn.example.com/iphone.jpg');
      expect(deal.price, 129999.0);
      expect(deal.discountPercentage, 13.3);
    });

    test('accepts a thumbnail alias and ignores invalid image values', () {
      final aliased = Deal.fromJson({
        'id': '2',
        'thumbnail': 'https://cdn.example.com/thumb.jpg',
      });
      final invalid = Deal.fromJson({'id': '3', 'image_url': '/relative.jpg'});

      expect(aliased.imageUrl, 'https://cdn.example.com/thumb.jpg');
      expect(invalid.imageUrl, isEmpty);
    });
  });

  group('DemoData', () {
    test('provides a non-empty tracked items list', () {
      expect(DemoData.trackedItems, isNotEmpty);
      expect(DemoData.trackedItems.first.canonicalProductId, isNotEmpty);
    });

    test('provides a non-empty deals list', () {
      expect(DemoData.deals, isNotEmpty);
    });

    test('provides stats', () {
      expect(DemoData.stats.totalTrackers, greaterThan(0));
    });

    test('generates a deterministic 90-day price history', () {
      final history = DemoData.priceHistory('iphone-15-pro-max-256gb');
      expect(history.length, 90);

      // Deterministic: same sku yields the same series.
      final again = DemoData.priceHistory('iphone-15-pro-max-256gb');
      expect(
        history.map((p) => p.priceLocal).toList(),
        equals(again.map((p) => p.priceLocal).toList()),
      );

      // All points have a positive price and a timestamp.
      for (final point in history) {
        expect(point.priceLocal, greaterThan(0));
        expect(point.time, isNotNull);
      }
    });
  });
}
