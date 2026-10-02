import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/data/services/unauthorized_handler.dart';

/// Counts how many times the login route builder ran — each distinct route
/// entry builds once, so two pushes mean two builds.
int _loginBuilds = 0;

Widget _testApp(GlobalKey<NavigatorState> navigatorKey) {
  return MaterialApp(
    navigatorKey: navigatorKey,
    home: const Scaffold(body: Text('home')),
    routes: {
      '/login': (context) {
        _loginBuilds++;
        return const Scaffold(body: Text('login'));
      },
    },
  );
}

void main() {
  const loginRoute = '/login';

  setUp(() {
    _loginBuilds = 0;
  });

  testWidgets('a 401 routes to the login screen', (tester) async {
    final navigatorKey = GlobalKey<NavigatorState>();
    final handler = buildUnauthorizedHandler(
      navigatorKey,
      loginRoute: loginRoute,
    );

    await tester.pumpWidget(_testApp(navigatorKey));
    expect(find.text('home'), findsOneWidget);

    // Start the handler without awaiting (it defers to end-of-frame), let a
    // frame land, then await completion.
    final pending = handler();
    await tester.pump();
    await tester.pumpAndSettle();
    await expectLater(pending, completes);

    expect(find.text('login'), findsOneWidget);
    expect(_loginBuilds, 1);
  });

  testWidgets('a burst of concurrent 401s routes to login exactly once', (
    tester,
  ) async {
    final navigatorKey = GlobalKey<NavigatorState>();
    final handler = buildUnauthorizedHandler(
      navigatorKey,
      loginRoute: loginRoute,
    );

    await tester.pumpWidget(_testApp(navigatorKey));

    // Several requests expire at once: start every callback (they run
    // synchronously until the first await), then let a frame land so the
    // in-flight navigation can proceed.
    final pending = <Future<void>>[];
    for (var i = 0; i < 5; i++) {
      pending.add(handler());
    }
    await tester.pump();
    await tester.pumpAndSettle();
    await Future.wait(pending);

    expect(find.text('login'), findsOneWidget);
    expect(_loginBuilds, 1, reason: 'login must be pushed exactly once');
    // home was removed from the history; no stacked duplicate routes.
    expect(find.text('home'), findsNothing);
  });

  testWidgets(
    'a later, non-concurrent 401 while on login re-pushes in place (single '
    'login at rest)',
    (tester) async {
      final navigatorKey = GlobalKey<NavigatorState>();
      final handler = buildUnauthorizedHandler(
        navigatorKey,
        loginRoute: loginRoute,
      );

      await tester.pumpWidget(_testApp(navigatorKey));
      final pending = handler();
      await tester.pump();
      await tester.pumpAndSettle();
      await expectLater(pending, completes);
      expect(_loginBuilds, 1);

      // A request that outlived the burst also 401s: we are already on the
      // login screen. pushNamedAndRemoveUntil with a never-true predicate
      // replaces the whole history in place — one login route at rest, never
      // a stacked duplicate — but the login route IS rebuilt (its form state
      // resets). In production this path is effectively unreachable for stale
      // 401s: ApiClient's token-identity check only fires the handler while
      // the stored token still matches the one the failed request carried,
      // so a delayed 401 arriving after re-login is ignored entirely.
      final second = handler();
      await tester.pump();
      await tester.pumpAndSettle();
      await expectLater(second, completes);

      expect(find.text('login'), findsOneWidget);
      expect(find.text('home'), findsNothing);
      // Pin the actual contract: the route was re-pushed (rebuilt), in place.
      expect(_loginBuilds, 2);
    },
  );

  testWidgets('a null navigator state is swallowed, not thrown', (
    tester,
  ) async {
    // A key that is never attached to a navigator: the handler must await the
    // frame, see a null state, and complete quietly instead of throwing.
    final attachedKey = GlobalKey<NavigatorState>();
    final detachedKey = GlobalKey<NavigatorState>();
    final handler = buildUnauthorizedHandler(
      detachedKey,
      loginRoute: loginRoute,
    );

    await tester.pumpWidget(_testApp(attachedKey));

    final pending = handler();
    await tester.pump(); // let the end-of-frame deferral fire
    await expectLater(pending, completes);
  });
}
