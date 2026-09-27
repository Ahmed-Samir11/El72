import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app_colors.dart';

/// Explicit Material 3 token sets for light and dark.
///
/// Every surface, text, and outline color in the app must come from these
/// tokens (no ad-hoc `Colors.*`). Semantic status colors are identical across
/// themes because they already meet WCAG AA against both backgrounds.
class AppThemeData {
  const AppThemeData({
    required this.brightness,
    required this.surface,
    required this.surfaceContainerLow,
    required this.surfaceContainer,
    required this.surfaceContainerHigh,
    required this.onSurface,
    required this.onSurfaceVariant,
    required this.outline,
    required this.primary,
    required this.onPrimary,
    required this.secondary,
    required this.onSecondary,
    required this.tertiary,
    required this.onTertiary,
    required this.success,
    required this.error,
    required this.onError,
    required this.warning,
    required this.info,
    required this.primaryText,
    required this.priceUp,
    required this.priceDown,
  });

  final Brightness brightness;
  final Color surface;
  final Color surfaceContainerLow;
  final Color surfaceContainer;
  final Color surfaceContainerHigh;
  final Color onSurface;
  final Color onSurfaceVariant;
  final Color outline;
  final Color primary;
  final Color onPrimary;
  final Color secondary;
  final Color onSecondary;
  final Color tertiary;
  final Color onTertiary;

  /// Semantic status colors, tuned per theme so each meets WCAG AA (4.5:1)
  /// against that theme's surface. A single tone cannot pass on both the
  /// cream light surface and the deep-brown dark surface.
  final Color success;
  final Color error;
  final Color onError;
  final Color warning;
  final Color info;

  /// Brand primary is too low-contrast to use as *text* on the light cream
  /// surface (2.7:1); this token is the per-theme tone that passes AA.
  final Color primaryText;
  final Color priceUp;
  final Color priceDown;

  ColorScheme toColorScheme() => ColorScheme(
        brightness: brightness,
        error: error,
        onError: onError,
        primary: primary,
        onPrimary: onPrimary,
        secondary: secondary,
        onSecondary: onSecondary,
        tertiary: tertiary,
        onTertiary: onTertiary,
        surface: surface,
        onSurface: onSurface,
        surfaceContainerLow: surfaceContainerLow,
        surfaceContainer: surfaceContainer,
        surfaceContainerHigh: surfaceContainerHigh,
        onSurfaceVariant: onSurfaceVariant,
        outline: outline,
      );
}

/// Builds the app's [ThemeData] from explicit tokens — no seed derivation.
abstract final class AppTheme {
  static const AppThemeData lightData = AppThemeData(
    brightness: Brightness.light,
    surface: Color(0xFFFDFCEB), // Cream page background
    surfaceContainerLow: Color(0xFFFBF7E3),
    surfaceContainer: Color(0xFFF8F3DC),
    surfaceContainerHigh: Color(0xFFF2EBD0),
    onSurface: Color(0xFF3D2B0F), // Dark brown body text
    onSurfaceVariant: Color(0xFF6B5327), // Darkened muted brown (4.5:1+ on cream)
    outline: Color(0xFFD4C49A),
    primary: AppColors.primary,
    onPrimary: Color(0xFF3D2B0F), // 5.2:1 on falcon orange
    secondary: AppColors.secondary,
    onSecondary: Color(0xFF3D2B0F),
    tertiary: AppColors.accent,
    onTertiary: Color(0xFF3D2B0F),
    success: Color(0xFF047857),
    error: Color(0xFFDC2626),
    onError: Colors.white,
    warning: Color(0xFFB45309),
    info: Color(0xFF2563EB),
    primaryText: Color(0xFFC2410C), // Darkened orange, 5.1:1 on cream
    priceUp: Color(0xFFDC2626),
    priceDown: Color(0xFF047857),
  );

  static const AppThemeData darkData = AppThemeData(
    brightness: Brightness.dark,
    surface: Color(0xFF241505), // Deep warm brown page background
    surfaceContainerLow: Color(0xFF2B1B08),
    surfaceContainer: Color(0xFF33220B),
    surfaceContainerHigh: Color(0xFF3B290F),
    onSurface: Color(0xFFF5EEDC), // Warm off-white body text
    onSurfaceVariant: Color(0xFFCBB58A),
    outline: Color(0xFF5A4620),
    primary: AppColors.primary,
    onPrimary: Color(0xFF3D2B0F),
    secondary: AppColors.secondary,
    onSecondary: Color(0xFF3D2B0F),
    tertiary: AppColors.accent,
    onTertiary: Color(0xFF3D2B0F),
    success: Color(0xFF10B981),
    error: Color(0xFFEF4444),
    onError: Colors.black,
    warning: Color(0xFFF59E0B),
    info: Color(0xFF3B82F6),
    primaryText: Color(0xFFF97314), // Primary itself passes on dark brown
    priceUp: Color(0xFFEF4444),
    priceDown: Color(0xFF10B981),
  );

  static ThemeData light() => _build(lightData);
  static ThemeData dark() => _build(darkData);

  static ThemeData _build(AppThemeData t) {
    final scheme = t.toColorScheme();
    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      scaffoldBackgroundColor: t.surface,
      canvasColor: t.surfaceContainerLow,
      cardTheme: CardThemeData(
        color: t.surfaceContainerLow,
        elevation: 0,
        margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: BorderSide(color: t.outline),
        ),
      ),
      inputDecorationTheme: InputDecorationThemeData(
        filled: true,
        fillColor: t.surfaceContainer,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        outlineBorder: BorderSide(color: t.outline),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: scheme.primary, width: 2),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: AppColors.error, width: 2),
        ),
        focusedErrorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: AppColors.error, width: 2),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: scheme.primary,
          foregroundColor: scheme.onPrimary,
          disabledBackgroundColor: t.surfaceContainerHigh,
          disabledForegroundColor: t.onSurfaceVariant,
          elevation: 0,
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          textStyle: const TextStyle(
            fontFamily: 'IBM Plex Sans',
            fontWeight: FontWeight.w600,
            fontSize: 16,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: t.primaryText,
          side: BorderSide(color: t.outline),
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        ),
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: t.surfaceContainerLow,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: t.surfaceContainerLow,
        indicatorColor: scheme.primary,
        labelTextStyle: WidgetStateProperty.resolveWith(
          (states) => TextStyle(
            color: states.contains(WidgetState.selected)
                ? t.primaryText
                : t.onSurfaceVariant,
            fontSize: 12,
          ),
        ),
      ),
      floatingActionButtonTheme: FloatingActionButtonThemeData(
        backgroundColor: scheme.primary,
        foregroundColor: scheme.onPrimary,
      ),
      textTheme: _textTheme(t),
      fontFamily: 'IBM Plex Sans',
    );
  }

  /// Type scale: display / headline / title / body / label.
  static TextTheme _textTheme(AppThemeData t) {
    return TextTheme(
      displayLarge: _t(t, 57, FontWeight.w400, 64),
      displayMedium: _t(t, 45, FontWeight.w400, 52),
      displaySmall: _t(t, 36, FontWeight.w400, 44),
      headlineMedium: _t(t, 28, FontWeight.w600, 36),
      headlineSmall: _t(t, 24, FontWeight.w600, 32),
      titleLarge: _t(t, 22, FontWeight.w600, 28),
      titleMedium: _t(t, 16, FontWeight.w500, 24),
      titleSmall: _t(t, 14, FontWeight.w500, 20),
      bodyLarge: _t(t, 16, FontWeight.w400, 24),
      bodyMedium: _t(t, 14, FontWeight.w400, 20),
      bodySmall: _t(t, 12, FontWeight.w400, 18),
      labelLarge: _t(t, 14, FontWeight.w600, 20),
      labelMedium: _t(t, 12, FontWeight.w500, 18),
      labelSmall: _t(t, 11, FontWeight.w500, 16),
    );
  }

  static TextStyle _t(AppThemeData t, double size, FontWeight weight, double height) =>
      TextStyle(
        fontFamily: 'IBM Plex Sans',
        fontSize: size,
        fontWeight: weight,
        height: height / size,
        color: t.onSurface,
      );
}

extension BuildContextTokens on BuildContext {
  /// The [AppThemeData] tokens for the active theme. Use these for any
  /// semantic color (status, price, brand-as-text) — never a raw hex.
  AppThemeData get appTokens =>
      Theme.of(this).brightness == Brightness.dark
          ? AppTheme.darkData
          : AppTheme.lightData;
}

/// User-selectable theme mode, persisted across launches.
enum AppThemeMode { system, light, dark }

extension AppThemeModeX on AppThemeMode {
  ThemeMode get toThemeMode => switch (this) {
        AppThemeMode.system => ThemeMode.system,
        AppThemeMode.light => ThemeMode.light,
        AppThemeMode.dark => ThemeMode.dark,
      };
}

/// Persists the user's [AppThemeMode] in SharedPreferences.
///
/// Public API:
/// - [mode] reads the stored preference; unknown/corrupt values fall back to
///   [AppThemeMode.system], so a bad stored value can never crash the app.
/// - [setMode] writes the preference. Callers should only invoke this from a
///   user action (the MS2 settings toggle), not on every build.
///
/// Construction requires an already-initialized [SharedPreferences] instance;
/// `main()` guards initialization failure and falls back to system mode.
class ThemePreferenceStore {
  static const _key = 'theme_mode';

  /// Creates a store backed by [prefs].
  ThemePreferenceStore(this._prefs);

  final SharedPreferences _prefs;

  /// The currently persisted [AppThemeMode] (default: system).
  AppThemeMode get mode => switch (_prefs.getString(_key)) {
        'light' => AppThemeMode.light,
        'dark' => AppThemeMode.dark,
        _ => AppThemeMode.system,
      };

  /// Persists [m] as the active theme mode.
  Future<void> setMode(AppThemeMode m) => _prefs.setString(
        _key,
        switch (m) {
          AppThemeMode.light => 'light',
          AppThemeMode.dark => 'dark',
          _ => 'system',
        },
      );
}
