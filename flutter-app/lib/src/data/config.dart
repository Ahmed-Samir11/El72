import 'package:shared_preferences/shared_preferences.dart';

/// Central configuration for the إلحق app.
///
/// Values are overridable at build/run time via `--dart-define`, e.g.:
/// ```
/// flutter run \
///   --dart-define=API_BASE_URL=http://192.168.1.106:8000 \
/// ```
///
/// Demo mode is a persistent runtime setting and defaults to Full mode.
class AppConfig {
  /// Base URL of the Elhaq API gateway (`services/api`). Android emulators
  /// reach services running on the host machine through `10.0.2.2`.
  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000',
  );

  static const String _demoModeKey = 'demo_mode';
  static late SharedPreferences _preferences;
  static bool demoMode = false;

  static Future<void> initialize() async {
    _preferences = await SharedPreferences.getInstance();
    demoMode = _preferences.getBool(_demoModeKey) ?? false;
  }

  static Future<void> setDemoMode(bool enabled) async {
    demoMode = enabled;
    await _preferences.setBool(_demoModeKey, enabled);
  }
}
