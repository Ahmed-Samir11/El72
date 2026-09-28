import 'dart:ui';

import 'package:intl/intl.dart';

/// Formats a monetary amount for the active locale.
///
/// Arabic renders with Eastern-Arabic digits and the local currency label;
/// English renders with Latin digits and `EGP`. The app's currency is EGP.
String formatPrice(double amount, {Locale? locale}) {
  final tag = locale?.toLanguageTag() ?? 'en';
  final symbol = tag.startsWith('ar') ? '\u{062C}.\u{0645}' : 'EGP';
  return NumberFormat.currency(locale: tag, symbol: symbol).format(amount);
}
