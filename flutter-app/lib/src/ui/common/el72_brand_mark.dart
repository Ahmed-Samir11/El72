import 'package:flutter/material.dart';

import '../../core/styles/app_colors.dart';

class El72BrandMark extends StatelessWidget {
  const El72BrandMark({
    super.key,
    this.size = 104,
    this.showTagline = true,
    this.alignCenter = false,
  });

  final double size;
  final bool showTagline;
  final bool alignCenter;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: alignCenter ? CrossAxisAlignment.center : CrossAxisAlignment.start,
      children: [
        Semantics(
          label: 'El72 logo',
          image: true,
          child: Container(
            width: size,
            height: size,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(size * 0.28),
              gradient: const LinearGradient(
                colors: [Color(0xFFFFE066), Color(0xFFFFA726), Color(0xFFFF6F00)],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
              boxShadow: const [
                BoxShadow(
                  color: Color(0x26FF8A00),
                  blurRadius: 20,
                  offset: Offset(0, 10),
                ),
              ],
            ),
            child: Stack(
              children: [
                Positioned(
                  right: -14,
                  top: -16,
                  child: Container(
                    width: size * 0.45,
                    height: size * 0.45,
                    decoration: const BoxDecoration(
                      shape: BoxShape.circle,
                      color: Color(0x33FFFFFF),
                    ),
                  ),
                ),
                Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        'EL72',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: size * 0.24,
                          fontWeight: FontWeight.w900,
                          letterSpacing: 1.6,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Container(
                        width: size * 0.42,
                        height: 4,
                        decoration: BoxDecoration(
                          color: Colors.white.withValues(alpha: 0.9),
                          borderRadius: BorderRadius.circular(999),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
        if (showTagline) ...[
          const SizedBox(height: 12),
          const Text(
            'El72',
            style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w800,
              color: AppColors.textPrimary,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            'Real-time price intelligence',
            textAlign: alignCenter ? TextAlign.center : TextAlign.start,
            style: const TextStyle(
              fontSize: 13,
              color: AppColors.textSecondary,
            ),
          ),
        ],
      ],
    );
  }
}