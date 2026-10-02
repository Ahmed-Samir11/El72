import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/l10n/app_localizations.dart';
import 'package:elhaq_tracker/src/core/styles/app_theme.dart';
import 'package:elhaq_tracker/src/data/models/tracked_item_model.dart';
import 'package:elhaq_tracker/src/data/providers.dart';
import 'package:elhaq_tracker/src/data/repositories/tracked_items_repository.dart';
import 'package:elhaq_tracker/src/ui/create_tracker_sheet.dart';
import 'package:elhaq_tracker/src/ui/subscription_screen.dart';

/// Repository stub whose `createFromUrl` always fails with the 402 signal.
class _OutOfCreditsRepository implements TrackedItemsRepository {
  @override
  Future<List<TrackedItem>> getTrackedItems({bool includeInactive = false})
  async => const [];

  @override
  Future<void> createFromUrl(String url, {double? targetPrice}) async {
    throw const InsufficientCreditsException('Insufficient credits');
  }

  @override
  Future<void> refreshPrice(int itemId) async {}
}

Widget _wrap(Widget child) {
  return ProviderScope(
    overrides: [
      trackedItemsRepositoryProvider.overrideWithValue(
        _OutOfCreditsRepository(),
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
      home: child,
    ),
  );
}

void main() {
  testWidgets('402 shows the friendly limit dialog with an upgrade button',
      (tester) async {
    await tester.pumpWidget(
      _wrap(Scaffold(body: const CreateTrackerSheet())),
    );

    // Fill the URL field so the tap proceeds to the network call.
    await tester.enterText(find.byType(TextField).first, 'https://example.com/x');
    await tester.tap(find.text('Start Tracking'));
    await tester.pumpAndSettle();

    // Friendly dialog appears instead of a raw error SnackBar.
    expect(find.text("You've reached your limit"), findsOneWidget);
    expect(find.text('Upgrade plan'), findsOneWidget);
    expect(find.byType(SnackBar), findsNothing);
  });

  testWidgets('upgrade button navigates to the subscription screen',
      (tester) async {
    await tester.pumpWidget(
      _wrap(Scaffold(body: const CreateTrackerSheet())),
    );

    await tester.enterText(find.byType(TextField).first, 'https://example.com/x');
    await tester.tap(find.text('Start Tracking'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Upgrade plan'));
    await tester.pumpAndSettle();

    // The plans screen is on top: its title is visible.
    expect(find.text('Subscription Plans'), findsOneWidget);
  });

  testWidgets('"Not now" dismisses the dialog without navigating',
      (tester) async {
    await tester.pumpWidget(
      _wrap(Scaffold(body: const CreateTrackerSheet())),
    );

    await tester.enterText(find.byType(TextField).first, 'https://example.com/x');
    await tester.tap(find.text('Start Tracking'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Not now'));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsNothing);
    expect(find.byType(SubscriptionScreen), findsNothing);
  });
}
