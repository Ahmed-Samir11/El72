import 'package:flutter/material.dart';
import '../../core/styles/app_colors.dart';

class Deal {
  final String id;
  final String title;
  final String storeName;
  final String imageUrl;
  final double price;
  final double originalPrice;
  final double discountPercentage;

  const Deal({
    required this.id,
    required this.title,
    required this.storeName,
    required this.imageUrl,
    required this.price,
    required this.originalPrice,
    required this.discountPercentage,
  });
}

class DealCard extends StatelessWidget {
  final Deal deal;

  const DealCard({
    super.key,
    required this.deal,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
      ),
      elevation: 2,
      child: InkWell(
        onTap: () {
          // TODO: Navigate to ProductDetailsPage
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Navigate to ${deal.title} details')),
          );
        },
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              // Product Image
              Container(
                width: 60,
                height: 60,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(8),
                  color: Theme.of(context).cardColor,
                ),
                child: deal.imageUrl.isNotEmpty
                    ? ClipRRect(
                        borderRadius: BorderRadius.circular(8),
                        child: Image.network(
                          deal.imageUrl,
                          fit: BoxFit.cover,
                          errorBuilder: (context, error, stackTrace) =>
                              const Icon(Icons.shopping_bag_outlined, size: 30),
                        ),
                      )
                    : const Icon(Icons.shopping_bag_outlined, size: 30),
              ),
              const SizedBox(width: 16),

              // Center Content
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Title
                    Text(
                      deal.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w600,
                          ),
                    ),
                    const SizedBox(height: 4),

                    // Store Name
                    Text(
                      deal.storeName,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                            color: AppColors.textSecondary,
                          ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 16),

              // Right Content
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  // Price
                  Text(
                    '\$${deal.price.toStringAsFixed(2)}',
                    style: AppColors.priceTextStyle.copyWith(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                    ),
                  ),

                  // Original Price (strikethrough)
                  if (deal.originalPrice > deal.price)
                    Text(
                      '\$${deal.originalPrice.toStringAsFixed(2)}',
                      style: TextStyle(
                        fontSize: 14,
                        color: AppColors.textSecondary,
                        decoration: TextDecoration.lineThrough,
                      ),
                    ),

                  const SizedBox(height: 8),

                  // Discount Badge
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: AppColors.priceDown,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      '-${deal.discountPercentage.toStringAsFixed(0)}%',
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}