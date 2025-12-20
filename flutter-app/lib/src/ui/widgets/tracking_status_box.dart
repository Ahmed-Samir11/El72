import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../data/providers/tracking_status_provider.dart';

class TrackingStatusBox extends ConsumerWidget {
  const TrackingStatusBox({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final trackingState = ref.watch(trackingStatusProvider);

    if (trackingState.status == TrackingStatus.idle) {
      return const SizedBox.shrink();
    }

    return Container(
      margin: const EdgeInsets.all(16),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: _getGradientColors(trackingState.status),
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: _getGradientColors(trackingState.status)[0].withOpacity(0.3),
            blurRadius: 12,
            offset: const Offset(0, 6),
          ),
        ],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Status Icon
          _buildStatusIcon(trackingState.status),
          const SizedBox(height: 16),

          // Status Message
          Text(
            trackingState.message,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 16,
              fontWeight: FontWeight.w600,
            ),
            textAlign: TextAlign.center,
          ),

          // Progress Indicator (for active statuses)
          if (_isActiveStatus(trackingState.status)) ...[
            const SizedBox(height: 16),
            const SizedBox(
              height: 3,
              child: LinearProgressIndicator(
                backgroundColor: Colors.white24,
                valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
              ),
            ),
          ],

          // Product Info
          if (trackingState.productUrl != null) ...[
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.white.withOpacity(0.2),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                children: [
                  if (trackingState.targetPrice != null)
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Icon(Icons.flag_outlined, color: Colors.white70, size: 16),
                        const SizedBox(width: 8),
                        Text(
                          'Target: ${trackingState.targetPrice!.toStringAsFixed(0)} EGP',
                          style: const TextStyle(
                            color: Colors.white70,
                            fontSize: 14,
                          ),
                        ),
                      ],
                    ),
                  if (trackingState.currentPrice != null &&
                      trackingState.currentPrice! > 0) ...[
                    const SizedBox(height: 8),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Icon(Icons.price_check, color: Colors.white, size: 16),
                        const SizedBox(width: 8),
                        Text(
                          'Current: ${trackingState.currentPrice!.toStringAsFixed(0)} EGP',
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 14,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ],

          // Close Button (for completed/error)
          if (trackingState.status == TrackingStatus.completed ||
              trackingState.status == TrackingStatus.error) ...[
            const SizedBox(height: 16),
            TextButton(
              onPressed: () {
                ref.read(trackingStatusProvider.notifier).reset();
              },
              style: TextButton.styleFrom(
                backgroundColor: Colors.white.withOpacity(0.2),
                padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
              ),
              child: const Text(
                'Close',
                style: TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildStatusIcon(TrackingStatus status) {
    IconData iconData;
    double size = 48;

    switch (status) {
      case TrackingStatus.creating:
        iconData = Icons.add_circle_outline;
        break;
      case TrackingStatus.scraping:
        iconData = Icons.search;
        break;
      case TrackingStatus.analyzing:
        iconData = Icons.analytics_outlined;
        break;
      case TrackingStatus.notifying:
        iconData = Icons.notifications_active;
        break;
      case TrackingStatus.completed:
        iconData = Icons.check_circle;
        break;
      case TrackingStatus.error:
        iconData = Icons.error_outline;
        break;
      case TrackingStatus.idle:
        iconData = Icons.info;
        break;
    }

    if (_isActiveStatus(status)) {
      return SizedBox(
        width: size,
        height: size,
        child: Stack(
          alignment: Alignment.center,
          children: [
            SizedBox(
              width: size,
              height: size,
              child: CircularProgressIndicator(
                strokeWidth: 3,
                valueColor: const AlwaysStoppedAnimation<Color>(Colors.white),
              ),
            ),
            Icon(iconData, color: Colors.white, size: size * 0.5),
          ],
        ),
      );
    }

    return Icon(iconData, color: Colors.white, size: size);
  }

  List<Color> _getGradientColors(TrackingStatus status) {
    switch (status) {
      case TrackingStatus.creating:
        return [const Color(0xFF667EEA), const Color(0xFF764BA2)];
      case TrackingStatus.scraping:
        return [const Color(0xFF4776E6), const Color(0xFF8E54E9)];
      case TrackingStatus.analyzing:
        return [const Color(0xFF00B4DB), const Color(0xFF0083B0)];
      case TrackingStatus.notifying:
        return [const Color(0xFFF093FB), const Color(0xFFF5576C)];
      case TrackingStatus.completed:
        return [const Color(0xFF11998E), const Color(0xFF38EF7D)];
      case TrackingStatus.error:
        return [const Color(0xFFEB3349), const Color(0xFFF45C43)];
      case TrackingStatus.idle:
        return [const Color(0xFF667EEA), const Color(0xFF764BA2)];
    }
  }

  bool _isActiveStatus(TrackingStatus status) {
    return status == TrackingStatus.creating ||
        status == TrackingStatus.scraping ||
        status == TrackingStatus.analyzing ||
        status == TrackingStatus.notifying;
  }
}
