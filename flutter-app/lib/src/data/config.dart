import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Central configuration for the إلحق app.
///
/// Values are overridable at build/run time via `--dart-define`, e.g.:
/// ```
/// flutter run \
///   --dart-define=API_BASE_URL=http://192.168.1.106:8000 \
/// ```
///
/// Demo mode is a persistent runtime setting and defaults to Full (live) mode.
class AppConfig {
  /// The dev-only loopback address the Android emulator uses to reach services
  /// running on the host machine. A release build must never ship pointing
  /// here — that host only exists on the developer's machine.
  static const String _emulatorDefaultUrl = 'http://10.0.2.2:8000';

  /// The emulator loopback host, used to detect dev-only endpoints by host
  /// (scheme/port independent).
  static const String _emulatorHost = '10.0.2.2';

  /// Base URL of the Elhaq API gateway (`services/api`). Overridable at build
  /// time via `--dart-define=API_BASE_URL=<prod>`. Defaults to the emulator
  /// loopback address for local development.
  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: _emulatorDefaultUrl,
  );

  static const String _demoModeKey = 'demo_mode';
  static late SharedPreferences _preferences;
  static bool demoMode = false;

  /// True if [url] points at the dev-only emulator loopback host, regardless
  /// of scheme or port. Matching the host (not the exact string) catches both
  /// `http://10.0.2.2:8000` and a hypothetical `https://10.0.2.2:8443`.
  static bool isEmulatorDefaultUrl(String url) {
    try {
      return Uri.parse(url).host == _emulatorHost;
    } catch (_) {
      return false;
    }
  }

  /// True if [url] is a production-grade endpoint: HTTPS and not the dev-only
  /// emulator loopback address. A release build must point at such a URL —
  /// cleartext (`http://`) endpoints are rejected because Android blocks
  /// cleartext traffic by default and a release must be tamper-resistant.
  static bool isProductionEndpoint(String url) =>
      url.startsWith('https://') && !isEmulatorDefaultUrl(url);

  static Future<void> initialize() async {
    _preferences = await SharedPreferences.getInstance();
    // Demo mode defaults to false (live) so first-run is the real API path.
    demoMode = _preferences.getBool(_demoModeKey) ?? false;
    _failFastOnEmulatorEndpointInRelease();
  }

  /// In a release build the API base URL must be a real production endpoint:
  /// HTTPS, and not the dev-only emulator loopback address. If it is not, the
  /// build was not given a proper production `--dart-define`, so we throw at
  /// startup rather than ship an app that points at nothing or leaks traffic
  /// in cleartext. Debug and profile builds keep the emulator default for
  /// local development, so this never fires there.
  static void _failFastOnEmulatorEndpointInRelease() {
    if (!kReleaseMode) return;
    if (isEmulatorDefaultUrl(apiBaseUrl)) {
      throw StateError(
        'Release build is configured with the emulator API base URL '
        "'$apiBaseUrl'. Rebuild with a production HTTPS endpoint via "
        '--dart-define=API_BASE_URL=https://<prod-host> (see '
        '.github/workflows/ci.yml).',
      );
    }
    if (!apiBaseUrl.startsWith('https://')) {
      throw StateError(
        'Release build API base URL "$apiBaseUrl" is not HTTPS. A release '
        'must use a production HTTPS endpoint; rebuild with '
        '--dart-define=API_BASE_URL=https://<prod-host> (see '
        '.github/workflows/ci.yml).',
      );
    }
  }

  static Future<void> setDemoMode(bool enabled) async {
    demoMode = enabled;
    await _preferences.setBool(_demoModeKey, enabled);
  }
}
