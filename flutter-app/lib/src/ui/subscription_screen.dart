import 'package:flutter/material.dart';

import '../data/models/payment_models.dart';
import '../../l10n/app_localizations.dart';
import 'payment/wallet_payment_screen.dart';

/// Credit packages screen (one-time purchases, server-priced).
///
/// Replaces the old mock "subscription plans" screen: the app only offers
/// the real one-time credit packages and routes the purchase through the
/// Paymob wallet flow (Feature 2). Pricing displayed here mirrors the
/// server allowlist — the authoritative price is always the backend's.
class SubscriptionScreen extends StatelessWidget {
  const SubscriptionScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.creditPackages)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  Icon(Icons.check_circle, color: scheme.primary),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          l10n.freePlanShort,
                          style: const TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        Text(l10n.freeCreditsDesc),
                      ],
                    ),
                  ),
                  Chip(label: Text(l10n.currentPlan)),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          for (final package in CreditPackage.all)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Card(
                child: InkWell(
                  borderRadius: BorderRadius.circular(12),
                  onTap: () => Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (_) =>
                          WalletPaymentScreen(initialPackage: package),
                    ),
                  ),
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Row(
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                package == CreditPackage.premium
                                    ? l10n.premiumPackage
                                    : l10n.standardPackage,
                                style: const TextStyle(
                                  fontSize: 18,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                              Text(
                                package == CreditPackage.premium
                                    ? l10n.premiumPackageDesc
                                    : l10n.standardPackageDesc,
                              ),
                            ],
                          ),
                        ),
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: [
                            Text(
                              l10n.creditsLabel(package.credits),
                              style: TextStyle(color: scheme.primary),
                            ),
                            Text(l10n.egpOnce('${package.priceEgp}')),
                            const SizedBox(height: 4),
                            Text(l10n.buyNow),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
