import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';

import '../../data/models/payment_models.dart';
import '../../data/repositories/payment_repository.dart';
import '../../../l10n/app_localizations.dart';

/// Step-based Paymob wallet payment flow (Feature 2).
///
/// Package selection → wallet type + number (with confirmation, plan 2.3) →
/// OTP entry → result with status polling. The price is server-determined
/// (plan 2.4); the app only sends the package id and the wallet choice.
class WalletPaymentScreen extends StatefulWidget {
  const WalletPaymentScreen({super.key, this.repository, this.initialPackage});

  /// Injectable for tests; defaults to a shared [PaymentRepository].
  final PaymentRepository? repository;

  /// When set, the flow starts at the wallet step with this package.
  final CreditPackage? initialPackage;

  @override
  State<WalletPaymentScreen> createState() => _WalletPaymentScreenState();
}

enum _PaymentStep { package, wallet, otp, result }

class _WalletPaymentScreenState extends State<WalletPaymentScreen> {
  late _PaymentStep _step;
  late CreditPackage _package;

  WalletType? _walletType;
  late final TextEditingController _walletController = TextEditingController();
  late final TextEditingController _otpController = TextEditingController();

  String? _paymentId;

  bool _submitting = false;
  String? _fieldError;
  String? _otpError;

  PaymentStatus? _resultStatus;
  int _pollsDone = 0;
  bool _pollFailed = false;
  Timer? _pollTimer;
  static const int _maxPolls = 6;
  static const Duration _pollInterval = Duration(seconds: 5);

  // Cached in state so the repository is not re-created on every build
  // (review finding #6).
  late final PaymentRepository _repo = widget.repository ?? PaymentRepository();

  @override
  void initState() {
    super.initState();
    _package = widget.initialPackage ?? CreditPackage.standard;
    _step = widget.initialPackage != null
        ? _PaymentStep.wallet
        : _PaymentStep.package;
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _walletController.dispose();
    _otpController.dispose();
    super.dispose();
  }

  AppLocalizations get l10n => AppLocalizations.of(context);

  // ---------------------------------------------------------------------
  // Flow actions
  // ---------------------------------------------------------------------

  void _selectPackage(CreditPackage package) {
    setState(() {
      _package = package;
      _step = _PaymentStep.wallet;
    });
  }

  bool _walletNumberValid() =>
      walletNumberRegExp.hasMatch(_walletController.text.trim());

  Future<void> _submitWallet() async {
    final number = _walletController.text.trim();
    final type = _walletType;
    if (type == null) {
      setState(() => _fieldError = l10n.selectWallet);
      return;
    }
    if (!_walletNumberValid()) {
      setState(() => _fieldError = l10n.invalidWalletNumber);
      return;
    }
    // Plan 2.3: echo the wallet number back for explicit confirmation.
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(l10n.walletConfirmTitle),
        content: Text(l10n.walletConfirmMessage(number)),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: Text(l10n.cancel),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: Text(l10n.confirmPaymentButton),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() {
      _submitting = true;
      _fieldError = null;
    });
    try {
      final start = await _repo.startPayment();
      final result = await _repo.confirmWalletPayment(
        stagingToken: start['staging_token'] ?? '',
        walletType: type,
        walletNumber: number,
        packageId: _package.id,
      );
      if (!mounted) return;
      setState(() {
        _paymentId = result.paymentId;
        _submitting = false;
        if (PaymentStatus.parse(result.status) == PaymentStatus.pendingOtp) {
          _step = _PaymentStep.otp;
          _otpError = null;
        } else {
          _resultStatus = PaymentStatus.parse(result.status);
          _step = _PaymentStep.result;
          _startPollingIfNeeded();
        }
      });
    } on DioException {
      if (!mounted) return;
      setState(() {
        _submitting = false;
        _fieldError = l10n.paymentError;
      });
    }
  }

  Future<void> _submitOtp() async {
    final paymentId = _paymentId;
    if (paymentId == null) return;
    final otp = _otpController.text.trim();
    if (!otpRegExp.hasMatch(otp)) {
      setState(() => _otpError = l10n.otpInvalid);
      return;
    }
    setState(() {
      _submitting = true;
      _otpError = null;
    });
    try {
      final result = await _repo.confirmWalletOtp(
        paymentId: paymentId,
        otp: otp,
      );
      if (!mounted) return;
      final status = PaymentStatus.parse(result.status);
      setState(() {
        _submitting = false;
        if (status == PaymentStatus.failed) {
          // Server budget exhausted → the payment is canceled server-side.
          if (result.attemptsRemaining == 0) {
            _resultStatus = PaymentStatus.canceled;
            _step = _PaymentStep.result;
          } else {
            _otpError = l10n.otpAttemptsLeft(result.attemptsRemaining ?? 0);
            _otpController.clear();
          }
        } else {
          _resultStatus = status;
          _step = _PaymentStep.result;
          _startPollingIfNeeded();
        }
      });
    } on DioException {
      if (!mounted) return;
      setState(() {
        _submitting = false;
        _otpError = l10n.paymentError;
      });
    }
  }

  void _startPollingIfNeeded() {
    _pollTimer?.cancel();
    final status = _resultStatus;
    if (status == null || status.isTerminal || _pollsDone >= _maxPolls) return;
    _pollTimer = Timer(_pollInterval, _pollStatus);
  }

  Future<void> _pollStatus() async {
    _pollTimer = null;
    final paymentId = _paymentId;
    if (!mounted || paymentId == null || _pollsDone >= _maxPolls) return;
    _pollsDone += 1;
    try {
      final info = await _repo.getPaymentStatus(paymentId);
      if (!mounted) return;
      final status = PaymentStatus.parse(info.status);
      setState(() {
        _pollFailed = false;
        _resultStatus = status;
      });
      _startPollingIfNeeded();
    } on DioException {
      // Review finding #3: surface the polling failure instead of silently
      // swallowing it — the state stays pending until proven otherwise and
      // polling keeps retrying while the budget allows.
      if (!mounted) return;
      setState(() => _pollFailed = true);
      _startPollingIfNeeded();
    }
  }

  void _retry() {
    _pollTimer?.cancel();
    _pollTimer = null;
    setState(() {
      _step = _PaymentStep.wallet;
      _paymentId = null;
      _resultStatus = null;
      _otpController.clear();
      _otpError = null;
      _fieldError = null;
      _pollsDone = 0;
      _pollFailed = false;
    });
  }

  // ---------------------------------------------------------------------
  // Build
  // ---------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.creditPackages)),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: switch (_step) {
                _PaymentStep.package => _buildPackages(scheme),
                _PaymentStep.wallet => _buildWalletStep(scheme),
                _PaymentStep.otp => _buildOtpStep(scheme),
                _PaymentStep.result => _buildResult(scheme),
              },
            ),
            if (_step == _PaymentStep.wallet)
              Padding(
                padding: const EdgeInsets.all(16),
                child: FilledButton(
                  key: const ValueKey('confirm-wallet-payment'),
                  onPressed: _submitting ? null : _submitWallet,
                  child: _submitting
                      ? const SizedBox(
                          height: 20,
                          width: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : Text(l10n.confirmPaymentButton),
                ),
              ),
            if (_step == _PaymentStep.otp)
              Padding(
                padding: const EdgeInsets.all(16),
                child: FilledButton(
                  key: const ValueKey('verify-otp'),
                  onPressed: _submitting ? null : _submitOtp,
                  child: Text(l10n.verifyOtpButton),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildPackages(ColorScheme scheme) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                Icon(Icons.check_circle, color: scheme.primary),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        l10n.freePlanShort,
                        style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      Text(l10n.freeCreditsDesc),
                    ],
                  ),
                ),
                Chip(label: Text(l10n.currentPlan)),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),
        for (final package in CreditPackage.all)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Card(
              child: InkWell(
                borderRadius: BorderRadius.circular(12),
                onTap: () => _selectPackage(package),
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              package == CreditPackage.premium
                                  ? l10n.premiumPackage
                                  : l10n.standardPackage,
                              style: const TextStyle(
                                fontSize: 18,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                            Text(
                              package == CreditPackage.premium
                                  ? l10n.premiumPackageDesc
                                  : l10n.standardPackageDesc,
                            ),
                          ],
                        ),
                      ),
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          Text(
                            l10n.creditsLabel(package.credits),
                            style: TextStyle(color: scheme.primary),
                          ),
                          Text(l10n.egpOnce('${package.priceEgp}')),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }

  Widget _buildWalletStep(ColorScheme scheme) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(l10n.selectWallet, style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final type in WalletType.values)
              ChoiceChip(
                key: ValueKey('wallet-type-${type.apiValue}'),
                label: Text(switch (type) {
                  WalletType.vodafoneCash => l10n.walletVodafoneCash,
                  WalletType.orangeMoney => l10n.walletOrangeMoney,
                  WalletType.etisalatCash => l10n.walletEtisalatCash,
                  WalletType.fawry => l10n.walletFawry,
                }),
                selected: _walletType == type,
                onSelected: (_) => setState(() {
                  _walletType = type;
                  _fieldError = null;
                }),
              ),
          ],
        ),
        const SizedBox(height: 16),
        TextField(
          key: const ValueKey('wallet-number'),
          controller: _walletController,
          keyboardType: TextInputType.phone,
          maxLength: 11,
          decoration: InputDecoration(
            labelText: l10n.walletNumberLabel,
            hintText: l10n.walletNumberHint,
            errorText: _fieldError,
          ),
          onChanged: (_) => setState(() => _fieldError = null),
        ),
        const SizedBox(height: 8),
        Text(
          '${l10n.standardPackage}: ${l10n.egpOnce('${_package.priceEgp}')}',
          style: TextStyle(color: scheme.outline),
        ),
      ],
    );
  }

  Widget _buildOtpStep(ColorScheme scheme) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.sms, size: 48, color: scheme.primary),
            const SizedBox(height: 16),
            Text(
              l10n.enterOtpTitle,
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 8),
            Text(l10n.enterOtpDesc),
            const SizedBox(height: 24),
            TextField(
              key: const ValueKey('otp-input'),
              controller: _otpController,
              keyboardType: TextInputType.number,
              textAlign: TextAlign.center,
              maxLength: 8,
              style: const TextStyle(fontSize: 24, letterSpacing: 8),
              decoration: InputDecoration(errorText: _otpError),
              onChanged: (_) => setState(() => _otpError = null),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildResult(ColorScheme scheme) {
    final status = _resultStatus ?? PaymentStatus.pending;
    final (icon, color, title, desc) = switch (status) {
      PaymentStatus.succeeded => (
        Icons.check_circle,
        scheme.primary,
        l10n.paymentSucceededTitle,
        l10n.paymentSucceededDesc,
      ),
      PaymentStatus.failed => (
        Icons.error,
        scheme.error,
        l10n.paymentFailedTitle,
        l10n.paymentFailedDesc,
      ),
      PaymentStatus.canceled => (
        Icons.cancel,
        scheme.error,
        l10n.paymentCanceledTitle,
        l10n.paymentFailedDesc,
      ),
      _ => (
        Icons.hourglass_top,
        scheme.primary,
        l10n.paymentPending,
        l10n.paymentProcessing,
      ),
    };
    final terminal = status.isTerminal;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (!terminal)
              const SizedBox(
                height: 48,
                width: 48,
                child: CircularProgressIndicator(),
              )
            else
              Icon(icon, size: 64, color: color),
            const SizedBox(height: 24),
            Text(title, style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 8),
            Text(
              desc,
              textAlign: TextAlign.center,
              style: TextStyle(color: scheme.outline),
            ),
            if (!terminal && _pollFailed) ...[
              const SizedBox(height: 12),
              Text(
                l10n.paymentError,
                textAlign: TextAlign.center,
                style: TextStyle(color: scheme.error),
              ),
            ],
            if (terminal) ...[
              const SizedBox(height: 24),
              if (status == PaymentStatus.succeeded)
                FilledButton(
                  onPressed: () => Navigator.pop(context),
                  child: Text(l10n.buyNow),
                )
              else
                OutlinedButton(
                  onPressed: _retry,
                  child: Text(l10n.retryPayment),
                ),
            ],
          ],
        ),
      ),
    );
  }
}
