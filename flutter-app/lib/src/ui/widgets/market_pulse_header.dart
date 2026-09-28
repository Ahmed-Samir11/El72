import 'package:flutter/material.dart';

import '../../../l10n/app_localizations.dart';
import '../../core/format/price_format.dart';
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
    final locale = Localizations.localeOf(context);
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
            label: AppLocalizations.of(context).activeAlerts,
            value: activeAlerts.toString(),
            icon: Icons.notifications_active,
          ),
          Container(
            height: 40,
            width: 1,
            color: Colors.white.withValues(alpha: 0.3),
          ),
          _StatItem(
            label: AppLocalizations.of(context).dealsToday,
            value: dealsToday.toString(),
            icon: Icons.local_offer,
          ),
          Container(
            height: 40,
            width: 1,
            color: Colors.white.withValues(alpha: 0.3),
          ),
          _StatItem(
            label: AppLocalizations.of(context).savings,
            value: formatPrice(savings, locale: locale),
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
    // Text on the brand-orange card uses the theme's onPrimary token so it
    // stays legible in both light and dark themes.
    final onPrimary = Theme.of(context).colorScheme.onPrimary;
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, color: onPrimary, size: 20),
        const SizedBox(height: 4),
        Text(
          value,
          style: TextStyle(
            color: onPrimary,
            fontSize: 18,
            fontWeight: FontWeight.bold,
          ),
        ),
        Text(
          label,
          style: TextStyle(
            color: onPrimary.withValues(alpha: 0.8),
            fontSize: 12,
          ),
        ),
      ],
    );
  }
}
