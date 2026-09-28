import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

/// Reliable product image with disk caching, a loading placeholder, and a
/// themed fallback icon when the URL is missing or the load fails.
class ProductImage extends StatelessWidget {
  final String imageUrl;
  final double size;

  const ProductImage({
    super.key,
    required this.imageUrl,
    this.size = 60,
  });

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final radius = BorderRadius.circular(8);

    if (!imageUrl.startsWith('http')) {
      return Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          borderRadius: radius,
          color: colorScheme.surfaceContainerHighest,
        ),
        child: Icon(Icons.shopping_bag_outlined,
            size: size * 0.5, color: colorScheme.onSurfaceVariant),
      );
    }

    return ClipRRect(
      borderRadius: radius,
      child: CachedNetworkImage(
        imageUrl: imageUrl,
        fit: BoxFit.cover,
        width: size,
        height: size,
        placeholder: (BuildContext context, String url) => Container(
          color: colorScheme.surfaceContainerHighest,
          child: const Center(child: CircularProgressIndicator(strokeWidth: 2)),
        ),
        errorWidget: (BuildContext context, String url, Object error) =>
            Container(
              color: colorScheme.surfaceContainerHighest,
              child: Icon(Icons.shopping_bag_outlined,
                  size: size * 0.5, color: colorScheme.onSurfaceVariant),
            ),
      ),
    );
  }
}
