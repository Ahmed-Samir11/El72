import 'package:flutter_riverpod/flutter_riverpod.dart';

enum TrackingStatus {
  idle,
  creating,
  scraping,
  analyzing,
  notifying,
  completed,
  error,
}

class TrackingState {
  final TrackingStatus status;
  final String message;
  final String? productUrl;
  final double? targetPrice;
  final double? currentPrice;

  const TrackingState({
    required this.status,
    required this.message,
    this.productUrl,
    this.targetPrice,
    this.currentPrice,
  });

  TrackingState copyWith({
    TrackingStatus? status,
    String? message,
    String? productUrl,
    double? targetPrice,
    double? currentPrice,
  }) {
    return TrackingState(
      status: status ?? this.status,
      message: message ?? this.message,
      productUrl: productUrl ?? this.productUrl,
      targetPrice: targetPrice ?? this.targetPrice,
      currentPrice: currentPrice ?? this.currentPrice,
    );
  }
}

class TrackingStatusNotifier extends StateNotifier<TrackingState> {
  TrackingStatusNotifier()
      : super(const TrackingState(
          status: TrackingStatus.idle,
          message: '',
        ));

  void startTracking(String url, double price) {
    state = TrackingState(
      status: TrackingStatus.creating,
      message: 'Creating tracker...',
      productUrl: url,
      targetPrice: price,
    );
  }

  void updateStatus(TrackingStatus status, String message, {double? currentPrice}) {
    state = state.copyWith(
      status: status,
      message: message,
      currentPrice: currentPrice,
    );
  }

  void complete({double? finalPrice}) {
    state = state.copyWith(
      status: TrackingStatus.completed,
      message: finalPrice != null && finalPrice > 0
          ? 'Found! Current price: ${finalPrice.toStringAsFixed(2)} EGP'
          : 'Tracker created! Monitoring for deals...',
      currentPrice: finalPrice,
    );
  }

  void error(String message) {
    state = state.copyWith(
      status: TrackingStatus.error,
      message: message,
    );
  }

  void reset() {
    state = const TrackingState(
      status: TrackingStatus.idle,
      message: '',
    );
  }
}

final trackingStatusProvider =
    StateNotifierProvider<TrackingStatusNotifier, TrackingState>((ref) {
  return TrackingStatusNotifier();
});
