import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/l10n/app_localizations.dart';
import 'package:elhaq_tracker/src/core/styles/app_theme.dart';
import 'package:elhaq_tracker/src/data/models/credit_balance_model.dart';
import 'package:elhaq_tracker/src/data/providers.dart';
import 'package:elhaq_tracker/src/ui/dashboard/dashboard_page.dart';

void main() {
  testWidgets('profile tab shows the live credit balance', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          creditBalanceProvider.overrideWith(
            (_) async => const CreditBalance(balance: 3, tier: 'free'),
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

    // Switch to the Profile tab.
    await tester.tap(find.text('Profile'));
    await tester.pumpAndSettle();

    expect(find.text('You have 3 trackers left'), findsOneWidget);
  });
}
