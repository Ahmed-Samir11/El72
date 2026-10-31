import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/data/models/usage_limits_model.dart';

void main() {
  group('UsageLimits.fromJson', () {
    test('parses the shipped fair_use payload', () {
      final limits = UsageLimits.fromJson(const {
        'active_trackers': 4,
        'cap': 100,
        'created_last': '2026-02-11T09:12:33.004000',
        'retry_after_seconds': 0,
        'enforcement': 'fair_use',
      });

      expect(limits.activeTrackers, 4);
      expect(limits.cap, 100);
      expect(limits.isCapped, isTrue);
      expect(limits.createdLast, isNotNull);
      expect(limits.retryAfterSeconds, 0);
      expect(limits.enforcement, 'fair_use');
    });

    test('a legacy "on" backend reports no cap and the mode it is in', () {
      final limits = UsageLimits.fromJson(const {
        'active_trackers': 3,
        'cap': null,
        'created_last': null,
        'retry_after_seconds': 0,
        'enforcement': 'on',
      });

      expect(limits.isCapped, isFalse);
      expect(limits.createdLast, isNull);
      expect(limits.enforcement, 'on');
    });

    test('an empty body still yields a usable chip, not a crash', () {
      final limits = UsageLimits.fromJson(const {});

      expect(limits.activeTrackers, 0);
      expect(limits.cap, isNull);
      expect(limits.retryAfterSeconds, 0);
      // The default is the shipped mode, so an unlabelled answer still renders.
      expect(limits.enforcement, 'fair_use');
    });

    test('malformed values degrade instead of throwing a cast error', () {
      // A hand-edited proxy or an older server must not take down the Profile
      // tab: every field has a neutral fallback.
      final limits = UsageLimits.fromJson(const {
        'active_trackers': 'many',
        'cap': 'hundred',
        'created_last': 17,
        'retry_after_seconds': 'soon',
        'enforcement': 42,
      });

      expect(limits.activeTrackers, 0);
      expect(limits.cap, isNull);
      expect(limits.createdLast, isNull);
      expect(limits.retryAfterSeconds, 0);
      expect(limits.enforcement, 'fair_use');
    });

    test('a float cap from a JSON encoder is read as an int', () {
      final limits = UsageLimits.fromJson(const {
        'active_trackers': 2.0,
        'cap': 100.0,
        'retry_after_seconds': 2.76,
      });

      expect(limits.activeTrackers, 2);
      expect(limits.cap, 100);
      expect(limits.retryAfterSeconds, 2.76);
    });
  });
}
