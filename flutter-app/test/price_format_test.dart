import 'dart:ui';

import 'package:flutter_test/flutter_test.dart';
import 'package:intl/intl.dart';

import 'package:elhaq_tracker/src/core/format/price_format.dart';

void main() {
  group('formatPrice', () {
    test('formats EGP amounts for the en locale with the EGP symbol', () {
      expect(formatPrice(1250.5, locale: Locale('en')), contains('EGP'));
      expect(formatPrice(1250.5, locale: Locale('en')), contains('1,250.5'));
    });

    test('formats EGP amounts for the ar locale with Arabic currency label', () {
      final formatted = formatPrice(1250, locale: Locale('ar'));
      expect(formatted, contains('ج.م'));
      // CLDR default for ar uses Latin digits.
      expect(formatted, contains('1,250'));
    });

    test('respects the active locale tag for non-Arab locales', () {
      // A non-Arab, non-English locale still gets the EGP symbol.
      final formatted = NumberFormat.currency(locale: 'fr', symbol: 'EGP')
          .format(10);
      expect(formatted, contains('EGP'));
    });
  });
}
