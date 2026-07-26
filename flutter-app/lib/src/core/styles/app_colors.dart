import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class AppColors {
  // Primary Colors - El72 Deals Theme
  static const Color primary = Color(0xFFFF8A00); // Vibrant orange
  static const Color secondary = Color(0xFFFFC93C); // Bright yellow
  static const Color accent = Color(0xFFE65100); // Deep orange

  // Semantic Colors for Price Tracking
  static const Color priceUp = Color(0xFFEF4444); // Red for price increase
  static const Color priceDown = Color(0xFF10B981); // Green for price decrease/deals

  // Background Colors
  static const Color backgroundLight = Color(0xFFFFFBF4); // Warm white
  static const Color backgroundDark = Color(0xFF1B1206); // Deep charcoal

  // Text Colors
  static const Color textPrimary = Color(0xFF1F2933);
  static const Color textSecondary = Color(0xFF6B7280);
  static const Color textOnPrimary = Colors.white;

  // Status Colors
  static const Color success = Color(0xFF10B981); // Green
  static const Color error = Color(0xFFEF4444); // Red
  static const Color warning = Color(0xFFF59E0B); // Amber
  static const Color info = Color(0xFF3B82F6); // Blue

  // Card and Surface Colors
  static const Color cardBackground = Colors.white;
  static const Color cardBorder = Color(0xFFE2E8F0);

  // Button Colors
  static const Color buttonPrimary = Color(0xFFFF8A00);
  static const Color buttonSecondary = Color(0xFFFFC93C);
  static const Color buttonDisabled = Color(0xFFCBD5E1);

  // Text Styles
  static TextStyle priceTextStyle = GoogleFonts.jetBrainsMono(
    fontSize: 16,
    fontWeight: FontWeight.w600,
    color: textPrimary,
  );

  static TextStyle priceTextStyleLarge = GoogleFonts.jetBrainsMono(
    fontSize: 24,
    fontWeight: FontWeight.bold,
    color: textPrimary,
  );
}