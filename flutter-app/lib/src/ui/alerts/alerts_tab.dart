import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../l10n/app_localizations.dart';
import '../../core/format/error_message.dart';
import '../../data/providers.dart';
import '../../data/repositories/alert_events_repository.dart';
import '../widgets/alert_card.dart';

/// The Alerts tab (plans/p2 MS2) — the in-app half of the alert surface.
///
/// What it may claim: the server recorded a price event on a product this
/// user tracks, and tapping opens that product at the store. What it must not
/// claim: any channel. No operating-system push, no WhatsApp, no email is
/// implied here; `alert_events.channel` stays `in_app` until a sender ships
/// (plans/p2 MS3, blocked on the Firebase and WhatsApp decisions), and the
/// privacy policy says the same thing.
///
/// There is no demo fallback: a fabricated event row would assert a price
/// move that never happened, and the opened/unopened ratio Gate 2 measures
/// would be computed over fiction. Offline or empty therefore shows the empty
/// state (`alertsEmpty`) — and a FAILED read shows `alertsLoadFailed`, never
/// the empty state, because "no alerts" is a different claim from "I could not
/// read your alerts".
class AlertsTab extends ConsumerWidget {
  const AlertsTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final feedAsync = ref.watch(alertFeedProvider);

    return RefreshIndicator(
      // Pull the feed again without an app restart: a tap that marked events
      // opened, or a backlog the consumer finally drained, shows up here.
      onRefresh: () async {
        ref.invalidate(alertFeedProvider);
        try {
          await ref.read(alertFeedProvider.future);
        } catch (_) {
          // The provider already holds the failure and the tab renders its
          // error state; rethrowing here would only surface as an unhandled
          // async error behind the indicator.
        }
      },
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverAppBar(
            floating: true,
            title: Text(AppLocalizations.of(context).alertsTabTitle),
            // No settings/notification icons here: a bell with no bell behind
            // it is the exact affordance this plan exists to stop.
            actions: [
              IconButton(
                icon: const Icon(Icons.refresh),
                onPressed: () {
                  ref.invalidate(alertFeedProvider);
                },
              ),
            ],
          ),

          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
              child: Text(
                AppLocalizations.of(context).alertsTabHint,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
            ),
          ),

          // The un-opened badge. Straight from the server's `unopened_total`:
          // the account-wide count, so a clipped window cannot shrink it (the
          // split the router documents and `test_unopened_total_counts_the_
          // account_not_the_window` pins).
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: feedAsync.maybeWhen(
                data: (feed) => feed.unopenedTotal > 0
                    ? _Badge(count: feed.unopenedTotal.toString())
                    : const SizedBox.shrink(),
                orElse: () => const SizedBox.shrink(),
              ),
            ),
          ),

          feedAsync.when(
            loading: () => const SliverToBoxAdapter(
              child: Padding(
                padding: EdgeInsets.all(32),
                child: Center(child: CircularProgressIndicator()),
              ),
            ),
            error: (error, _) => SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Text(
                  AppLocalizations.of(
                    context,
                  ).alertsLoadFailed(_loadDetail(error)),
                  textAlign: TextAlign.center,
                ),
              ),
            ),
            data: (feed) {
              if (feed.alerts.isEmpty) {
                return SliverToBoxAdapter(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Text(
                      AppLocalizations.of(context).alertsEmpty,
                      textAlign: TextAlign.center,
                    ),
                  ),
                );
              }
              return SliverList(
                delegate: SliverChildBuilderDelegate((context, index) {
                  final event = feed.alerts[index];
                  return AlertCard(
                    event: event,
                    // Bookkeeping runs before the merchant opens and never
                    // blocks it: a refused mark-open (offline, rate-limited,
                    // an id that is not this user's) leaves the feed as it
                    // was rather than pretending the alert was seen.
                    onOpened: event.id.isEmpty
                        ? null
                        : (eventId) {
                            ref
                                .read(alertEventsRepositoryProvider)
                                .markOpened(eventId)
                                .then((marked) {
                                  if (!marked) return;
                                  // The tab may be gone (back button, tab
                                  // switch rebuilds it) — the feed refresh
                                  // then belongs to the next visit anyway.
                                  if (!context.mounted) return;
                                  ref.invalidate(alertFeedProvider);
                                });
                          },
                  );
                }, childCount: feed.alerts.length),
              );
            },
          ),
        ],
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  final String count;

  const _Badge({required this.count});

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(
          color: colorScheme.primary,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Text(
          AppLocalizations.of(context).alertsUnopenedBadge(count),
          style: TextStyle(
            color: colorScheme.onPrimary,
            fontSize: 12,
            fontWeight: FontWeight.bold,
          ),
        ),
      ),
    );
  }
}

/// The `{error}` slot of `alertsLoadFailed`.
///
/// [AlertFeedUnavailable] carries no prose on purpose (the app must not ship
/// an English sentence out of a server condition), so only its status number
/// is shown; anything else keeps the app's existing `errorMessage` treatment.
String _loadDetail(Object error) {
  if (error is AlertFeedUnavailable) {
    return error.statusCode == null ? '' : 'HTTP ${error.statusCode}';
  }
  return errorMessage(error);
}
