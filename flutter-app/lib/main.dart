import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'l10n/app_localizations.dart';
import 'src/routing/app_router.dart';
import 'src/core/styles/app_theme.dart';
import 'src/data/config.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await AppConfig.initialize();
  // Theme preference is best-effort: if SharedPreferences fails (e.g. missing
  // storage permission on some Android configurations), fall back to the
  // system theme instead of crashing at startup.
  ThemePreferenceStore? themePreference;
  try {
    final prefs = await SharedPreferences.getInstance();
    themePreference = ThemePreferenceStore(prefs);
  } catch (e) {
    debugPrint('Theme preference unavailable, using system mode: $e');
  }
  runApp(ProviderScope(child: ElhaqApp(themePreference: themePreference)));
}

class ElhaqApp extends StatelessWidget {
  const ElhaqApp({super.key, this.themePreference});

  /// Nullable for backward compatibility with tests/embeds that construct
  /// [ElhaqApp] directly; defaults to the system theme mode.
  final ThemePreferenceStore? themePreference;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'إلحق',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      // The persisted mode is honored at launch. Runtime theme switching
      // (a settings toggle) arrives in MS2 with the screens work.
      themeMode: themePreference?.mode.toThemeMode ?? ThemeMode.system,
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      // Arabic-first: ar leads supportedLocales, so any unsupported platform
      // locale falls back to Arabic. Supported devices (ar/en) use their own
      // locale; RTL layout follows automatically from the active locale.
      supportedLocales: const [Locale('ar'), Locale('en')],
      initialRoute: AppRoutes.splash,
      routes: AppRouter.routes,
    );
  }
}
