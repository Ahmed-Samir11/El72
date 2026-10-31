/// The authenticated user's fair-use usage of the tracker feature.
///
/// Mirrors the `GET /usage/limits` payload: `active_trackers` (int), `cap`
/// (int or null), `created_last` (ISO datetime or null), `retry_after_seconds`
/// (float) and `enforcement` (one of `fair_use`, `on`, `off`).
///
/// This is the account state the free product shows in place of a credit
/// balance: what the user is tracking, the ceiling they are held to, and how
/// long before the next tracker is allowed. `cap` is null when the server
/// runs with `CREDITS_ENFORCEMENT=off` (dev/test: unlimited), and `created_last`
/// is null for a user who has never created a tracker. Both must render as
/// data, never as a missing value.
class UsageLimits {
  const UsageLimits({
    required this.activeTrackers,
    this.cap,
    this.createdLast,
    this.retryAfterSeconds = 0,
    this.enforcement = 'fair_use',
  });

  /// Trackers the user currently has running (paused trackers do not count).
  final int activeTrackers;

  /// The per-user ceiling on active trackers, or `null` when unlimited.
  final int? cap;

  /// When the most recent tracker in that set was created.
  final DateTime? createdLast;

  /// Seconds still to wait before another tracker may be created. The server
  /// already rounds this upward, so waiting exactly this long gets through.
  final double retryAfterSeconds;

  /// Which enforcement mode the server answered with: `fair_use` (the shipped
  /// free model), `on` (legacy credit ledger) or `off` (unlimited).
  final String enforcement;

  /// Parse a `GET /usage/limits` JSON body. Every number is read with an
  /// `is num` check rather than a cast: a malformed value (a string where a
  /// number was expected) must degrade to the neutral default, not throw out
  /// of the Profile tab.
  factory UsageLimits.fromJson(Map<String, dynamic> json) => UsageLimits(
    activeTrackers: _asInt(json['active_trackers']) ?? 0,
    cap: _asInt(json['cap']),
    createdLast: json['created_last'] is String
        ? DateTime.tryParse(json['created_last'] as String)
        : null,
    retryAfterSeconds: _asDouble(json['retry_after_seconds']) ?? 0,
    enforcement: json['enforcement'] is String
        ? json['enforcement'] as String
        : 'fair_use',
  );

  /// True when the ceiling applies, i.e. the server told us a cap exists.
  bool get isCapped => cap != null;
}

/// JSON number -> int, or null when the value is missing or not a number.
int? _asInt(Object? value) => value is num ? value.toInt() : null;

double? _asDouble(Object? value) => value is num ? value.toDouble() : null;
