/// Central, build-time configuration for the Elhaq app.
///
/// Values are overridable at build/run time via `--dart-define`, e.g.:
/// ```
/// flutter run \
///   --dart-define=API_BASE_URL=http://192.168.1.106:8000 \
///   --dart-define=DEMO_MODE=true
/// ```
///
/// `DEMO_MODE` (default `true`) lets the UI render realistic demo data when
/// the backend is unreachable, so the investor demo works end-to-end even
/// before Engineer B's public endpoints (`/stats`, `/deals/live`,
/// `/price-history/{sku}`) are merged.
class AppConfig {
  /// Base URL of the Elhaq API gateway (`services/api`).
  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://localhost:8000',
  );

  /// When true, repositories fall back to [DemoData] if the API is
  /// unreachable or returns an error.
  static const bool demoMode = bool.fromEnvironment(
    'DEMO_MODE',
    defaultValue: true,
  );
}
