import 'dart:ui';

import 'package:intl/intl.dart';

/// Formats a monetary amount for the given locale.
///
/// Arabic renders with the local currency label (ج.م); English and other
/// locales render with `EGP`. The app's currency is EGP. The locale is
/// required so call sites cannot silently fall back to English on an
/// Arabic device.
String formatPrice(double amount, {required Locale locale}) {
  final tag = locale.toLanguageTag();
  final symbol = tag.startsWith('ar') ? '\u{062C}.\u{0645}' : 'EGP';
  return NumberFormat.currency(locale: tag, symbol: symbol).format(amount);
}
