import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/intl.dart';

import 'package:elhaq_tracker/l10n/app_localizations.dart';
import 'package:elhaq_tracker/src/core/styles/app_theme.dart';
import 'package:elhaq_tracker/src/data/models/payment_models.dart';
import 'package:elhaq_tracker/src/data/repositories/payment_repository.dart';
import 'package:elhaq_tracker/src/ui/payment/payment_flow_screen.dart';

/// Scripted repository: returns queued results; records calls.
class _FakePaymentRepository implements PaymentRepository {
  final List<WalletPaymentResult> confirmResults = [];
  final List<CashPaymentResult> cashConfirmResults = [];
  final List<OtpResult> otpResults = [];
  final List<String> otpSubmissions = [];
  final List<String> statusResults = [];

  int confirmCalls = 0;
  int cashConfirmCalls = 0;
  int otpCalls = 0;
  int statusCalls = 0;
  bool statusThrows = false;

  @override
  Future<Map<String, String>> startPayment() async => {
    'staging_token': 'stg_test',
    'expires_in': '900',
  };

  @override
  Future<WalletPaymentResult> confirmWalletPayment({
    required String stagingToken,
    required WalletType walletType,
    required String walletNumber,
    required String packageId,
  }) {
    confirmCalls += 1;
    final r = confirmResults.isEmpty
        ? const WalletPaymentResult(paymentId: 'pay_1', status: 'pending_otp')
        : confirmResults.removeAt(0);
    return Future.value(r);
  }

  @override
  Future<CashPaymentResult> confirmCashPayment({
    required String stagingToken,
    required CashType cashType,
    required String packageId,
  }) {
    cashConfirmCalls += 1;
    final r = cashConfirmResults.isEmpty
        ? const CashPaymentResult(
            paymentId: 'cpay_1',
            paymentCode: 'CODE1234',
            expiresAt: '2025-01-02T12:00:00Z',
            status: 'pending',
          )
        : cashConfirmResults.removeAt(0);
    return Future.value(r);
  }

  @override
  Future<OtpResult> confirmWalletOtp({
    required String paymentId,
    required String otp,
  }) {
    otpCalls += 1;
    otpSubmissions.add(otp);
    final r = otpResults.isEmpty
        ? const OtpResult(status: 'succeeded')
        : otpResults.removeAt(0);
    return Future.value(r);
  }

  @override
  Future<PaymentStatusInfo> getPaymentStatus(String paymentId) {
    statusCalls += 1;
    if (statusThrows) {
      throw DioException(
        requestOptions: RequestOptions(path: '/payment/status/$paymentId'),
      );
    }
    final s = statusResults.isEmpty ? 'succeeded' : statusResults.removeAt(0);
    return Future.value(
      PaymentStatusInfo(
        paymentId: paymentId,
        package: 'standard',
        amountEgp: 30,
        status: s,
        createdAt: 'now',
      ),
    );
  }
}

Widget _wrap(Widget child) {
  return MaterialApp(
    theme: AppTheme.light(),
    localizationsDelegates: const [
      AppLocalizations.delegate,
      GlobalMaterialLocalizations.delegate,
      GlobalWidgetsLocalizations.delegate,
      GlobalCupertinoLocalizations.delegate,
    ],
    supportedLocales: const [Locale('en')],
    home: child,
  );
}

Future<void> _openMethodStep(
  WidgetTester tester,
  _FakePaymentRepository repo,
) async {
  await tester.pumpWidget(_wrap(PaymentFlowScreen(repository: repo)));
  // Package step: tap the Standard card to proceed to the method step.
  await tester.tap(find.text('Standard').first);
  await tester.pumpAndSettle();
}

Future<void> _openWalletStep(
  WidgetTester tester,
  _FakePaymentRepository repo,
) async {
  await _openMethodStep(tester, repo);
  // Method step: choose the wallet to proceed to the wallet step.
  await tester.tap(find.byKey(const ValueKey('method-wallet')));
  await tester.pump();
}

Future<void> _openCashStep(
  WidgetTester tester,
  _FakePaymentRepository repo,
) async {
  await _openMethodStep(tester, repo);
  // Method step: choose cash to proceed to the cash step.
  await tester.tap(find.byKey(const ValueKey('method-cash')));
  await tester.pump();
}

void main() {
  testWidgets('method step is shown after package selection', (tester) async {
    final repo = _FakePaymentRepository();
    await _openMethodStep(tester, repo);
    expect(find.text('Choose how you\'d like to pay'), findsOneWidget);
    expect(find.byKey(const ValueKey('method-wallet')), findsOneWidget);
    expect(find.byKey(const ValueKey('method-cash')), findsOneWidget);
  });

  testWidgets(
    'full wallet flow: package -> method -> wallet -> otp -> success',
    (tester) async {
      final repo = _FakePaymentRepository();
      await _openWalletStep(tester, repo);

      // Select a wallet type.
      await tester.tap(find.byKey(const ValueKey('wallet-type-VODAFONE_CASH')));
      await tester.pump();

      // Enter a valid number and confirm.
      await tester.enterText(
        find.byKey(const ValueKey('wallet-number')),
        '01012345678',
      );
      await tester.pump();
      await tester.tap(find.byKey(const ValueKey('confirm-wallet-payment')));
      await tester.pumpAndSettle();

      // Confirmation dialog (plan 2.3) echoes the number.
      expect(find.textContaining('01012345678'), findsWidgets);
      await tester.tap(find.text('Confirm payment').last);
      await tester.pumpAndSettle();

      expect(repo.confirmCalls, 1);
      // OTP step.
      expect(find.byKey(const ValueKey('otp-input')), findsOneWidget);

      // Enter the OTP and verify.
      await tester.enterText(find.byKey(const ValueKey('otp-input')), '123456');
      await tester.tap(find.byKey(const ValueKey('verify-otp')));
      await tester.pumpAndSettle();

      expect(repo.otpSubmissions, ['123456']);
      expect(find.text('Payment successful!'), findsOneWidget);
    },
  );

  testWidgets('full cash flow: package -> method -> cash -> code display', (
    tester,
  ) async {
    final repo = _FakePaymentRepository();
    await _openCashStep(tester, repo);

    // Select a cash channel.
    await tester.tap(find.byKey(const ValueKey('cash-type-fawry')));
    await tester.pump();

    // Confirm; no OTP step for cash. Bounded pumps: the pending result
    // shows an indeterminate spinner, so pumpAndSettle would never settle.
    await tester.tap(find.byKey(const ValueKey('confirm-cash-payment')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    expect(repo.cashConfirmCalls, 1);
    // The single-use code is displayed with its expiry (plan 3.1/3.3).
    expect(find.byKey(const ValueKey('cash-code')), findsOneWidget);
    expect(find.text('CODE1234'), findsOneWidget);
    // The expiry is formatted for the user, not a raw ISO timestamp.
    final expectedExpiry = DateFormat(
      'yMMMMdEEE',
      'en',
    ).format(DateTime.parse('2025-01-02T12:00:00Z').toLocal());
    expect(find.text('Expires $expectedExpiry'), findsOneWidget);
    expect(find.textContaining('T12:00:00Z'), findsNothing);
    expect(find.byKey(const ValueKey('copy-cash-code')), findsOneWidget);
    // No wallet UI leaked into the cash flow.
    expect(find.byKey(const ValueKey('wallet-number')), findsNothing);
  });

  testWidgets('cash step shows the selected package label and price', (
    tester,
  ) async {
    final repo = _FakePaymentRepository();
    await tester.pumpWidget(
      _wrap(
        PaymentFlowScreen(
          repository: repo,
          initialPackage: CreditPackage.premium,
        ),
      ),
    );
    await tester.tap(find.byKey(const ValueKey('method-cash')));
    await tester.pump();
    // The premium package label and its price — not the hardcoded
    // Standard label.
    expect(find.textContaining('Premium'), findsOneWidget);
    expect(find.textContaining('90'), findsOneWidget);
    expect(find.textContaining('30'), findsNothing);
  });

  testWidgets('terminal cash result hides the code card', (tester) async {
    final repo = _FakePaymentRepository();
    repo.cashConfirmResults.add(
      const CashPaymentResult(
        paymentId: 'cpay_done',
        paymentCode: 'CODEDONE',
        expiresAt: '2025-01-02T12:00:00Z',
        status: 'succeeded',
      ),
    );
    await _openCashStep(tester, repo);
    await tester.tap(find.byKey(const ValueKey('cash-type-fawry')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('confirm-cash-payment')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    // Succeeded: the code card is gone, the success title is shown.
    expect(find.byKey(const ValueKey('cash-code')), findsNothing);
    expect(find.byKey(const ValueKey('copy-cash-code')), findsNothing);
    expect(find.text('Payment successful!'), findsOneWidget);
  });

  testWidgets('retry after a failed cash payment resets the poll counter', (
    tester,
  ) async {
    final repo = _FakePaymentRepository();
    // First cash attempt fails outright (terminal -> retry button).
    repo.cashConfirmResults.add(
      const CashPaymentResult(
        paymentId: 'cpay_fail',
        paymentCode: 'CODEFAIL',
        expiresAt: '2025-01-02T12:00:00Z',
        status: 'failed',
      ),
    );
    // Second attempt is pending; polling must work from a fresh budget.
    repo.cashConfirmResults.add(
      const CashPaymentResult(
        paymentId: 'cpay_ok',
        paymentCode: 'CODEOK',
        expiresAt: '2025-01-02T12:00:00Z',
        status: 'pending',
      ),
    );
    await _openCashStep(tester, repo);
    await tester.tap(find.byKey(const ValueKey('cash-type-fawry')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('confirm-cash-payment')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    // Failed result: retry is offered.
    expect(find.text('Payment failed'), findsOneWidget);
    await tester.tap(find.text('Try again'));
    await tester.pump();

    // Retry returns to the method step; confirm the cash payment again.
    await tester.tap(find.byKey(const ValueKey('method-cash')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('cash-type-fawry')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('confirm-cash-payment')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    // Polling must have been reset to zero: the first 60 s poll fires.
    expect(repo.statusCalls, 0);
    await tester.pump(const Duration(seconds: 60));
    expect(repo.statusCalls, 1);
  });

  testWidgets('copying the cash code puts it on the clipboard', (tester) async {
    final repo = _FakePaymentRepository();
    await _openCashStep(tester, repo);
    await tester.tap(find.byKey(const ValueKey('cash-type-bank')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('confirm-cash-payment')));
    // Bounded pumps: the pending result shows an indeterminate spinner,
    // so pumpAndSettle would never settle.
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    await tester.tap(find.byKey(const ValueKey('copy-cash-code')));
    await tester.pump();
    expect(find.text('Code copied'), findsOneWidget);
  });

  testWidgets('cash confirm without a channel selected shows an error', (
    tester,
  ) async {
    final repo = _FakePaymentRepository();
    await _openCashStep(tester, repo);
    await tester.tap(find.byKey(const ValueKey('confirm-cash-payment')));
    await tester.pumpAndSettle();

    expect(find.text('Choose your cash channel'), findsOneWidget);
    // No backend call was made.
    expect(repo.cashConfirmCalls, 0);
  });

  testWidgets('rejects an invalid wallet number before submitting', (
    tester,
  ) async {
    final repo = _FakePaymentRepository();
    await _openWalletStep(tester, repo);
    await tester.tap(find.byKey(const ValueKey('wallet-type-FAWRY')));
    await tester.pump();
    await tester.enterText(
      find.byKey(const ValueKey('wallet-number')),
      '01312345678',
    );
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('confirm-wallet-payment')));
    await tester.pumpAndSettle();

    expect(
      find.text(
        'Enter a valid Egyptian mobile number (010/011/012/015 + 8 digits)',
      ),
      findsOneWidget,
    );
    // No backend call was made.
    expect(repo.confirmCalls, 0);
  });

  testWidgets('cancelling the confirmation dialog makes no backend call', (
    tester,
  ) async {
    final repo = _FakePaymentRepository();
    await _openWalletStep(tester, repo);
    await tester.tap(find.byKey(const ValueKey('wallet-type-FAWRY')));
    await tester.pump();
    await tester.enterText(
      find.byKey(const ValueKey('wallet-number')),
      '01012345678',
    );
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('confirm-wallet-payment')));
    await tester.pumpAndSettle();

    // Tap the Cancel action of the confirmation dialog.
    await tester.tap(find.text('Cancel').last);
    await tester.pumpAndSettle();

    expect(repo.confirmCalls, 0);
  });

  testWidgets('failed OTP surfaces attempts remaining', (tester) async {
    final repo = _FakePaymentRepository();
    repo.otpResults.add(
      const OtpResult(status: 'failed', attemptsRemaining: 2),
    );
    await _openWalletStep(tester, repo);
    await tester.tap(find.byKey(const ValueKey('wallet-type-FAWRY')));
    await tester.pump();
    await tester.enterText(
      find.byKey(const ValueKey('wallet-number')),
      '01012345678',
    );
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('confirm-wallet-payment')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Confirm payment').last);
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const ValueKey('otp-input')), '000000');
    await tester.tap(find.byKey(const ValueKey('verify-otp')));
    await tester.pumpAndSettle();

    expect(find.text('2 attempts remaining'), findsOneWidget);
  });

  testWidgets('initial package skips the package step', (tester) async {
    final repo = _FakePaymentRepository();
    await tester.pumpWidget(
      _wrap(
        PaymentFlowScreen(
          repository: repo,
          initialPackage: CreditPackage.premium,
        ),
      ),
    );
    // The method step is shown directly (not the package step).
    expect(find.byKey(const ValueKey('method-wallet')), findsOneWidget);
    expect(find.byKey(const ValueKey('method-cash')), findsOneWidget);
  });

  testWidgets('terminal failed result offers retry', (tester) async {
    final repo = _FakePaymentRepository();
    repo.confirmResults.add(
      const WalletPaymentResult(paymentId: 'pay_f', status: 'failed'),
    );
    await _openWalletStep(tester, repo);
    await tester.tap(find.byKey(const ValueKey('wallet-type-FAWRY')));
    await tester.pump();
    await tester.enterText(
      find.byKey(const ValueKey('wallet-number')),
      '01012345678',
    );
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('confirm-wallet-payment')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Confirm payment').last);
    await tester.pumpAndSettle();

    expect(find.text('Payment failed'), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);

    // Retry returns to the method step.
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('method-wallet')), findsOneWidget);
  });

  testWidgets('poll failure is surfaced while status stays pending', (
    tester,
  ) async {
    final repo = _FakePaymentRepository();
    repo.confirmResults.add(
      const WalletPaymentResult(paymentId: 'pay_p', status: 'processing'),
    );
    repo.statusThrows = true;
    await _openWalletStep(tester, repo);
    await tester.tap(find.byKey(const ValueKey('wallet-type-FAWRY')));
    await tester.pump();
    await tester.enterText(
      find.byKey(const ValueKey('wallet-number')),
      '01012345678',
    );
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('confirm-wallet-payment')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Confirm payment').last);
    // Bounded pumps: the processing result shows an indeterminate spinner,
    // so pumpAndSettle would never settle.
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    // Pending view is shown (processing).
    expect(find.text('Waiting for payment confirmation…'), findsOneWidget);

    // Advance the 5 s poll timer; the status call throws -> the failure
    // must be surfaced while the status stays pending.
    await tester.pump(const Duration(seconds: 5));
    await tester.pump();
    expect(
      find.text('Something went wrong. Please try again.'),
      findsOneWidget,
    );
    expect(find.text('Waiting for payment confirmation…'), findsOneWidget);
  });
}
