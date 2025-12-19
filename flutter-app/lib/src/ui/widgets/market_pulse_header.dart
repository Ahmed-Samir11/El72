import 'package:flutter/material.dart';
import '../../core/styles/app_colors.dart';

class MarketPulseHeader extends StatelessWidget {
  final int activeAlerts;
  final int dealsToday;
  final double savings;

  const MarketPulseHeader({
    super.key,
    required this.activeAlerts,
    required this.dealsToday,
    required this.savings,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.all(16),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.primary,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceEvenly,
        children: [
          _StatItem(
            label: 'Active Alerts',
            value: activeAlerts.toString(),
            icon: Icons.notifications_active,
          ),
          Container(
            height: 40,
            width: 1,
            color: Colors.white.withValues(alpha: 0.3),
          ),
          _StatItem(
            label: 'Deals Today',
            value: dealsToday.toString(),
            icon: Icons.local_offer,
          ),
          Container(
            height: 40,
            width: 1,
            color: Colors.white.withValues(alpha: 0.3),
          ),
          _StatItem(
            label: 'Savings',
            value: '\$${savings.toStringAsFixed(0)}',
            icon: Icons.savings,
          ),
        ],
      ),
    );
  }
}

class _StatItem extends StatelessWidget {
  final String label;
  final String value;
  final IconData icon;

  const _StatItem({
    required this.label,
    required this.value,
    required this.icon,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(
          icon,
          color: Colors.white,
          size: 20,
        ),
        const SizedBox(height: 4),
        Text(
          value,
          style: const TextStyle(
            color: Colors.white,
            fontSize: 18,
            fontWeight: FontWeight.bold,
          ),
        ),
        Text(
          label,
          style: TextStyle(
            color: Colors.white.withValues(alpha: 0.8),
            fontSize: 12,
          ),
        ),
      ],
    );
  }
}