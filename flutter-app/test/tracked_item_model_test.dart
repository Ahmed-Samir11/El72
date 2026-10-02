import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/data/models/tracked_item_model.dart';

void main() {
  group('TrackedItem fetch status parsing', () {
    test('parses fetch_status and fetch_error when present', () {
      final item = TrackedItem.fromJson({
        'id': 7,
        'canonical_product_id': 'bad-link',
        'is_active': true,
        'store_count': 1,
        'fetch_status': 'no_price_found',
        'fetch_error': 'no price found on page',
      });
      expect(item.fetchStatus, 'no_price_found');
      expect(item.fetchError, 'no price found on page');
    });

    test('missing status fields parse as null (still fetching)', () {
      final item = TrackedItem.fromJson({
        'id': 8,
        'canonical_product_id': 'fresh-item',
        'is_active': true,
        'store_count': 1,
      });
      expect(item.fetchStatus, isNull);
      expect(item.fetchError, isNull);
    });

    test('ok status with null error parses', () {
      final item = TrackedItem.fromJson({
        'id': 9,
        'canonical_product_id': 'ok-item',
        'is_active': true,
        'store_count': 1,
        'fetch_status': 'ok',
        'fetch_error': null,
      });
      expect(item.fetchStatus, 'ok');
      expect(item.fetchError, isNull);
    });
  });
}
