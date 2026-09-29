/// MS1 tests: WCAG AA contrast for every token pair, theme construction,
/// and theme-mode persistence.
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:elhaq_tracker/src/core/styles/app_colors.dart';
import 'package:elhaq_tracker/src/core/styles/app_theme.dart';

double _relativeLuminance(Color c) {
  double channel(double v) {
    // Color.r/g/b are already in 0..1.
    return v <= 0.04045
        ? v / 12.92
        : math.pow((v + 0.055) / 1.055, 2.4) as double;
  }

  return 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b);
}

double _contrast(Color a, Color b) {
  final l1 = _relativeLuminance(a);
  final l2 = _relativeLuminance(b);
  final lighter = math.max(l1, l2);
  final darker = math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

void main() {
  const aa = 4.5; // WCAG AA for body text

  group('token contrast (WCAG AA)', () {
    test('light tokens meet 4.5:1', () {
      final t = AppTheme.lightData;
      expect(_contrast(t.onSurface, t.surface), greaterThan(aa));
      expect(_contrast(t.onSurfaceVariant, t.surface), greaterThan(aa));
      expect(_contrast(t.onPrimary, t.primary), greaterThan(aa));
      expect(_contrast(t.onSecondary, t.secondary), greaterThan(aa));
      expect(_contrast(t.onTertiary, t.tertiary), greaterThan(aa));
    });

    test('dark tokens meet 4.5:1', () {
      final t = AppTheme.darkData;
      expect(_contrast(t.onSurface, t.surface), greaterThan(aa));
      expect(_contrast(t.onSurfaceVariant, t.surface), greaterThan(aa));
      expect(_contrast(t.onPrimary, t.primary), greaterThan(aa));
      expect(_contrast(t.onSecondary, t.secondary), greaterThan(aa));
      expect(_contrast(t.onTertiary, t.tertiary), greaterThan(aa));
    });

    test('textSecondary contrast fix (was ~3.9:1)', () {
      expect(
        _contrast(AppColors.textSecondary, AppColors.backgroundLight),
        greaterThan(aa),
      );
    });

    test('per-theme semantic colors meet AA on their own surface', () {
      for (final t in [AppTheme.lightData, AppTheme.darkData]) {
        for (final s in [
          t.success,
          t.error,
          t.warning,
          t.info,
          t.priceUp,
          t.priceDown,
        ]) {
          expect(
            _contrast(s, t.surface),
            greaterThan(aa),
            reason: '$s on ${t.surface}',
          );
        }
      }
    });

    test('onError meets AA against error in both themes', () {
      for (final t in [AppTheme.lightData, AppTheme.darkData]) {
        expect(
          _contrast(t.onError, t.error),
          greaterThan(aa),
          reason: 'onError on error (${t.brightness})',
        );
      }
    });

    test('primaryText meets AA as text on both surfaces', () {
      for (final t in [AppTheme.lightData, AppTheme.darkData]) {
        expect(
          _contrast(t.primaryText, t.surface),
          greaterThan(aa),
          reason: 'primaryText on ${t.surface}',
        );
      }
    });
  });

  group('ThemeData construction', () {
    test('light theme uses explicit tokens', () {
      final t = AppTheme.light();
      expect(t.colorScheme.surface, AppTheme.lightData.surface);
      expect(t.colorScheme.onSurface, AppTheme.lightData.onSurface);
      expect(t.scaffoldBackgroundColor, AppTheme.lightData.surface);
      expect(t.textTheme.bodyLarge?.fontFamily, 'IBM Plex Sans');
      expect(t.useMaterial3, isTrue);
    });

    test('dark theme uses explicit tokens', () {
      final t = AppTheme.dark();
      expect(t.colorScheme.surface, AppTheme.darkData.surface);
      expect(t.colorScheme.onSurface, AppTheme.darkData.onSurface);
      expect(t.scaffoldBackgroundColor, AppTheme.darkData.surface);
    });

    test('component themes present and use tokens', () {
      final t = AppTheme.light();
      expect(t.cardTheme.color, AppTheme.lightData.surfaceContainerLow);
      expect(t.scaffoldBackgroundColor, AppTheme.lightData.surface);
      expect(t.elevatedButtonTheme.style?.backgroundColor, isNotNull);
      expect(
        t.bottomSheetTheme.backgroundColor,
        AppTheme.lightData.surfaceContainerLow,
      );
      expect(t.textTheme.headlineMedium, isNotNull);
    });

    test('price text styles use bundled monospace and theme color', () {
      final onSurface = AppTheme.lightData.onSurface;
      expect(AppColors.priceTextStyle(onSurface).fontFamily, 'JetBrains Mono');
      expect(AppColors.priceTextStyle(onSurface).color, onSurface);
      expect(AppColors.priceTextStyleLarge(onSurface).color, onSurface);
    });
  });

  group('ThemePreferenceStore', () {
    setUp(() => SharedPreferences.setMockInitialValues({}));

    test('defaults to system', () async {
      final store = ThemePreferenceStore(await SharedPreferences.getInstance());
      expect(store.mode, AppThemeMode.system);
    });

    test('corrupt/unrecognized stored value falls back to system', () async {
      SharedPreferences.setMockInitialValues({'theme_mode': 'garbage-value'});
      final store = ThemePreferenceStore(await SharedPreferences.getInstance());
      expect(store.mode, AppThemeMode.system);
    });

    test('persists and reads back each mode', () async {
      final prefs = await SharedPreferences.getInstance();
      final store = ThemePreferenceStore(prefs);
      for (final m in AppThemeMode.values) {
        await store.setMode(m);
        expect(store.mode, m);
      }
      // Survives a new store instance over the same prefs.
      final store2 = ThemePreferenceStore(prefs);
      expect(store2.mode, AppThemeMode.dark);
    });

    test('maps to Flutter ThemeMode', () {
      expect(AppThemeMode.system.toThemeMode, ThemeMode.system);
      expect(AppThemeMode.light.toThemeMode, ThemeMode.light);
      expect(AppThemeMode.dark.toThemeMode, ThemeMode.dark);
    });
  });
}
