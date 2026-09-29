import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:elhaq_tracker/main.dart';
import 'package:elhaq_tracker/src/core/styles/app_theme.dart';

/// Verifies the WS3 edge-to-edge system UI builder: the status and
/// navigation bars must follow the active theme (surface color, light icons
/// on dark, dark icons on light).
void main() {
  Future<ThemePreferenceStore> storeWith(AppThemeMode mode) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final store = ThemePreferenceStore(prefs);
    await store.setMode(mode);
    return store;
  }

  testWidgets('light theme uses dark icons on the surface color', (
    tester,
  ) async {
    final store = await storeWith(AppThemeMode.light);
    await tester.pumpWidget(ElhaqApp(themePreference: store));
    final region =
        tester.widget(
              find.byWidgetPredicate(
                (w) => w is AnnotatedRegion<SystemUiOverlayStyle>,
              ),
            )
            as AnnotatedRegion<SystemUiOverlayStyle>;
    final style = region.value;
    expect(style.statusBarIconBrightness, Brightness.dark);
    expect(style.systemNavigationBarIconBrightness, Brightness.dark);
    // Light theme surface is the cream token.
    expect(style.statusBarColor, const Color(0xFFFDFCEB));
  });

  testWidgets('dark theme uses light icons on the surface color', (
    tester,
  ) async {
    final store = await storeWith(AppThemeMode.dark);
    await tester.pumpWidget(ElhaqApp(themePreference: store));
    final region =
        tester.widget(
              find.byWidgetPredicate(
                (w) => w is AnnotatedRegion<SystemUiOverlayStyle>,
              ),
            )
            as AnnotatedRegion<SystemUiOverlayStyle>;
    final style = region.value;
    expect(style.statusBarIconBrightness, Brightness.light);
    expect(style.systemNavigationBarIconBrightness, Brightness.light);
    // Dark theme surface is the deep-brown token.
    expect(style.statusBarColor, const Color(0xFF241505));
  });
}
