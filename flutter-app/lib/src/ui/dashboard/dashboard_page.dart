import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/providers.dart';
import '../create_tracker_sheet.dart';
import '../price_history/price_history_page.dart';
import '../subscription_screen.dart';
import '../widgets/deal_card.dart';
import '../widgets/market_pulse_header.dart';
import '../widgets/tracker_card.dart';

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
      _ProfileTab(),
    ];
    return Scaffold(
      appBar: AppBar(title: const Text('Elhaq Dashboard')),
      body: pages[index],
      bottomNavigationBar: NavigationBar(
        selectedIndex: index,
        destinations: const [
          NavigationDestination(icon: Icon(Icons.track_changes), label: 'Trackers'),
          NavigationDestination(icon: Icon(Icons.local_offer), label: 'Deals'),
          NavigationDestination(icon: Icon(Icons.person), label: 'Profile'),
        ],
        onDestinationSelected: (i) => setState(() => index = i),
      ),
      floatingActionButton: (index == 0 || index == 1) ? FloatingActionButton(
        onPressed: () {
          showModalBottomSheet(
            context: context,
            isScrollControlled: true,
            builder: (context) => const CreateTrackerSheet(),
          );
        },
        child: const Icon(Icons.add),
      ) : null,
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
        child: Text(
          'Failed to load your trackers.\n$e',
          textAlign: TextAlign.center,
        ),
      ),
      data: (items) {
        if (items.isEmpty) {
          return const Center(
            child: Text(
              'No active trackers yet.\nTap + to start tracking a product.',
              textAlign: TextAlign.center,
            ),
          );
        }
        return ListView.builder(
          itemCount: items.length,
          itemBuilder: (context, i) {
            final item = items[i];
            final lowest = item.lowestPrice;
            return TrackerCard(
              imageUrl: lowest?.url ?? '',
              title: item.displayName,
              currentPrice: lowest?.priceLocal ?? 0.0,
              targetPrice: item.targetPrice ?? 0.0,
              isActive: item.isActive,
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
            );
          },
        );
      },
    );
  }
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
          title: const Text('Elhaq'),
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
              'Live Market Feed',
              style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.bold,
                  ),
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
              child: Text('Failed to load deals.\n$e'),
            ),
          ),
          data: (deals) {
            if (deals.isEmpty) {
              return SliverToBoxAdapter(
                child: const Padding(
                  padding: EdgeInsets.all(16),
                  child: Text('No live deals right now.'),
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

class _ProfileTab extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Center(
      child: ElevatedButton(
        onPressed: () {
          Navigator.push(
            context,
            MaterialPageRoute(builder: (context) => const SubscriptionScreen()),
          );
        },
        child: const Text('Manage Subscription'),
      ),
    );
  }
}