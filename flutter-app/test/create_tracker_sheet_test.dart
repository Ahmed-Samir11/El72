import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/l10n/app_localizations.dart';
import 'package:elhaq_tracker/src/core/styles/app_theme.dart';
import 'package:elhaq_tracker/src/data/config.dart';
import 'package:elhaq_tracker/src/data/models/credit_balance_model.dart';
import 'package:elhaq_tracker/src/data/models/tracked_item_model.dart';
import 'package:elhaq_tracker/src/data/providers.dart';
import 'package:elhaq_tracker/src/data/repositories/tracked_items_repository.dart';
import 'package:elhaq_tracker/src/ui/create_tracker_sheet.dart';
import 'package:elhaq_tracker/src/ui/subscription_screen.dart';

/// Repository stub whose `createFromUrl` always fails with the 402 signal.
class _OutOfCreditsRepository implements TrackedItemsRepository {
  @override
  Future<List<TrackedItem>> getTrackedItems({
    bool includeInactive = false,
  }) async => const [];

  @override
  Future<void> createFromUrl(String url, {double? targetPrice}) async {
    throw const InsufficientCreditsException('Insufficient credits');
  }

  @override
  Future<void> refreshPrice(int itemId) async {}

  @override
  Future<void> deleteTrackedItem(int itemId) async {}
}

/// Repository stub whose `createFromUrl` always fails with a generic error.
class _FailingRepository implements TrackedItemsRepository {
  @override
  Future<List<TrackedItem>> getTrackedItems({
    bool includeInactive = false,
  }) async => const [];

  @override
  Future<void> createFromUrl(String url, {double? targetPrice}) async {
    throw Exception('Backend exploded');
  }

  @override
  Future<void> refreshPrice(int itemId) async {}

  @override
  Future<void> deleteTrackedItem(int itemId) async {}
}

/// Stub for the free product's main refusal: the user already has `cap` trackers
/// running, so the create is refused with HTTP 409 + a structured detail.
class _AtCapRepository implements TrackedItemsRepository {
  @override
  Future<List<TrackedItem>> getTrackedItems({
    bool includeInactive = false,
  }) async => const [];

  @override
  Future<void> createFromUrl(String url, {double? targetPrice}) async {
    throw FairUseCapException(activeTrackers: 100, cap: 100);
  }

  @override
  Future<void> refreshPrice(int itemId) async {}

  @override
  Future<void> deleteTrackedItem(int itemId) async {}
}

/// Stub for the creation-window refusal (HTTP 429), carrying the original
/// DioException as `cause` exactly as the real repository does.
class _RateLimitedRepository implements TrackedItemsRepository {
  @override
  Future<List<TrackedItem>> getTrackedItems({
    bool includeInactive = false,
  }) async => const [];

  @override
  Future<void> createFromUrl(String url, {double? targetPrice}) async {
    throw RateLimitedException(
      retryAfterSeconds: 2.76,
      cause: DioException(
        requestOptions: RequestOptions(path: '/tracked-items/from-url'),
        type: DioExceptionType.badResponse,
      ),
    );
  }

  @override
  Future<void> refreshPrice(int itemId) async {}

  @override
  Future<void> deleteTrackedItem(int itemId) async {}
}

/// A cap refusal whose numbers were malformed, so the client knows neither.
class _AtUnknownCapRepository implements TrackedItemsRepository {
  @override
  Future<List<TrackedItem>> getTrackedItems({
    bool includeInactive = false,
  }) async => const [];

  @override
  Future<void> createFromUrl(String url, {double? targetPrice}) async {
    throw const FairUseCapException(activeTrackers: null, cap: null);
  }

  @override
  Future<void> refreshPrice(int itemId) async {}

  @override
  Future<void> deleteTrackedItem(int itemId) async {}
}

/// A 429 with no usable countdown (`Retry-After` sent as an HTTP date).
class _RateLimitedNoCountRepository implements TrackedItemsRepository {
  @override
  Future<List<TrackedItem>> getTrackedItems({
    bool includeInactive = false,
  }) async => const [];

  @override
  Future<void> createFromUrl(String url, {double? targetPrice}) async {
    throw RateLimitedException(
      retryAfterSeconds: 0,
      cause: DioException(
        requestOptions: RequestOptions(path: '/tracked-items/from-url'),
        type: DioExceptionType.badResponse,
      ),
    );
  }

  @override
  Future<void> refreshPrice(int itemId) async {}

  @override
  Future<void> deleteTrackedItem(int itemId) async {}
}

/// Repository stub whose `createFromUrl` always succeeds.
class _SuccessRepository implements TrackedItemsRepository {
  @override
  Future<List<TrackedItem>> getTrackedItems({
    bool includeInactive = false,
  }) async => const [];

  @override
  Future<void> createFromUrl(String url, {double? targetPrice}) async {}

  @override
  Future<void> refreshPrice(int itemId) async {}

  @override
  Future<void> deleteTrackedItem(int itemId) async {}
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
  testWidgets('402 shows the friendly limit dialog with an upgrade button', (
    tester,
  ) async {
    await tester.pumpWidget(_wrap(Scaffold(body: const CreateTrackerSheet())));

    // Fill the URL field so the tap proceeds to the network call.
    await tester.enterText(
      find.byType(TextField).first,
      'https://example.com/x',
    );
    await tester.tap(find.text('Start Tracking'));
    await tester.pumpAndSettle();

    if (!AppConfig.paymentsEnabled) {
      // A free build compiles the upgrade route out: the same 402 must fall
      // back to the generic error snackbar instead of offering a screen the
      // build does not contain.
      expect(find.byType(AlertDialog), findsNothing);
      expect(find.text('Upgrade plan'), findsNothing);
      expect(find.byType(SnackBar), findsOneWidget);
      return;
    }

    // Friendly dialog appears instead of a raw error SnackBar.
    expect(find.text("You've reached your limit"), findsOneWidget);
    expect(find.text('Upgrade plan'), findsOneWidget);
    expect(find.byType(SnackBar), findsNothing);
  }, skip: false);

  testWidgets(
    'upgrade button navigates to the subscription screen',
    (tester) async {
      await tester.pumpWidget(
        _wrap(Scaffold(body: const CreateTrackerSheet())),
      );

      await tester.enterText(
        find.byType(TextField).first,
        'https://example.com/x',
      );
      await tester.tap(find.text('Start Tracking'));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Upgrade plan'));
      await tester.pumpAndSettle();

      // The packages screen is on top: its title is visible.
      expect(find.text('Credit Packages'), findsOneWidget);
    },
    // Only meaningful in a build compiled with the payment surface; the
    // ENABLE_PAYMENTS=false run asserts the opposite in the test above, so the
    // upgrade route being compiled out of a free build skips this case.
    skip: !AppConfig.paymentsEnabled,
  );

  testWidgets('"Not now" dismisses the dialog without navigating', (
    tester,
  ) async {
    await tester.pumpWidget(_wrap(Scaffold(body: const CreateTrackerSheet())));

    await tester.enterText(
      find.byType(TextField).first,
      'https://example.com/x',
    );
    await tester.tap(find.text('Start Tracking'));
    await tester.pumpAndSettle();

    if (!AppConfig.paymentsEnabled) {
      // No dialog to dismiss in a free build - assert the state directly rather
      // than tapping a button that was never rendered.
      expect(find.byType(AlertDialog), findsNothing);
      expect(find.byType(SubscriptionScreen), findsNothing);
      return;
    }

    await tester.tap(find.text('Not now'));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsNothing);
    expect(find.byType(SubscriptionScreen), findsNothing);
  });

  Future<void> submit(WidgetTester tester, TrackedItemsRepository repo) async {
    await tester.pumpWidget(
      _wrap(Scaffold(body: const CreateTrackerSheet()), repository: repo),
    );
    await tester.enterText(
      find.byType(TextField).first,
      'https://example.com/x',
    );
    await tester.tap(find.text('Start Tracking'));
    await tester.pumpAndSettle();
  }

  testWidgets('the fair-use cap explains the ceiling and the way out', (
    tester,
  ) async {
    await submit(tester, _AtCapRepository());

    expect(find.byType(AlertDialog), findsOneWidget);
    expect(find.text("You've reached your limit"), findsOneWidget);
    expect(
      find.text(
        'You already have 100 trackers running, which is the maximum. '
        'Delete one to make room, or tap Not now.',
      ),
      findsOneWidget,
    );
    expect(find.text('Trackers'), findsOneWidget);
    expect(find.text('Not now'), findsOneWidget);
    // Never the internals, and never an upgrade the free product lacks.
    expect(find.textContaining('FairUseCapException'), findsNothing);
    expect(find.text('Upgrade plan'), findsNothing);
    expect(find.byType(SubscriptionScreen), findsNothing);
  });

  testWidgets('"Not now" on the cap dialog keeps the sheet open', (
    tester,
  ) async {
    await submit(tester, _AtCapRepository());
    await tester.tap(find.text('Not now'));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsNothing);
    expect(find.byType(CreateTrackerSheet), findsOneWidget);
  });

  testWidgets('a cap the server did not number is not invented', (
    tester,
  ) async {
    await submit(tester, _AtUnknownCapRepository());

    expect(find.text("You've reached your limit"), findsOneWidget);
    expect(find.textContaining('trackers running'), findsNothing);
    expect(find.textContaining('0'), findsNothing);
  });

  testWidgets('the creation window shows the countdown, rounded up', (
    tester,
  ) async {
    // 2.76 s must read as 3: rounding down would invite a refused retry.
    await submit(tester, _RateLimitedRepository());

    expect(find.text('One tracker at a time'), findsOneWidget);
    expect(
      find.text(
        'You just added a tracker. Wait 3 seconds before adding the next one.',
      ),
      findsOneWidget,
    );
    expect(find.textContaining('RateLimitedException'), findsNothing);
    expect(find.byType(SnackBar), findsNothing);
  });

  testWidgets('a wait with no usable countdown says so without a number', (
    tester,
  ) async {
    await submit(tester, _RateLimitedNoCountRepository());

    expect(
      find.text(
        'One tracker at a time. Tap Start Tracking again when you are ready.',
      ),
      findsOneWidget,
    );
    await tester.tap(find.text('Close'));
    await tester.pumpAndSettle();
    expect(find.byType(AlertDialog), findsNothing);
  });

  testWidgets('a non-402 failure keeps the generic SnackBar (no dialog)', (
    tester,
  ) async {
    await tester.pumpWidget(
      _wrap(
        Scaffold(body: const CreateTrackerSheet()),
        repository: _FailingRepository(),
      ),
    );

    await tester.enterText(
      find.byType(TextField).first,
      'https://example.com/x',
    );
    await tester.tap(find.text('Start Tracking'));
    await tester.pumpAndSettle();

    // The existing error path is preserved: SnackBar with the error message,
    // and no credit-limit dialog.
    expect(find.text('Error: Exception: Backend exploded'), findsOneWidget);
    expect(find.byType(AlertDialog), findsNothing);
  });

  testWidgets('successful creation invalidates the credit balance provider', (
    tester,
  ) async {
    // A counting balance provider: the sheet must invalidate it after a
    // successful creation so the Profile tab shows the new balance.
    var fetches = 0;
    final container = ProviderContainer(
      overrides: [
        creditBalanceProvider.overrideWith((_) async {
          fetches++;
          return const CreditBalance(balance: 2, tier: 'free');
        }),
        trackedItemsRepositoryProvider.overrideWithValue(_SuccessRepository()),
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

    await tester.enterText(
      find.byType(TextField).first,
      'https://example.com/x',
    );
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
