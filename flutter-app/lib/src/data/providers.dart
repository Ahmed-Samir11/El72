import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'models/credit_balance_model.dart';
import 'models/deal_model.dart';
import 'models/platform_stats_model.dart';
import 'models/price_point_model.dart';
import 'models/tracked_item_model.dart';
import 'repositories/auth_repository.dart';
import 'repositories/credits_repository.dart';
import 'repositories/deals_repository.dart';
import 'repositories/price_history_repository.dart';
import 'repositories/stats_repository.dart';
import 'repositories/tracked_items_repository.dart';

final authRepositoryProvider = Provider<AuthRepository>((ref) {
  return AuthRepository();
});

final trackedItemsRepositoryProvider = Provider<TrackedItemsRepository>((ref) {
  return TrackedItemsRepository();
});

final dealsRepositoryProvider = Provider<DealsRepository>((ref) {
  return DealsRepository();
});

final statsRepositoryProvider = Provider<StatsRepository>((ref) {
  return StatsRepository();
});

final priceHistoryRepositoryProvider = Provider<PriceHistoryRepository>((ref) {
  return PriceHistoryRepository();
});

final creditsRepositoryProvider = Provider<CreditsRepository>((ref) {
  return CreditsRepository();
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

/// The current user's credit balance and tier.
///
/// One-shot [FutureProvider]: callers must `ref.invalidate(creditBalanceProvider)`
/// after any credit-consuming action (e.g. successful tracker creation) so
/// the Profile tab reflects the new balance without an app restart.
final creditBalanceProvider = FutureProvider<CreditBalance>((ref) {
  return ref.read(creditsRepositoryProvider).getBalance();
});

/// Price history for a single SKU (keyed by [sku]).
final priceHistoryProvider = FutureProvider.family<List<PricePoint>, String>((
  ref,
  sku,
) {
  return ref.read(priceHistoryRepositoryProvider).getPriceHistory(sku);
});
