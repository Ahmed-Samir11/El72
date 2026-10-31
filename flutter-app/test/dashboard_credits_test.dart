import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/l10n/app_localizations.dart';
import 'package:elhaq_tracker/src/core/styles/app_theme.dart';
import 'package:elhaq_tracker/src/data/config.dart';
import 'package:elhaq_tracker/src/data/models/credit_balance_model.dart';
import 'package:elhaq_tracker/src/data/models/usage_limits_model.dart';
import 'package:elhaq_tracker/src/data/providers.dart';
import 'package:elhaq_tracker/src/ui/dashboard/dashboard_page.dart';

Widget _wrap(Future<CreditBalance> balanceFuture, {Locale? locale}) {
  return ProviderScope(
    overrides: [
      creditBalanceProvider.overrideWith((_) => balanceFuture),
      // A payments-off run watches the fair-use card instead; pin it so this
      // file never reaches the real repository.
      usageLimitsProvider.overrideWith(
        (_) async => const UsageLimits(activeTrackers: 0, cap: 100),
      ),
    ],
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
  testWidgets('profile tab shows the live credit balance', (tester) async {
    await tester.pumpWidget(
      _wrap(Future.value(const CreditBalance(balance: 3, tier: 'free'))),
    );

    // Switch to the Profile tab.
    await _gotoProfile(tester);

    if (!AppConfig.paymentsEnabled) {
      // A free release has no credit tile at all: no balance line, no "Current
      // plan" heading and no "Manage" affordance that could be read as a paywall.
      // The ProviderScope still injects a balance - if the tile rendered, this
      // is exactly where it would show.
      expect(find.text('You have 3 trackers left'), findsNothing);
      expect(find.text('Manage'), findsNothing);
      expect(find.text('Current plan'), findsNothing);
      return;
    }

    expect(find.text('You have 3 trackers left'), findsOneWidget);
    expect(find.text('Manage'), findsOneWidget);
  });

  // The remaining cases are credit copy, which a build compiled with
  // ENABLE_PAYMENTS=false never renders: the whole tile is absent (asserted
  // above), so these run only in the payments-on posture.
  group('credit copy', () {
    testWidgets('singular form is used for a balance of 1', (tester) async {
      await tester.pumpWidget(
        _wrap(Future.value(const CreditBalance(balance: 1, tier: 'free'))),
      );

      await _gotoProfile(tester);

      expect(find.text('You have 1 tracker left'), findsOneWidget);
    });

    testWidgets('zero balance renders the plural form', (tester) async {
      await tester.pumpWidget(
        _wrap(Future.value(const CreditBalance(balance: 0, tier: 'free'))),
      );

      await _gotoProfile(tester);

      expect(find.text('You have 0 trackers left'), findsOneWidget);
    });

    testWidgets('loading state falls back to the free-plan label', (
      tester,
    ) async {
      // A never-completing future keeps the provider in the loading state.
      final completer = Completer<CreditBalance>();
      await tester.pumpWidget(_wrap(completer.future));

      await _gotoProfile(tester);

      expect(find.text('Free plan'), findsOneWidget);
    });

    testWidgets('error state falls back to the free-plan label', (
      tester,
    ) async {
      // Throwing lazily inside the provider (rather than a pre-completed
      // Future.error) so the error is handled by Riverpod, not the test zone.
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            creditBalanceProvider.overrideWith(
              (_) async => throw Exception('boom'),
            ),
          ],
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
          ),
        ),
      );

      await _gotoProfile(tester);

      expect(find.text('Free plan'), findsOneWidget);
    });

    testWidgets('Arabic uses the correct plural form for a balance of 1', (
      tester,
    ) async {
      await tester.pumpWidget(
        _wrap(
          Future.value(const CreditBalance(balance: 1, tier: 'free')),
          locale: const Locale('ar'),
        ),
      );

      await _gotoProfile(tester, locale: const Locale('ar'));

      expect(find.text('لديك متتبع واحد متبقٍ'), findsOneWidget);
    });
    // Skip the whole group in a build compiled with ENABLE_PAYMENTS=false.
  }, skip: !AppConfig.paymentsEnabled);
}
