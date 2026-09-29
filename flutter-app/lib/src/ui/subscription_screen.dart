import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../l10n/app_localizations.dart';

class SubscriptionScreen extends StatelessWidget {
  const SubscriptionScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(AppLocalizations.of(context).subscriptionPlans),
      ),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            _buildPlanCard(
              AppLocalizations.of(context).freePlanShort,
              AppLocalizations.of(context).basicTracking,
              AppLocalizations.of(context).egpPerMonth('0'),
              Theme.of(context).colorScheme.outline,
              () {
                // Handle free plan
              },
            ),
            const SizedBox(height: 16),
            _buildPlanCard(
              AppLocalizations.of(context).proPlan,
              AppLocalizations.of(context).unlimitedTracking,
              AppLocalizations.of(context).egpPerMonth('50'),
              Theme.of(context).colorScheme.primary,
              () => _launchPayment('pro'),
            ),
            const SizedBox(height: 16),
            _buildPlanCard(
              AppLocalizations.of(context).businessPlan,
              AppLocalizations.of(context).advancedAnalytics,
              AppLocalizations.of(context).egpPerMonth('200'),
              Theme.of(context).colorScheme.secondary,
              () => _launchPayment('business'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildPlanCard(
    String title,
    String description,
    String price,
    Color color,
    VoidCallback onTap,
  ) {
    return Card(
      color: color.withValues(alpha: 0.1),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: TextStyle(
                  fontSize: 24,
                  fontWeight: FontWeight.bold,
                  color: color,
                ),
              ),
              const SizedBox(height: 8),
              Text(description),
              const SizedBox(height: 8),
              Text(
                price,
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _launchPayment(String plan) async {
    // Mock payment URL - replace with actual Paymob link
    final url = 'https://paymob.com/pay/$plan';
    if (await canLaunchUrl(Uri.parse(url))) {
      await launchUrl(Uri.parse(url));
    }
  }
}
