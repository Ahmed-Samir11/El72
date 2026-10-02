import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/l10n/app_localizations.dart';
import 'package:elhaq_tracker/src/core/styles/app_theme.dart';
import 'package:elhaq_tracker/src/data/models/credit_balance_model.dart';
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

/// Repository stub whose `createFromUrl` always fails with a generic error.
class _FailingRepository implements TrackedItemsRepository {
  @override
  Future<List<TrackedItem>> getTrackedItems({bool includeInactive = false})
  async => const [];

  @override
  Future<void> createFromUrl(String url, {double? targetPrice}) async {
    throw Exception('Backend exploded');
  }

  @override
  Future<void> refreshPrice(int itemId) async {}
}

/// Repository stub whose `createFromUrl` always succeeds.
class _SuccessRepository implements TrackedItemsRepository {
  @override
  Future<List<TrackedItem>> getTrackedItems({bool includeInactive = false})
  async => const [];

  @override
  Future<void> createFromUrl(String url, {double? targetPrice}) async {}

  @override
  Future<void> refreshPrice(int itemId) async {}
}

Widget _wrap(Widget child, {TrackedItemsRepository? repository}) {
  return ProviderScope(
    overrides: [
      trackedItemsRepositoryProvider.overrideWithValue(
        repository ?? _OutOfCreditsRepository(),
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

  testWidgets('a non-402 failure keeps the generic SnackBar (no dialog)',
      (tester) async {
    await tester.pumpWidget(
      _wrap(
        Scaffold(body: const CreateTrackerSheet()),
        repository: _FailingRepository(),
      ),
    );

    await tester.enterText(find.byType(TextField).first, 'https://example.com/x');
    await tester.tap(find.text('Start Tracking'));
    await tester.pumpAndSettle();

    // The existing error path is preserved: SnackBar with the error message,
    // and no credit-limit dialog.
    expect(
      find.text('Error: Exception: Backend exploded'),
      findsOneWidget,
    );
    expect(find.byType(AlertDialog), findsNothing);
  });

  testWidgets('successful creation invalidates the credit balance provider',
      (tester) async {
    // A counting balance provider: the sheet must invalidate it after a
    // successful creation so the Profile tab shows the new balance.
    var fetches = 0;
    final container = ProviderContainer(
      overrides: [
        creditBalanceProvider.overrideWith(
          (_) async {
            fetches++;
            return const CreditBalance(balance: 2, tier: 'free');
          },
        ),
        trackedItemsRepositoryProvider.overrideWithValue(
          _SuccessRepository(),
        ),
      ],
    );
    addTearDown(container.dispose);

    // Prime the provider (initial fetch).
    container.read(creditBalanceProvider);
    expect(fetches, 1);

    await tester.pumpWidget(
      ProviderScope(
        parent: container, // ignore: deprecated_member_use
        child: MaterialApp(
          theme: AppTheme.light(),
          localizationsDelegates: const [
            AppLocalizations.delegate,
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
            GlobalCupertinoLocalizations.delegate,
          ],
          supportedLocales: const [Locale('en'), Locale('ar')],
          home: Scaffold(body: const CreateTrackerSheet()),
        ),
      ),
    );

    await tester.enterText(find.byType(TextField).first, 'https://example.com/x');
    await tester.tap(find.text('Start Tracking'));
    await tester.pumpAndSettle();

    // Let the success-path 3.5s refresh timer fire so no timer is left
    // pending when the test ends.
    await tester.pump(const Duration(seconds: 4));

    // The creation succeeded and the invalidated provider must refetch on
    // the next read. (No SnackBar assertion: in this harness the sheet is
    // not a route, so the success-path Navigator.pop pops the home route.)
    container.read(creditBalanceProvider);
    expect(fetches, 2, reason: 'balance provider must be invalidated');
  });
}
