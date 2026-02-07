import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../core/styles/app_colors.dart';

class SubscriptionScreen extends StatelessWidget {
  const SubscriptionScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Subscription Plans'),
        backgroundColor: AppColors.primary,
        foregroundColor: Colors.white,
      ),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            _buildPlanCard(
              'Free',
              'Basic tracking for 3 products',
              'EGP 0/month',
              AppColors.primary.withOpacity(0.5), // Light teal
              () {
                // Handle free plan
              },
            ),
            const SizedBox(height: 16),
            _buildPlanCard(
              'Pro',
              'Unlimited tracking + notifications',
              'EGP 50/month',
              AppColors.secondary, // Orange
              () => _launchPayment('pro'),
            ),
            const SizedBox(height: 16),
            _buildPlanCard(
              'Business',
              'Advanced analytics + API access',
              'EGP 200/month',
              AppColors.primary, // Deep teal
              () => _launchPayment('business'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildPlanCard(String title, String description, String price, Color color, VoidCallback onTap) {
    return Card(
      color: color,
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
                style: const TextStyle(
                  fontSize: 24,
                  fontWeight: FontWeight.bold,
                  color: Colors.white,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                description,
                style: const TextStyle(color: Colors.white),
              ),
              const SizedBox(height: 8),
              Text(
                price,
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                  color: Colors.white,
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