import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class AppColors {
  // Primary Colors - El72 Falcon Theme (framed logo palette)
  static const Color primary = Color(0xFFF2841A); // Falcon Orange
  static const Color secondary = Color(0xFFF6E832); // Falcon Yellow
  static const Color accent = Color(0xFFCF9D3F); // Tan / Bronze

  // Semantic Colors for Price Tracking
  static const Color priceUp = Color(0xFFEF4444); // Red for price increase
  static const Color priceDown = Color(0xFF10B981); // Green for price decrease/deals

  // Background Colors
  static const Color backgroundLight = Color(0xFFFDFCEB); // Cream
  static const Color backgroundDark = Color(0xFF241505); // Deep Warm Brown

  // Text Colors
  static const Color textPrimary = Color(0xFF3D2B0F); // Dark Brown
  static const Color textSecondary = Color(0xFF8A6D3B); // Muted Brown
  static const Color textOnPrimary = Colors.white;

  // Status Colors
  static const Color success = Color(0xFF10B981); // Green
  static const Color error = Color(0xFFEF4444); // Red
  static const Color warning = Color(0xFFF59E0B); // Amber
  static const Color info = Color(0xFF3B82F6); // Blue

  // Card and Surface Colors
  static const Color cardBackground = Colors.white;
  static const Color cardBorder = Color(0xFFE8D9B0); // Light Tan

  // Button Colors
  static const Color buttonPrimary = Color(0xFFF2841A); // Falcon Orange
  static const Color buttonSecondary = Color(0xFFF6E832); // Falcon Yellow
  static const Color buttonDisabled = Color(0xFFD9C9A0); // Muted Tan

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