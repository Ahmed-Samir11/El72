import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/l10n/app_localizations.dart';
import 'package:elhaq_tracker/src/core/styles/app_theme.dart';
import 'package:elhaq_tracker/src/data/models/payment_models.dart';
import 'package:elhaq_tracker/src/data/repositories/payment_repository.dart';
import 'package:elhaq_tracker/src/ui/payment/wallet_payment_screen.dart';

/// Scripted repository: returns queued results; records calls.
class _FakePaymentRepository implements PaymentRepository {
  final List<WalletPaymentResult> confirmResults = [];
  final List<OtpResult> otpResults = [];
  final List<String> otpSubmissions = [];
  final List<String> statusResults = [];

  int confirmCalls = 0;
  int otpCalls = 0;
  int statusCalls = 0;

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

Future<void> _openWalletStep(
  WidgetTester tester,
  _FakePaymentRepository repo,
) async {
  await tester.pumpWidget(_wrap(WalletPaymentScreen(repository: repo)));
  // Package step: tap the Standard card to proceed to the wallet step.
  await tester.tap(find.text('Standard').first);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('full wallet flow: package -> wallet -> otp -> success', (
    tester,
  ) async {
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
        WalletPaymentScreen(
          repository: repo,
          initialPackage: CreditPackage.premium,
        ),
      ),
    );
    // The wallet step is shown directly.
    expect(find.byKey(const ValueKey('wallet-number')), findsOneWidget);
    expect(find.byKey(const ValueKey('wallet-type-FAWRY')), findsOneWidget);
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

    // Retry returns to the wallet step.
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wallet-number')), findsOneWidget);
  });
}
