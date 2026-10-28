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

  group('TrackedItem title stays bounded', () {
    test('a page-sized scraped title is clipped where it enters the app', () {
      // The scraper copies the store page's title straight out of third-party
      // markup, and the card renders it. Bounded at parse time, no later screen
      // has to remember to do it, and a runaway page cannot keep a megabyte of
      // text alive for the whole dashboard session.
      final item = TrackedItem.fromJson({
        'id': 5,
        'canonical_product_id': 'amazon_eg:kindle',
        'title': 't' * 5000,
      });
      expect(item.title!.length, maxTrackedItemTitleLength);
      // The card label comes from the same field, so it is bounded too.
      expect(item.displayName.length, maxTrackedItemTitleLength);
    });

    test('a legitimate product name is left whole', () {
      final item = TrackedItem.fromJson({
        'id': 6,
        'canonical_product_id': 'amazon_eg:kindle',
        'title': 'Kindle Paperwhite Signature Edition (32 GB, 6.8" display)',
      });
      expect(
        item.displayName,
        'Kindle Paperwhite Signature Edition (32 GB, 6.8" display)',
      );
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

    test('a scraped title is folded onto one line', () {
      // The scraper stores the page title as the markup had it, which can wrap
      // across lines or pad it with tabs. The card lays `displayName` out on
      // one line, so the whitespace is folded where the model reads the field -
      // the same rule the toast helpers use, without their length cap.
      final item = TrackedItem.fromJson({
        'id': 10,
        'canonical_product_id': 'amazon_eg:kindle',
        'title': '  Kindle\n\tPaperwhite   Signature\nEdition  ',
      });
      expect(item.displayName, 'Kindle Paperwhite Signature Edition');
    });

    test('a control character in a scraped title does not reach the card', () {
      // Third-party titles are attacker-influenced: a stray escape from the
      // page's own pipeline survives a whitespace fold and renders as a
      // replacement glyph, so it is removed rather than folded.
      final item = TrackedItem.fromJson({
        'id': 11,
        'canonical_product_id': 'amazon_eg:kindle',
        'title': 'Kindle\u0002\u007fPaperwhite\u2027',
      });
      expect(item.displayName, 'KindlePaperwhite\u2027');
      expect(item.displayName.contains('\u0002'), false);
      expect(item.displayName.contains('\u007f'), false);
    });

    test('an empty id has no label to invent', () {
      // Nothing to derive from and no key to invent: the card shows an empty
      // title rather than a made-up English one.
      final item = TrackedItem.fromJson({'id': 4, 'canonical_product_id': ''});
      expect(item.displayName, '');
    });
  });
}
