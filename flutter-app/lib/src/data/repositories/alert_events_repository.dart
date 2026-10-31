import 'package:dio/dio.dart';

import '../models/alert_event_model.dart';
import '../services/api_client.dart';

/// Raised when the alert feed could not be read (offline, 401 already routed
/// by [ApiClient]'s interceptor, 404 on a server older than plans/p2, 5xx,
/// rate-limited).
///
/// Deliberately a throw rather than an empty feed: "no alerts yet" and "I
/// could not read your alerts" are different claims, and the Alerts tab
/// renders different copy for each (`alertsEmpty` vs `alertsLoadFailed`).
class AlertFeedUnavailable implements Exception {
  const AlertFeedUnavailable([this.statusCode]);

  /// The HTTP status that answered, when there was one. Display-free by
  /// design: the user-facing message is localized, never a raw server detail.
  final int? statusCode;

  @override
  String toString() =>
      'AlertFeedUnavailable(${statusCode == null ? '' : 'HTTP $statusCode'})';
}

/// The Alerts tab's read: the events in the window plus the account-wide
/// un-opened count.
///
/// [unopenedTotal] is NOT `alerts.where(isUnopened).count`. The server
/// documents the split (`services/api/routers/alerts.py`): the list is a
/// bounded window, the badge answers "how many of my alerts have I not
/// opened yet", which is the opened/unopened ratio Gate 2 measures. Counting
/// the array here would silently shrink the badge whenever the window clips.
class AlertFeed {
  final List<AlertEvent> alerts;
  final int unopenedTotal;

  AlertFeed({required this.alerts, required this.unopenedTotal});

  AlertFeed.empty()
    : alerts = const [],
      unopenedTotal = 0;
}

/// Data source for the user's alert history (`GET /alerts/recent`) and for
/// marking one event opened (`POST /alerts/{event_id}/open`).
///
/// There is no demo fallback here, unlike the deals feed. A demo `alert_events`
/// row would assert "a price event happened for you", which never happened —
/// and the opened/unopened ratio Gate 2 measures would be computed over
/// fiction. In demo mode, and offline, the tab shows the empty state plus its
/// load-failure copy instead; the migration makes the same call server-side
/// (no backfill from `current_prices`).
class AlertEventsRepository {
  /// An [ApiClient] may be injected for testing; the shared singleton is used
  /// when omitted.
  AlertEventsRepository({ApiClient? apiClient})
    : _apiClient = apiClient ?? ApiClient();

  final ApiClient _apiClient;

  /// Fetch the newest events, newest first (the server's order, preserved).
  Future<AlertFeed> getRecentAlerts({int limit = defaultAlertsLimit}) async {
    final safeLimit = limit.clamp(minAlertsLimit, maxAlertsLimit).toInt();

    try {
      final response = await _apiClient.dio.get(
        '/alerts/recent',
        queryParameters: {'limit': safeLimit},
      );
      if (response.statusCode != 200) {
        throw AlertFeedUnavailable(response.statusCode);
      }
      return _parseFeed(response.data);
    } on AlertFeedUnavailable {
      rethrow;
    } on DioException catch (error) {
      throw AlertFeedUnavailable(error.response?.statusCode);
    } catch (_) {
      // A body Dio could not decode, a cancelled request, and anything else
      // are still just "could not read the feed": the tab must not crash, and
      // must not claim the account has no alerts.
      throw AlertFeedUnavailable();
    }
  }

  /// Record that the user opened one of their own events.
  ///
  /// Idempotent server-side (a second tap keeps the FIRST `opened_at`), and
  /// scoped to the caller's rows: another user's id answers 404, reported here
  /// as `false` rather than as an error — the merchant tap must not be blocked
  /// by bookkeeping.
  Future<bool> markOpened(String eventId) async {
    if (!isEventIdShaped(eventId)) return false;

    try {
      final response = await _apiClient.dio.post('/alerts/$eventId/open');
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }
}

/// Mirrors `DEFAULT_ALERTS_LIMIT` in `services/api/routers/alerts.py`; pinned
/// against the server by `test/alert_events_repository_test.dart`.
const int defaultAlertsLimit = 50;

/// Mirrors `MAX_ALERTS_LIMIT` in that router: asking for more answers HTTP 422,
/// so the client clamps instead of round-tripping a rejected query.
const int maxAlertsLimit = 200;
const int minAlertsLimit = 1;

/// Only the id shapes the server can issue — a UUID (PostgreSQL) or digits
/// (the SQLite fixtures). The id reaches the request PATH, so a stray `/` or
/// `?` would address a different endpoint; this rejects those before the call.
final _eventIdPattern = RegExp(r'^[0-9a-fA-F-]{1,64}$');

bool isEventIdShaped(String value) => _eventIdPattern.hasMatch(value);

/// Decode the `{alerts: [...], unopened_total: N}` envelope.
///
/// Every field is read defensively: a scraper-owned row can carry a numeric
/// store id, a null price, or a `created_at` the client cannot place on a
/// timeline, and none of that may take the whole feed down.
AlertFeed _parseFeed(dynamic data) {
  final body = data is Map ? Map<String, dynamic>.from(data) : <String, dynamic>{};

  final rawAlerts = body['alerts'];
  final events = <AlertEvent>[];
  if (rawAlerts is List) {
    for (final entry in rawAlerts) {
      if (entry is! Map) continue;
      final event = AlertEvent.fromJson(Map<String, dynamic>.from(entry));
      // A row whose `created_at` cannot be parsed is not displayable: it
      // would be labelled "Today", which is a lie about when it happened.
      if (!event.hasCreatedAt) continue;
      events.add(event);
    }
  }

  final total = body['unopened_total'];
  final unopened = total is int
      ? (total < 0 ? 0 : total)
      : (total is String ? (int.tryParse(total) ?? 0) : 0);

  return AlertFeed(alerts: events, unopenedTotal: unopened);
}
