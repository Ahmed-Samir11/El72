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

  group('TrackedItem.displayName', () {
    test('prefers the scraped page title', () {
      final item = TrackedItem.fromJson({
        'id': 1,
        'canonical_product_id': 'unknown:item',
        'title': 'Logitech G102 Lightsync Gaming Mouse',
      });
      expect(item.displayName, 'Logitech G102 Lightsync Gaming Mouse');
    });

    test('falls back to the slug without the store prefix', () {
      final item = TrackedItem.fromJson({
        'id': 1,
        'canonical_product_id': 'elbadr_eg:asus-tuf-gaming-27-inch-monitor',
      });
      expect(item.displayName, 'Asus Tuf Gaming 27 Inch Monitor');
    });

    test('blank title falls back to the slug', () {
      final item = TrackedItem.fromJson({
        'id': 1,
        'canonical_product_id': 'iphone-15-pro',
        'title': '  ',
      });
      expect(item.displayName, 'Iphone 15 Pro');
    });

    test('an id with nothing after the store prefix keeps the whole id', () {
      // Stripping the prefix would leave an empty label, i.e. a card with no
      // name at all. The raw id is the only thing that still identifies the
      // tracker, and inventing a word like "Unknown" would be a new i18n key
      // with an Arabic twin to author, so it is not an option here.
      final item = TrackedItem.fromJson({
        'id': 2,
        'canonical_product_id': 'amazon_eg:',
      });
      expect(item.displayName, 'amazon_eg:');
    });

    test('a slug of nothing but separators keeps the whole id', () {
      final item = TrackedItem.fromJson({
        'id': 3,
        'canonical_product_id': 'amazon_eg:---_',
      });
      expect(item.displayName, 'amazon_eg:---_');
    });

    test('an empty id has no label to invent', () {
      // Nothing to derive from and no key to invent: the card shows an empty
      // title rather than a made-up English one.
      final item = TrackedItem.fromJson({'id': 4, 'canonical_product_id': ''});
      expect(item.displayName, '');
    });
  });
}
