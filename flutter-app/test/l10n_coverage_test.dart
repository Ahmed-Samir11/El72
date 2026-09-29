import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// Localization coverage tests: every key in the English template must have
/// a non-empty Arabic translation, and both ARB files must be valid JSON.
void main() {
  final enArb = File('lib/l10n/app_en.arb').readAsStringSync();
  final arArb = File('lib/l10n/app_ar.arb').readAsStringSync();

  Map<String, dynamic> load(String source) =>
      Map<String, dynamic>.from(jsonDecode(source) as Map);

  final en = load(enArb);
  final ar = load(arArb);

  List<String> keys(Map<String, dynamic> arb) =>
      arb.keys.where((k) => !k.startsWith('@')).toList();

  group('ARB coverage', () {
    test('every template key has a non-empty Arabic translation', () {
      final missing = keys(en).where((k) {
        final value = ar[k];
        return value == null || (value is String && value.trim().isEmpty);
      }).toList();
      expect(missing, isEmpty, reason: 'Missing/empty in app_ar.arb: $missing');
    });

    test('every Arabic key exists in the English template', () {
      final extra = keys(ar).where((k) => !en.containsKey(k)).toList();
      expect(extra, isEmpty, reason: 'Extra in app_ar.arb: $extra');
    });

    test('placeholder declarations match between locales', () {
      for (final key in keys(en)) {
        final enPh = (en['@$key'] as Map?)?['placeholders'] as Map?;
        final arPh = (ar['@$key'] as Map?)?['placeholders'] as Map?;
        expect(
          arPh?.keys.toSet(),
          enPh?.keys.toSet(),
          reason: 'Placeholder mismatch for $key',
        );
      }
    });
  });

  group('Arabic quality', () {
    test('no Arabic translation is a copy of the English string', () {
      final copies = keys(en).where((k) => ar[k] == en[k]).toList();
      // appTitle is intentionally the brand name in both locales.
      expect(copies, isEmpty, reason: 'Untranslated: $copies');
    });

    test('Arabic strings contain Arabic script', () {
      final arabicRegex = RegExp('[\u0600-\u06FF]');
      const allowedNoArabicScript = <String>{'appTitle'};
      final offenders = keys(ar)
          .where(
            (k) =>
                !allowedNoArabicScript.contains(k) &&
                !arabicRegex.hasMatch(ar[k] as String),
          )
          .toList();
      expect(offenders, isEmpty, reason: 'No Arabic script: $offenders');
    });
  });
}
