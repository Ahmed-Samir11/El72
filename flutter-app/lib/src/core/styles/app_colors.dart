import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class AppColors {
  // Primary Colors - Elhaq Big Tech Theme
  static const Color primary = Color(0xFF0D7377); // Deep Teal
  static const Color secondary = Color(0xFFFF6B35); // Warm Orange

  // Semantic Colors for Price Tracking
  static const Color priceUp = Color(0xFFEF4444); // Red for price increase
  static const Color priceDown = Color(0xFFFF6B35); // Orange for price decrease/deals

  // Background Colors
  static const Color backgroundLight = Colors.white; // White
  static const Color backgroundDark = Color(0xFF0F172A); // Dark Navy

  // Text Colors
  static const Color textPrimary = Color(0xFF0D7377); // Deep Teal
  static const Color textSecondary = Color(0xFF64748B);
  static const Color textOnPrimary = Colors.white;

  // Status Colors
  static const Color success = Color(0xFF0D7377); // Teal
  static const Color error = Color(0xFFEF4444); // Red
  static const Color warning = Color(0xFFF59E0B); // Amber
  static const Color info = Color(0xFF3B82F6); // Blue

  // Card and Surface Colors
  static const Color cardBackground = Colors.white;
  static const Color cardBorder = Color(0xFFE2E8F0);

  // Button Colors
  static const Color buttonPrimary = Color(0xFFFF6B35); // Warm Orange
  static const Color buttonSecondary = Color(0xFF0D7377); // Deep Teal
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