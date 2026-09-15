import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'models/deal_model.dart';
import 'models/platform_stats_model.dart';
import 'models/price_point_model.dart';
import 'models/tracked_item_model.dart';
import 'repositories/auth_repository.dart';
import 'repositories/deals_repository.dart';
import 'repositories/price_history_repository.dart';
import 'repositories/stats_repository.dart';
import 'repositories/tracked_items_repository.dart';

final authRepositoryProvider = Provider<AuthRepository>((ref) {
  return AuthRepository();
});

final trackedItemsRepositoryProvider =
    Provider<TrackedItemsRepository>((ref) {
  return TrackedItemsRepository();
});

final dealsRepositoryProvider = Provider<DealsRepository>((ref) {
  return DealsRepository();
});

final statsRepositoryProvider = Provider<StatsRepository>((ref) {
  return StatsRepository();
});

final priceHistoryRepositoryProvider =
    Provider<PriceHistoryRepository>((ref) {
  return PriceHistoryRepository();
});

/// The current user's active tracked items.
final trackedItemsProvider = FutureProvider<List<TrackedItem>>((ref) {
  return ref.read(trackedItemsRepositoryProvider).getTrackedItems();
});

/// Live deal discovery feed.
final liveDealsProvider = FutureProvider<List<Deal>>((ref) {
  return ref.read(dealsRepositoryProvider).getLiveDeals();
});

/// Platform-wide stats for the Market Pulse header.
final platformStatsProvider = FutureProvider<PlatformStats>((ref) {
  return ref.read(statsRepositoryProvider).getStats();
});

/// Price history for a single SKU (keyed by [sku]).
final priceHistoryProvider =
    FutureProvider.family<List<PricePoint>, String>((ref, sku) {
  return ref.read(priceHistoryRepositoryProvider).getPriceHistory(sku);
});