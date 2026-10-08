import 'package:flutter/material.dart';

import '../models/traffic_summary.dart';
import '../theme/app_tokens.dart';

/// Reusable time-series chart displaying volume bars and congestion curve
/// with quantitative X/Y scales and touch tooltip inspection.
class VolumeTrendChart extends StatefulWidget {
  const VolumeTrendChart({
    super.key,
    required this.buckets,
    required this.isHourly,
    this.height = 200.0,
  });

  final List<TrafficSummaryBucket> buckets;
  final bool isHourly;
  final double height;

  @override
  State<VolumeTrendChart> createState() => _VolumeTrendChartState();
}

class _VolumeTrendChartState extends State<VolumeTrendChart> {
  int? _selectedIndex;

  String _formatBucketTime(DateTime dt, bool isHourly) {
    if (isHourly) {
      final h = dt.hour.toString().padLeft(2, '0');
      final m = dt.minute.toString().padLeft(2, '0');
      return '$h:$m';
    } else {
      final m = dt.month.toString().padLeft(2, '0');
      final d = dt.day.toString().padLeft(2, '0');
      return '$m/$d';
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final buckets = widget.buckets;

    if (buckets.isEmpty) {
      return Container(
        height: widget.height,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: theme.colorScheme.surface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: theme.colorScheme.outline),
        ),
        child: Text(
          'No telemetry observations recorded for this timeframe',
          style: theme.textTheme.bodySmall?.copyWith(
            color: AppTokens.mutedOf(context),
          ),
        ),
      );
    }

    final maxVol = buckets
        .map((b) => b.avgVehicleCount)
        .fold<double>(1.0, (a, b) => a > b ? a : b);

    final selectedBucket = _selectedIndex != null &&
            _selectedIndex! >= 0 &&
            _selectedIndex! < buckets.length
        ? buckets[_selectedIndex!]
        : null;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // Interactive tooltip when operator touches a bar
        if (selectedBucket != null)
          Container(
            margin: const EdgeInsets.only(bottom: AppTokens.spaceSm),
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: theme.colorScheme.surface,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: AppTokens.teal.withAlpha(90)),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withAlpha(20),
                  blurRadius: 6,
                  offset: const Offset(0, 2),
                ),
              ],
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Row(
                  children: [
                    const Icon(Icons.access_time_rounded,
                        size: 14, color: AppTokens.teal),
                    const SizedBox(width: 4),
                    Text(
                      _formatBucketTime(selectedBucket.bucket, widget.isHourly),
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        color: theme.colorScheme.onSurface,
                      ),
                    ),
                  ],
                ),
                Row(
                  children: [
                    Container(
                      width: 8,
                      height: 8,
                      decoration: const BoxDecoration(
                        color: AppTokens.teal,
                        shape: BoxShape.circle,
                      ),
                    ),
                    const SizedBox(width: 4),
                    Text(
                      '${selectedBucket.avgVehicleCount.toStringAsFixed(0)} veh',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: theme.colorScheme.onSurface,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Container(
                      width: 8,
                      height: 8,
                      decoration: const BoxDecoration(
                        color: AppTokens.amber,
                        shape: BoxShape.circle,
                      ),
                    ),
                    const SizedBox(width: 4),
                    Text(
                      '${selectedBucket.avgCongestion.toStringAsFixed(1)}%',
                      style: const TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        color: AppTokens.amber,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),

        // Quantitative Scale Header
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'Volume (max: ${maxVol >= 1000 ? "${(maxVol / 1000).toStringAsFixed(1)}k" : maxVol.toStringAsFixed(0)})',
                style: TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.w600,
                  color: AppTokens.teal,
                ),
              ),
              const Text(
                'Congestion (0-100%)',
                style: TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.w600,
                  color: AppTokens.amber,
                ),
              ),
            ],
          ),
        ),

        // Custom canvas with gestures
        LayoutBuilder(
          builder: (context, constraints) {
            final canvasWidth = constraints.maxWidth;
            final canvasHeight = widget.height - (selectedBucket != null ? 36 : 0);

            return GestureDetector(
              onTapDown: (details) {
                final slotWidth = canvasWidth / buckets.length;
                final idx = (details.localPosition.dx / slotWidth).floor().clamp(0, buckets.length - 1);
                setState(() {
                  _selectedIndex = idx;
                });
              },
              onPanUpdate: (details) {
                final slotWidth = canvasWidth / buckets.length;
                final idx = (details.localPosition.dx / slotWidth).floor().clamp(0, buckets.length - 1);
                setState(() {
                  _selectedIndex = idx;
                });
              },
              child: SizedBox(
                height: canvasHeight,
                width: canvasWidth,
                child: Semantics(
                  label:
                      'Traffic volume trend chart displaying volume bars and congestion curve over ${widget.isHourly ? "hours" : "days"}',
                  button: false,
                  child: CustomPaint(
                    painter: _VolumeTrendCanvasPainter(
                      buckets: buckets,
                      isHourly: widget.isHourly,
                      maxVol: maxVol,
                      selectedIndex: _selectedIndex,
                      gridColor: theme.colorScheme.outline,
                      textColor: AppTokens.mutedOf(context),
                    ),
                  ),
                ),
              ),
            );
          },
        ),

        // X-axis Time Marks Footer
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                _formatBucketTime(buckets.first.bucket, widget.isHourly),
                style: TextStyle(
                  fontSize: 10,
                  color: AppTokens.mutedOf(context),
                ),
              ),
              if (buckets.length > 2)
                Text(
                  _formatBucketTime(
                    buckets[buckets.length ~/ 2].bucket,
                    widget.isHourly,
                  ),
                  style: TextStyle(
                    fontSize: 10,
                    color: AppTokens.mutedOf(context),
                  ),
                ),
              Text(
                _formatBucketTime(buckets.last.bucket, widget.isHourly),
                style: TextStyle(
                  fontSize: 10,
                  color: AppTokens.mutedOf(context),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _VolumeTrendCanvasPainter extends CustomPainter {
  _VolumeTrendCanvasPainter({
    required this.buckets,
    required this.isHourly,
    required this.maxVol,
    this.selectedIndex,
    required this.gridColor,
    required this.textColor,
  });

  final List<TrafficSummaryBucket> buckets;
  final bool isHourly;
  final double maxVol;
  final int? selectedIndex;
  final Color gridColor;
  final Color textColor;

  @override
  void paint(Canvas canvas, Size size) {
    if (buckets.isEmpty) return;

    final n = buckets.length;

    // Gridlines (horizontal)
    final gridPaint = Paint()
      ..color = gridColor.withAlpha(60)
      ..strokeWidth = 1.0;

    for (int i = 1; i <= 3; i++) {
      final y = size.height * (i / 4);
      canvas.drawLine(Offset(0, y), Offset(size.width, y), gridPaint);
    }

    final slotWidth = size.width / n;
    final barWidth = slotWidth * 0.55;

    final barPaint = Paint()
      ..color = AppTokens.teal.withAlpha(160)
      ..style = PaintingStyle.fill;

    final selectedBarPaint = Paint()
      ..color = AppTokens.teal
      ..style = PaintingStyle.fill;

    final linePaint = Paint()
      ..color = AppTokens.amber
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.0;

    final linePath = Path();

    for (int i = 0; i < n; i++) {
      final b = buckets[i];
      final centerX = (i * slotWidth) + (slotWidth / 2);

      // Volume bar
      final normalizedVol = maxVol > 0 ? (b.avgVehicleCount / maxVol) : 0.0;
      final barHeight = normalizedVol * (size.height - 20);
      final isSelected = selectedIndex == i;

      final barRect = RRect.fromRectAndRadius(
        Rect.fromLTWH(
          centerX - (barWidth / 2),
          size.height - barHeight - 8,
          barWidth,
          barHeight,
        ),
        const Radius.circular(3),
      );
      canvas.drawRRect(barRect, isSelected ? selectedBarPaint : barPaint);

      // Congestion curve point (0-100%)
      final congY = (size.height - 16) -
          ((b.avgCongestion / 100.0) * (size.height - 24));
      if (i == 0) {
        linePath.moveTo(centerX, congY);
      } else {
        linePath.lineTo(centerX, congY);
      }

      canvas.drawCircle(
        Offset(centerX, congY),
        isSelected ? 4.0 : 2.5,
        Paint()..color = AppTokens.amber,
      );
    }

    canvas.drawPath(linePath, linePaint);
  }

  @override
  bool shouldRepaint(covariant _VolumeTrendCanvasPainter oldDelegate) {
    return oldDelegate.buckets != buckets ||
        oldDelegate.selectedIndex != selectedIndex ||
        oldDelegate.gridColor != gridColor;
  }
}
