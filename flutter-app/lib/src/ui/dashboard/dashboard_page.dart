import 'package:flutter/material.dart';
import '../create_tracker_sheet.dart';
import '../subscription_screen.dart';
import '../widgets/deal_card.dart';
import '../widgets/market_pulse_header.dart';

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

class _TrackersTab extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Text('Active Price Trackers'),
    );
  }
}

class _DealsTab extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    // Mock data for immediate UI rendering
    final mockDeals = [
      const Deal(
        id: '1',
        title: 'iPhone 15 Pro Max 256GB',
        storeName: 'Amazon EG',
        imageUrl: '',
        price: 1299.99,
        originalPrice: 1499.99,
        discountPercentage: 13.3,
      ),
      const Deal(
        id: '2',
        title: 'PlayStation 5 Slim Bundle',
        storeName: 'Jumia EG',
        imageUrl: '',
        price: 499.99,
        originalPrice: 599.99,
        discountPercentage: 16.7,
      ),
      const Deal(
        id: '3',
        title: 'NVIDIA RTX 4060 Graphics Card',
        storeName: 'Newegg',
        imageUrl: '',
        price: 299.99,
        originalPrice: 399.99,
        discountPercentage: 25.0,
      ),
      const Deal(
        id: '4',
        title: 'Samsung 55" 4K Smart TV',
        storeName: 'Carrefour EG',
        imageUrl: '',
        price: 699.99,
        originalPrice: 899.99,
        discountPercentage: 22.2,
      ),
      const Deal(
        id: '5',
        title: 'MacBook Air M2 13"',
        storeName: 'Apple Store EG',
        imageUrl: '',
        price: 1099.99,
        originalPrice: 1199.99,
        discountPercentage: 8.3,
      ),
    ];

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

        // Market Pulse Header
        SliverToBoxAdapter(
          child: MarketPulseHeader(
            activeAlerts: 12,
            dealsToday: 47,
            savings: 2847.50,
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

        // Deals List
        SliverList(
          delegate: SliverChildBuilderDelegate(
            (context, index) {
              return DealCard(deal: mockDeals[index]);
            },
            childCount: mockDeals.length,
          ),
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