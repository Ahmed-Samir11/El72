/// Platform-wide stats as returned by `GET /stats` (Engineer B's endpoint).
///
/// Expected shape:
/// ```json
/// { "total_trackers": 128, "deals_today": 47, "total_savings": 2847.5 }
/// ```
class PlatformStats {
  final int totalTrackers;
  final int dealsToday;
  final double totalSavings;

  const PlatformStats({
    required this.totalTrackers,
    required this.dealsToday,
    required this.totalSavings,
  });

  factory PlatformStats.fromJson(Map<String, dynamic> json) {
    return PlatformStats(
      totalTrackers: (json['total_trackers'] as num?)?.toInt() ??
          (json['totalTrackers'] as num?)?.toInt() ??
          0,
      dealsToday: (json['deals_today'] as num?)?.toInt() ??
          (json['dealsToday'] as num?)?.toInt() ??
          0,
      totalSavings: (json['total_savings'] as num?)?.toDouble() ??
          (json['totalSavings'] as num?)?.toDouble() ??
          0.0,
    );
  }
}
