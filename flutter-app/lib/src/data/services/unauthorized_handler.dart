import 'package:flutter/widgets.dart';

/// Builds the [ApiClient.onUnauthorized] callback (kept in its own file,
/// without importing `ApiClient`, so the data layer stays acyclic): on 401
/// it routes to [loginRoute], resiliently.
///
/// Layering note: this file lives under `data/services` but intentionally
/// depends on `widgets.dart` (NavigatorState) — it is the single sanctioned
/// app-level exception where the data layer's 401 hook reaches the UI, kept
/// in one file so `ApiClient` itself never imports widgets or the router.
///
/// * An in-flight guard suppresses concurrent invocations while the first
///   navigation is being scheduled, so a burst of 401s (several in-flight
///   requests expiring at once) triggers a single push per burst.
/// * A *later*, non-concurrent invocation re-pushes login in place
///   (pushNamedAndRemoveUntil with a never-true predicate replaces the whole
///   history, so there is at most one login route at rest — but its form
///   state is rebuilt). In production this path is effectively unreachable
///   for stale 401s: `ApiClient`'s token-identity check only fires this
///   callback when the stored token still matches the one the failed request
///   was sent with, so a delayed 401 arriving after re-login is ignored.
/// * All navigation errors are swallowed: the data layer runs this callback
///   fire-and-forget, and a broken navigator must never crash the app.
Future<void> Function() buildUnauthorizedHandler(
  GlobalKey<NavigatorState> navigatorKey, {
  required String loginRoute,
}) {
  var navigationInFlight = false;
  return () async {
    if (navigationInFlight) return;
    navigationInFlight = true;
    try {
      // Defer to the end of the frame so the push never races an in-flight
      // route transition (which would throw).
      await WidgetsBinding.instance.endOfFrame;
      navigatorKey.currentState?.pushNamedAndRemoveUntil(
        loginRoute,
        (route) => false,
      );
    } catch (e) {
      debugPrint('401 navigation to login failed: $e');
    } finally {
      navigationInFlight = false;
    }
  };
}
