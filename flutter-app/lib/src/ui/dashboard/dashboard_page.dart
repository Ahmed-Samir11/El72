import 'package:flutter/material.dart';

import '../../../l10n/app_localizations.dart';
import '../../core/format/error_message.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/models/tracked_item_model.dart';
import '../../data/providers.dart';
import '../../data/config.dart';
import '../../routing/app_router.dart';
import '../create_tracker_sheet.dart';
import '../price_history/price_history_page.dart';
import '../subscription_screen.dart';
import '../widgets/deal_card.dart';
import '../widgets/market_pulse_header.dart';
import '../widgets/tracker_card.dart';
import '../chatbot/chat_page.dart';

class DashboardPage extends StatefulWidget {
  const DashboardPage({super.key});

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> {
  int index = 0;

  @override
  Widget build(BuildContext context) {
    final pages = <Widget>[
      _TrackersTab(),
      _DealsTab(),
      _ChatTab(),
      _ProfileTab(),
    ];
    return Scaffold(
      body: pages[index],
      bottomNavigationBar: NavigationBar(
        selectedIndex: index,
        destinations: [
          NavigationDestination(
            icon: Icon(Icons.track_changes),
            label: AppLocalizations.of(context).navTrackers,
          ),
          NavigationDestination(
            icon: Icon(Icons.local_offer),
            label: AppLocalizations.of(context).navDeals,
          ),
          NavigationDestination(
            icon: Icon(Icons.chat),
            label: AppLocalizations.of(context).navChat,
          ),
          NavigationDestination(
            icon: Icon(Icons.person),
            label: AppLocalizations.of(context).navProfile,
          ),
        ],
        onDestinationSelected: (i) => setState(() => index = i),
      ),
      floatingActionButton: (index == 0 || index == 1)
          ? FloatingActionButton(
              onPressed: () {
                showModalBottomSheet(
                  context: context,
                  isScrollControlled: true,
                  builder: (context) => const CreateTrackerSheet(),
                );
              },
              child: const Icon(Icons.add),
            )
          : null,
    );
  }
}

class _TrackersTab extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final itemsAsync = ref.watch(trackedItemsProvider);
    return itemsAsync.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                AppLocalizations.of(
                  context,
                ).failedToLoadTrackers(errorMessage(e)),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 12),
              // The provider caches the failure, so offer an explicit retry.
              FilledButton.icon(
                onPressed: () => ref.invalidate(trackedItemsProvider),
                icon: const Icon(Icons.refresh),
                label: Text(AppLocalizations.of(context).retry),
              ),
            ],
          ),
        ),
      ),
      data: (items) {
        return RefreshIndicator(
          onRefresh: () async {
            ref.invalidate(trackedItemsProvider);
            await ref.read(trackedItemsProvider.future);
          },
          child: items.isEmpty
              ? ListView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  children: [
                    const SizedBox(height: 200),
                    // No Center here: a Center inside a ListView gets
                    // unbounded height and trips a layout assert.
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 32),
                      child: Text(
                        AppLocalizations.of(context).noTrackersEmpty,
                        textAlign: TextAlign.center,
                      ),
                    ),
                  ],
                )
              : ListView.builder(
                  physics: const AlwaysScrollableScrollPhysics(),
                  itemCount: items.length,
                  itemBuilder: (context, i) {
                    final item = items[i];
                    final lowest = item.lowestPrice;
                    // Swipe toward the start edge (left in LTR, right in RTL)
                    // to delete, after a confirmation dialog.
                    return Dismissible(
                      key: ValueKey('tracker-${item.id}'),
                      direction: DismissDirection.endToStart,
                      background: Container(
                        alignment: AlignmentDirectional.centerEnd,
                        padding: const EdgeInsets.symmetric(horizontal: 24),
                        color: Theme.of(context).colorScheme.error,
                        child: Icon(
                          Icons.delete_outline,
                          color: Theme.of(context).colorScheme.onError,
                        ),
                      ),
                      confirmDismiss: (_) =>
                          _confirmAndDeleteTracker(context, ref, item),
                      onDismissed: (_) => ref.invalidate(trackedItemsProvider),
                      child: TrackerCard(
                        imageUrl: lowest?.imageUrl ?? '',
                        title: item.displayName,
                        currentPrice: lowest?.priceLocal ?? 0.0,
                        targetPrice: item.targetPrice ?? 0.0,
                        hasPrice: lowest != null && lowest.priceLocal > 0,
                        isActive: item.isActive,
                        fetchStatus: item.fetchStatus,
                        productUrl: lowest?.url ?? '',
                        sku: item.canonicalProductId,
                        onTap: () {
                          Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (_) => PriceHistoryPage(
                                sku: item.canonicalProductId,
                                title: item.displayName,
                              ),
                            ),
                          );
                        },
                        // Retryable fetch failure: re-trigger the backend fetch
                        // (the server resets the status to "fetching"), then
                        // reload so the card shows the spinner again.
                        onRetry: () async {
                          try {
                            await ref
                                .read(trackedItemsRepositoryProvider)
                                .refreshPrice(item.id);
                          } catch (_) {
                            // The refresh request itself failed (DioException
                            // on 429/offline/5xx, or anything else unexpected):
                            // tell the user instead of letting the error escape
                            // the tap handler — the card stays in its failure
                            // state so they can retry later.
                            if (context.mounted) {
                              ScaffoldMessenger.of(context)
                                ..hideCurrentSnackBar()
                                ..showSnackBar(
                                  SnackBar(
                                    content: Text(
                                      AppLocalizations.of(
                                        context,
                                      ).priceRefreshFailed,
                                    ),
                                  ),
                                );
                            }
                            return;
                          }
                          ref.invalidate(trackedItemsProvider);
                        },
                      ),
                    );
                  },
                ),
        );
      },
    );
  }
}

/// Ask before deleting [item]; delete it on confirmation.
///
/// Returns true only when the backend deleted the tracker, so the swiped
/// card is removed; on cancel or failure the card slides back.
Future<bool> _confirmAndDeleteTracker(
  BuildContext context,
  WidgetRef ref,
  TrackedItem item,
) async {
  final l10n = AppLocalizations.of(context);
  final confirmed = await showDialog<bool>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: Text(l10n.deleteTrackerTitle),
      content: Text(l10n.deleteTrackerBody(item.displayName)),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(dialogContext, false),
          child: Text(l10n.cancel),
        ),
        FilledButton(
          style: FilledButton.styleFrom(
            backgroundColor: Theme.of(dialogContext).colorScheme.error,
            foregroundColor: Theme.of(dialogContext).colorScheme.onError,
          ),
          onPressed: () => Navigator.pop(dialogContext, true),
          child: Text(l10n.deleteTrackerConfirm),
        ),
      ],
    ),
  );
  if (confirmed != true) return false;

  try {
    await ref.read(trackedItemsRepositoryProvider).deleteTrackedItem(item.id);
  } catch (_) {
    if (context.mounted) {
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(l10n.trackerDeleteFailed)));
    }
    return false;
  }
  if (context.mounted) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(l10n.trackerDeleted)));
  }
  return true;
}

class _DealsTab extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final dealsAsync = ref.watch(liveDealsProvider);
    final statsAsync = ref.watch(platformStatsProvider);

    return CustomScrollView(
      slivers: [
        // SliverAppBar
        SliverAppBar(
          floating: true,
          title: Text(AppLocalizations.of(context).appTitle),
          actions: [
            IconButton(
              icon: const Icon(Icons.notifications),
              onPressed: () {
                // TODO: Navigate to notifications
              },
            ),
            IconButton(
              icon: const Icon(Icons.settings),
              onPressed: () {
                // TODO: Navigate to settings
              },
            ),
          ],
        ),

        // Market Pulse Header (real stats, with demo fallback)
        SliverToBoxAdapter(
          child: statsAsync.when(
            loading: () => const SizedBox(height: 120),
            error: (e, _) => const SizedBox.shrink(),
            data: (stats) => MarketPulseHeader(
              activeAlerts: stats.totalTrackers,
              dealsToday: stats.dealsToday,
              savings: stats.totalSavings,
            ),
          ),
        ),

        // Section Title
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
            child: Text(
              AppLocalizations.of(context).liveMarketFeed,
              style: Theme.of(
                context,
              ).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold),
            ),
          ),
        ),

        // Deals List (real data, with demo fallback)
        dealsAsync.when(
          loading: () => SliverToBoxAdapter(
            child: const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: CircularProgressIndicator()),
            ),
          ),
          error: (e, _) => SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Text(
                AppLocalizations.of(context).failedToLoadDeals(errorMessage(e)),
              ),
            ),
          ),
          data: (deals) {
            if (deals.isEmpty) {
              return SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Text(AppLocalizations.of(context).noLiveDeals),
                ),
              );
            }
            return SliverList(
              delegate: SliverChildBuilderDelegate(
                (context, index) => DealCard(deal: deals[index]),
                childCount: deals.length,
              ),
            );
          },
        ),
      ],
    );
  }
}

class _ChatTab extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return const ChatPage();
  }
}

class _ProfileTab extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final isDemo = AppConfig.demoMode;
    final creditAsync = ref.watch(creditBalanceProvider);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          child: ListTile(
            leading: const CircleAvatar(child: Icon(Icons.person)),
            title: Text(AppLocalizations.of(context).myAccount),
            subtitle: Text(
              isDemo
                  ? AppLocalizations.of(context).demoAccount
                  : AppLocalizations.of(context).fullAccount,
            ),
          ),
        ),
        const SizedBox(height: 12),
        Card(
          child: ListTile(
            leading: const Icon(Icons.workspace_premium_outlined),
            title: Text(AppLocalizations.of(context).currentPlan),
            // Live credit balance; falls back to the static plan name while
            // loading or on error so the tile never shows a spinner.
            subtitle: creditAsync.maybeWhen(
              data: (credits) => Text(
                AppLocalizations.of(context).creditsRemaining(credits.balance),
              ),
              orElse: () => Text(AppLocalizations.of(context).freePlan),
            ),
            trailing: TextButton(
              onPressed: () => Navigator.push(
                context,
                MaterialPageRoute(builder: (_) => const SubscriptionScreen()),
              ),
              child: Text(AppLocalizations.of(context).manage),
            ),
          ),
        ),
        const SizedBox(height: 12),
        Card(
          child: SwitchListTile.adaptive(
            secondary: const Icon(Icons.science_outlined),
            title: Text(AppLocalizations.of(context).demoMode),
            subtitle: Text(
              isDemo
                  ? AppLocalizations.of(context).usingSampleData
                  : AppLocalizations.of(context).usingLiveData,
            ),
            value: isDemo,
            onChanged: (enabled) async {
              await AppConfig.setDemoMode(enabled);
              await ref.read(authRepositoryProvider).logout();
              ref.invalidate(trackedItemsProvider);
              ref.invalidate(liveDealsProvider);
              ref.invalidate(platformStatsProvider);
              ref.invalidate(chatConversationProvider);
              if (context.mounted) {
                Navigator.of(
                  context,
                ).pushNamedAndRemoveUntil(AppRoutes.splash, (_) => false);
              }
            },
          ),
        ),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          onPressed: () async {
            await ref.read(authRepositoryProvider).logout();
            ref.invalidate(trackedItemsProvider);
            ref.invalidate(liveDealsProvider);
            ref.invalidate(platformStatsProvider);
            // Same contract as the demo-mode toggle and the login/register
            // pages: `chatConversationProvider`'s doc says to invalidate it on
            // logout so the next account starts with an empty chat. Without
            // this, the previous user's messages and search results survive
            // into the signed-out welcome screen.
            ref.invalidate(chatConversationProvider);
            if (context.mounted) {
              Navigator.of(
                context,
              ).pushNamedAndRemoveUntil(AppRoutes.welcome, (_) => false);
            }
          },
          icon: const Icon(Icons.logout),
          label: Text(AppLocalizations.of(context).logOut),
        ),
      ],
    );
  }
}
