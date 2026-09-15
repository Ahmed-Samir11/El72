import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/providers.dart';
import '../widgets/deal_card.dart';

/// Deal Discovery feed, consuming `GET /deals/live` (with demo fallback).
class DealsFeedPage extends ConsumerWidget {
  const DealsFeedPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final dealsAsync = ref.watch(liveDealsProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Live Deals')),
      body: dealsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(
          child: Text(
            'Failed to load deals.\n$e',
            textAlign: TextAlign.center,
          ),
        ),
        data: (deals) {
          if (deals.isEmpty) {
            return const Center(
              child: Text('No live deals right now. Check back soon.'),
            );
          }
          return ListView.builder(
            itemCount: deals.length,
            itemBuilder: (context, i) => DealCard(deal: deals[i]),
          );
        },
      ),
    );
  }
}
