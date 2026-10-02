/// The authenticated user's credit balance and subscription tier.
///
/// Mirrors the `GET /credits/balance` payload:
/// `{"balance": <int>, "tier": "<str>"}`.
class CreditBalance {
  const CreditBalance({required this.balance, required this.tier});

  /// Remaining tracker credits (each tracker costs one credit).
  final int balance;

  /// Subscription tier: `free`, `standard`, or `premium`.
  final String tier;

  /// Parse a `GET /credits/balance` JSON body.
  factory CreditBalance.fromJson(Map<String, dynamic> json) => CreditBalance(
    balance: (json['balance'] as num?)?.toInt() ?? 0,
    tier: json['tier'] as String? ?? 'free',
  );
}
