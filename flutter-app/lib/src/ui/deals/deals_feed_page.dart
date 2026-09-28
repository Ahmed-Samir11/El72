import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../l10n/app_localizations.dart';
import '../../data/models/deal_model.dart';
import '../../data/providers.dart';
import '../common/async_state_view.dart';
import '../widgets/deal_card.dart';

/// Deal Discovery feed, consuming `GET /deals/live` (with demo fallback).
class DealsFeedPage extends ConsumerWidget {
  const DealsFeedPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final dealsAsync = ref.watch(liveDealsProvider);
    return Scaffold(
      appBar: AppBar(title: Text(AppLocalizations.of(context).liveDeals)),
      body: AsyncStateView<List<Deal>>(
        value: dealsAsync,
        builder: (deals) {
          if (deals.isEmpty) {
            return Center(
              child: Text(AppLocalizations.of(context).noLiveDeals),
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
