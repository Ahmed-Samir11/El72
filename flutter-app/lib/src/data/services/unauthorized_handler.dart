import 'package:flutter/widgets.dart';

/// Builds the [ApiClient.onUnauthorized] callback (kept in its own file,
/// without importing `ApiClient`, so the data layer stays acyclic): on 401
/// it routes to [loginRoute], resiliently.
///
/// * An in-flight guard suppresses concurrent invocations while the first
///   navigation is being scheduled, so a burst of 401s (several in-flight
///   requests expiring at once) triggers a single push per burst.
/// * The push uses [NavigatorState.pushNamedAndRemoveUntil] with a
///   never-true predicate, which replaces the whole history: if a 401 that
///   outlived the burst fires while the user is already on the login screen,
///   the navigation is idempotent (login is re-pushed in place, no stacked
///   duplicate routes).
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
