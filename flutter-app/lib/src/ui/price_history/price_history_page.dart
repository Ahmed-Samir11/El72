import 'dart:math' as math;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/styles/app_colors.dart';
import '../../data/models/price_point_model.dart';
import '../../data/providers.dart';

/// Price history chart for a single product, consuming
/// `GET /price-history/{sku}` (with demo fallback).
class PriceHistoryPage extends ConsumerWidget {
  final String sku;
  final String title;

  const PriceHistoryPage({super.key, required this.sku, this.title = ''});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final pointsAsync = ref.watch(priceHistoryProvider(sku));
    return Scaffold(
      appBar: AppBar(
        title: Text(title.isEmpty ? 'Price History' : title),
      ),
      body: pointsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => _ErrorView(message: e.toString()),
        data: (points) {
          if (points.isEmpty) return const _EmptyView();
          return _PriceChart(points: points);
        },
      ),
    );
  }
}

class _PriceChart extends StatelessWidget {
  final List<PricePoint> points;

  const _PriceChart({required this.points});

  @override
  Widget build(BuildContext context) {
    final spots = List.generate(
      points.length,
      (i) => FlSpot(i.toDouble(), points[i].priceLocal),
    );
    final prices = points.map((p) => p.priceLocal).toList();
    final maxY = prices.reduce(math.max).toDouble();
    final minY = prices.reduce(math.min).toDouble();
    final double range = (maxY - minY) == 0 ? maxY * 0.1 : (maxY - minY);

    final double interval = (points.length / 6).ceilToDouble().clamp(1.0, 1e9);

    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _SummaryRow(points: points),
          const SizedBox(height: 24),
          SizedBox(
            height: 260,
            child: LineChart(
              LineChartData(
                lineTouchData: LineTouchData(
                  touchTooltipData: LineTouchTooltipData(
                    getTooltipColor: (_) => AppColors.primary,
                    tooltipRoundedRadius: 8,
                  ),
                ),
                gridData: FlGridData(
                  show: true,
                  drawVerticalLine: false,
                  horizontalInterval: range / 4,
                  verticalInterval: interval,
                ),
                titlesData: FlTitlesData(
                  show: true,
                  topTitles: const AxisTitles(),
                  rightTitles: const AxisTitles(),
                  leftTitles: AxisTitles(
                    sideTitles: SideTitles(
                      showTitles: true,
                      interval: range / 4,
                      getTitlesWidget: (value, meta) => Text(
                        _formatPrice(value.toInt()),
                        style: const TextStyle(fontSize: 10),
                      ),
                    ),
                  ),
                  bottomTitles: AxisTitles(
                    sideTitles: SideTitles(
                      showTitles: true,
                      interval: interval,
                      getTitlesWidget: (value, meta) {
                        final idx = value.round();
                        if (idx < 0 || idx >= points.length) {
                          return const SizedBox.shrink();
                        }
                        final day = points[idx].time;
                        return Text(
                          '${day.month}/${day.day}',
                          style: const TextStyle(fontSize: 10),
                        );
                      },
                    ),
                  ),
                ),
                lineBarsData: [
                  LineChartBarData(
                    spots: spots,
                    isCurved: true,
                    color: AppColors.secondary,
                    barWidth: 3,
                    isStrokeCapRound: true,
                    dotData: const FlDotData(show: false),
                    belowBarData: BarAreaData(
                      show: true,
                      gradient: LinearGradient(
                        begin: Alignment.topCenter,
                        end: Alignment.bottomCenter,
                        colors: [
                          AppColors.secondary.withValues(alpha: 0.3),
                          AppColors.secondary.withValues(alpha: 0.0),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
              duration: const Duration(milliseconds: 300),
            ),
          ),
        ],
      ),
    );
  }

  String _formatPrice(int value) {
    if (value >= 1000) {
      return '${(value / 1000).toStringAsFixed(0)}K';
    }
    return '$value';
  }
}

class _SummaryRow extends StatelessWidget {
  final List<PricePoint> points;

  const _SummaryRow({required this.points});

  @override
  Widget build(BuildContext context) {
    final prices = points.map((p) => p.priceLocal).toList();
    final current = prices.last;
    final lowest = prices.reduce(math.min);
    final highest = prices.reduce(math.max);
    final change = current - prices.first;
    final changePct = prices.first == 0
        ? 0.0
        : (change / prices.first) * 100;

    return Row(
      children: [
        Expanded(
          child: _Stat(
            label: 'Current',
            value: 'EGP ${current.toStringAsFixed(0)}',
            color: AppColors.textPrimary,
          ),
        ),
        Expanded(
          child: _Stat(
            label: '90d Low',
            value: 'EGP ${lowest.toStringAsFixed(0)}',
            color: AppColors.priceDown,
          ),
        ),
        Expanded(
          child: _Stat(
            label: '90d High',
            value: 'EGP ${highest.toStringAsFixed(0)}',
            color: AppColors.priceUp,
          ),
        ),
        Expanded(
          child: _Stat(
            label: 'Change',
            value:
                '${change >= 0 ? '+' : ''}${changePct.toStringAsFixed(1)}%',
            color: change >= 0 ? AppColors.priceUp : AppColors.priceDown,
          ),
        ),
      ],
    );
  }
}

class _Stat extends StatelessWidget {
  final String label;
  final String value;
  final Color color;

  const _Stat({
    required this.label,
    required this.value,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
            fontSize: 12,
            color: AppColors.textSecondary,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          value,
          style: TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.bold,
            color: color,
          ),
        ),
      ],
    );
  }
}

class _EmptyView extends StatelessWidget {
  const _EmptyView();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Text(
        'No price history available for this product yet.',
        style: TextStyle(color: AppColors.textSecondary),
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  final String message;

  const _ErrorView({required this.message});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Text(
          'Failed to load price history.\n$message',
          textAlign: TextAlign.center,
          style: const TextStyle(color: AppColors.textSecondary),
        ),
      ),
    );
  }
}
