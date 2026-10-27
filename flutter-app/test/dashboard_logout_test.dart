import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/l10n/app_localizations.dart';
import 'package:elhaq_tracker/src/core/styles/app_theme.dart';
import 'package:elhaq_tracker/src/data/models/chat_message_model.dart';
import 'package:elhaq_tracker/src/data/models/credit_balance_model.dart';
import 'package:elhaq_tracker/src/data/providers.dart';
import 'package:elhaq_tracker/src/data/repositories/auth_repository.dart';
import 'package:elhaq_tracker/src/routing/app_router.dart';
import 'package:elhaq_tracker/src/ui/dashboard/dashboard_page.dart';

/// Counts how many times the welcome route builder ran — each distinct route
/// entry builds once, so two builds would mean the navigation happened twice.
int _welcomeBuilds = 0;

class _FakeAuthRepository extends AuthRepository {
  int _logoutCalls = 0;
  int get logoutCalls => _logoutCalls;

  // The real implementation deletes a key from FlutterSecureStorage, which has
  // no injection point (`const FlutterSecureStorage()` is a private final).
  // Counting the call is enough: the handler's job is to invalidate the app's
  // state afterwards, not to touch storage.
  @override
  Future<void> logout() async {
    _logoutCalls++;
  }
}

ChatMessageModel _message(String content) => ChatMessageModel(
  id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaaaaaa',
  sessionId: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbbbbbb',
  role: 'user',
  content: content,
  createdAt: DateTime(2025, 10, 26, 12),
);

/// The dashboard under an [UncontrolledProviderScope] so the test can read
/// providers from the same container the page uses, and under a route table
/// that stubs `/welcome` — the handler ends with
/// `pushNamedAndRemoveUntil(AppRoutes.welcome, …)`, and the real
/// [WelcomePage] would pull in repositories the test never wants to reach.
Widget _app(ProviderContainer container) {
  return UncontrolledProviderScope(
    container: container,
    child: MaterialApp(
      theme: AppTheme.light(),
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: const [Locale('en'), Locale('ar')],
      home: const DashboardPage(),
      routes: {
        AppRoutes.welcome: (context) {
          _welcomeBuilds++;
          return const Scaffold(
            body: Center(child: Text('signed-out welcome')),
          );
        },
      },
    ),
  );
}

ProviderContainer _containerWith(_FakeAuthRepository auth) {
  final container = ProviderContainer(
    overrides: [
      authRepositoryProvider.overrideWithValue(auth),
      creditBalanceProvider.overrideWith(
        (ref) async => const CreditBalance(balance: 7, tier: 'free'),
      ),
    ],
  );
  addTearDown(container.dispose);
  return container;
}

void main() {
  setUp(() {
    _welcomeBuilds = 0;
  });

  testWidgets(
    'logging out from the Profile tab leaves the chat empty for the next '
    'account',
    (tester) async {
      final auth = _FakeAuthRepository();
      final container = _containerWith(auth);

      // A conversation the previous user was in the middle of: a session id
      // has been issued and two messages are on screen.
      final before = container.read(chatConversationProvider);
      before.sessionId = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbbbbbb';
      before.addMessage(_message('2k monitor under 12k'));
      before.addMessage(_message('Samsung Odyssey G5 27'));
      expect(before.messages, hasLength(2));

      await tester.pumpWidget(_app(container));

      // Switch to the Profile tab and tap its Log out button.
      await tester.tap(find.text('Profile'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Log out'));
      await tester.pump();
      await tester.pumpAndSettle();

      expect(auth.logoutCalls, 1);
      expect(_welcomeBuilds, 1);
      expect(find.text('signed-out welcome'), findsOneWidget);

      // The contract `chatConversationProvider`'s doc states: invalidate on
      // logout. The instance the page was wired to is dead, and whoever reads
      // the provider next gets a clean one — not the previous account's chat.
      expect(before.isDisposed, isTrue);
      final after = container.read(chatConversationProvider);
      expect(identical(after, before), isFalse);
      expect(after.messages, isEmpty);
      expect(after.searchResults, isEmpty);
      expect(after.sessionId, isNull);
      expect(after.draft, isEmpty);

      // And the dead instance really is inert: a late write from a page whose
      // tab is off screen cannot resurrect it.
      before.addMessage(_message('written after logout'));
      before.sessionId = 'cccccccc-cccc-cccc-cccc-cccccccccccccc';
      expect(before.messages, hasLength(2));
      expect(before.sessionId, 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbbbbbb');
      expect(after.messages, isEmpty);
    },
  );

  testWidgets(
    'logging out rebuilds the chat even when the chat tab was never opened',
    (tester) async {
      // Nothing rendered the chat tab, so the provider is created on demand
      // and only ever has to be disposable; the handler must not skip the
      // invalidation just because the tab is closed.
      final auth = _FakeAuthRepository();
      final container = _containerWith(auth);
      final before = container.read(chatConversationProvider);

      await tester.pumpWidget(_app(container));
      await tester.tap(find.text('Profile'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Log out'));
      await tester.pump();
      await tester.pumpAndSettle();

      expect(auth.logoutCalls, 1);
      expect(before.isDisposed, isTrue);
      expect(
        identical(container.read(chatConversationProvider), before),
        isFalse,
      );
    },
  );
}
