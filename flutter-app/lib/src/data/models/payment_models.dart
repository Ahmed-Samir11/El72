// Payment data models for the Paymob wallet flow (Feature 2).
//
// Pricing is SERVER-DETERMINED: the app only ever sends a package id and a
// wallet choice; the backend looks up the price (plan 2.4). The constants
// below mirror the server allowlist for display purposes only.

/// One-time credit packages (server-priced, not subscriptions).
class CreditPackage {
  const CreditPackage({
    required this.id,
    required this.credits,
    required this.priceEgp,
  });

  /// Package id sent to the backend (`package` field).
  final String id;

  /// Credits granted on successful payment.
  final int credits;

  /// Display price in EGP (the authoritative price is the server's).
  final int priceEgp;

  static const CreditPackage standard = CreditPackage(
    id: 'standard',
    credits: 10,
    priceEgp: 30,
  );

  static const CreditPackage premium = CreditPackage(
    id: 'premium',
    credits: 30,
    priceEgp: 90,
  );

  /// All purchasable packages, cheapest first.
  static const List<CreditPackage> all = [standard, premium];

  /// The free allowance (not purchasable).
  static const int freeCredits = 3;
}

/// Egyptian wallet types supported by the backend allowlist (plan 2.7).
/// Values are matched case-insensitively server-side; [apiValue] is the
/// canonical token the API accepts.
enum WalletType {
  vodafoneCash('VODAFONE_CASH'),
  orangeMoney('ORANGE_MONEY'),
  etisalatCash('ETISALAT_CASH'),
  fawry('FAWRY');

  const WalletType(this.apiValue);

  /// Canonical token sent in the `wallet_type` field.
  final String apiValue;
}

/// Payment status values as reported by the backend.
enum PaymentStatus {
  pending,
  pendingOtp,
  processing,
  succeeded,
  failed,
  canceled;

  /// Parses a backend status string; unknown values map to [pending] so a
  /// new server status can never crash the app.
  static PaymentStatus parse(String value) {
    switch (value) {
      case 'pending_otp':
        return pendingOtp;
      case 'processing':
        return processing;
      case 'succeeded':
        return succeeded;
      case 'failed':
        return failed;
      case 'canceled':
        return canceled;
      case 'pending':
      case '':
      default:
        return pending;
    }
  }

  /// True once the payment reached a terminal state.
  bool get isTerminal =>
      this == succeeded || this == failed || this == canceled;
}

/// Egyptian wallet number: 01[0125] + 8 digits (mirrors the server regex).
final RegExp walletNumberRegExp = RegExp(r'^01[0125]\d{8}$');

/// OTP format: 4-8 digits (mirrors the server validation).
final RegExp otpRegExp = RegExp(r'^\d{4,8}$');

/// Result of `POST /payment/confirm` (wallet).
class WalletPaymentResult {
  const WalletPaymentResult({required this.paymentId, required this.status});

  factory WalletPaymentResult.fromJson(Map<String, dynamic> json) {
    return WalletPaymentResult(
      paymentId: json['payment_id']?.toString() ?? '',
      status: json['status']?.toString() ?? 'pending_otp',
    );
  }

  final String paymentId;
  final String status;
}

/// Result of `POST /payment/confirm-otp`.
class OtpResult {
  const OtpResult({required this.status, this.attemptsRemaining});

  factory OtpResult.fromJson(Map<String, dynamic> json) {
    final remaining = json['attempts_remaining'];
    return OtpResult(
      // A 200 response missing the status field is a malformed payload:
      // default to the NON-terminal 'processing' so the UI keeps polling
      // for the authoritative outcome instead of surfacing a premature
      // 'failed' (which could nudge the user into a duplicate payment).
      status: json['status']?.toString() ?? 'processing',
      attemptsRemaining: remaining is int ? remaining : null,
    );
  }

  final String status;

  /// Remaining OTP attempts, present only when [status] is `failed`.
  final int? attemptsRemaining;
}

/// Result of `GET /payment/status/{payment_id}`.
class PaymentStatusInfo {
  const PaymentStatusInfo({
    required this.paymentId,
    required this.package,
    required this.amountEgp,
    required this.status,
    required this.createdAt,
  });

  factory PaymentStatusInfo.fromJson(Map<String, dynamic> json) {
    final amount = json['amount_egp'];
    return PaymentStatusInfo(
      paymentId: json['payment_id']?.toString() ?? '',
      package: json['package']?.toString() ?? '',
      amountEgp: amount is num ? amount.toDouble() : 0,
      status: json['status']?.toString() ?? 'pending',
      createdAt: json['created_at']?.toString() ?? '',
    );
  }

  final String paymentId;
  final String package;
  final double amountEgp;
  final String status;
  final String createdAt;
}
