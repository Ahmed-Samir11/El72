import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/l10n/app_localizations.dart';
import 'package:elhaq_tracker/src/core/styles/app_theme.dart';
import 'package:elhaq_tracker/src/data/config.dart';
import 'package:elhaq_tracker/src/data/models/usage_limits_model.dart';
import 'package:elhaq_tracker/src/data/providers.dart';
import 'package:elhaq_tracker/src/ui/dashboard/dashboard_page.dart';

Widget _wrap(Future<UsageLimits> Function() usage, {Locale? locale}) {
  return ProviderScope(
    // Built lazily, so a failing load is raised inside the provider (where
    // the UI handles it) rather than as an unhandled error in the test zone.
    overrides: [usageLimitsProvider.overrideWith((_) => usage())],
    child: MaterialApp(
      theme: AppTheme.light(),
      locale: locale,
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: const [Locale('en'), Locale('ar')],
      home: const DashboardPage(),
    ),
  );
}

Future<void> _gotoProfile(WidgetTester tester, {Locale? locale}) async {
  final label = locale?.languageCode == 'ar' ? 'الملف الشخصي' : 'Profile';
  await tester.tap(find.text(label));
  await tester.pumpAndSettle();
}

void main() {
  // The fair-use card is the free build's account state; a payments build keeps
  // the credit tile instead (dashboard_credits_test.dart covers that posture).
  group('free build profile card', () {
    testWidgets('shows the active count against the cap', (tester) async {
      await tester.pumpWidget(
        _wrap(() async => const UsageLimits(activeTrackers: 7, cap: 100)),
      );
      await _gotoProfile(tester);

      expect(find.text('Your trackers'), findsOneWidget);
      expect(find.text('Tracking 7 of up to 100'), findsOneWidget);
      expect(find.text('Manage'), findsNothing);
    });

    testWidgets('an empty account names the ceiling', (tester) async {
      await tester.pumpWidget(
        _wrap(() async => const UsageLimits(activeTrackers: 0, cap: 100)),
      );
      await _gotoProfile(tester);

      expect(find.text('No trackers yet. Up to 100 at once'), findsOneWidget);
    });

    testWidgets('no cap from the server reads as unlimited, not as 0', (
      tester,
    ) async {
      await tester.pumpWidget(
        _wrap(() async => const UsageLimits(activeTrackers: 3)),
      );
      await _gotoProfile(tester);

      expect(
        find.text('Tracking 3 trackers, no limit in this build'),
        findsOneWidget,
      );
    });

    testWidgets('a failed load leaves the heading without a guessed count', (
      tester,
    ) async {
      await tester.pumpWidget(_wrap(() async => throw Exception('offline')));
      await _gotoProfile(tester);

      expect(find.text('Your trackers'), findsOneWidget);
      expect(find.textContaining('Tracking'), findsNothing);
      expect(find.textContaining('offline'), findsNothing);
    });

    testWidgets('Arabic uses the dual form for two trackers', (tester) async {
      const arabic = Locale('ar');
      await tester.pumpWidget(
        _wrap(
          () async => const UsageLimits(activeTrackers: 2, cap: 100),
          locale: arabic,
        ),
      );
      await _gotoProfile(tester, locale: arabic);

      expect(find.text('متتبعاتك'), findsOneWidget);
      expect(
        find.text('لديك متتبعان نشطان من أصل 100 كحد أقصى'),
        findsOneWidget,
      );
    });
  }, skip: AppConfig.paymentsEnabled);
}
