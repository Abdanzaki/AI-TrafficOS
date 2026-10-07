import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/hotspot.dart';
import '../models/incident.dart';
import '../models/traffic_summary.dart';
import '../services/analytics_service.dart';
import '../services/api_client.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_card.dart';
import '../widgets/empty_state.dart';
import '../widgets/error_state.dart';
import '../widgets/loading_state.dart';

/// Citywide traffic telemetry aggregation, congestion hotspots ranking, and incident distributions.
class AnalyticsScreen extends ConsumerStatefulWidget {
  const AnalyticsScreen({super.key});

  @override
  ConsumerState<AnalyticsScreen> createState() => _AnalyticsScreenState();
}

class _AnalyticsScreenState extends ConsumerState<AnalyticsScreen> {
  final ScrollController _scrollController = ScrollController();

  List<TrafficSummaryBucket> _buckets = [];
  List<CongestionHotspot> _hotspots = [];
  IncidentsSummary? _incidentsSummary;

  bool _isLoading = true;
  String? _errorMessage;
  String _selectedBucket = 'hour';

  @override
  void initState() {
    super.initState();
    _loadAllAnalytics();
  }

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _loadAllAnalytics() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final service = ref.read(analyticsServiceProvider);

      final results = await Future.wait([
        service.getTrafficSummary(bucket: _selectedBucket),
        service.getHotspots(limit: 10),
        service.getIncidentsSummary(),
      ]);

      if (mounted) {
        setState(() {
          _buckets = results[0] as List<TrafficSummaryBucket>;
          _hotspots = results[1] as List<CongestionHotspot>;
          _incidentsSummary = results[2] as IncidentsSummary;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoading = false;
          _errorMessage = e is ApiException
              ? e.message
              : 'Failed to retrieve municipal analytics: $e';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Citywide Traffic Analytics'),
        actions: [
          IconButton(
            tooltip: 'Reload Analytics',
            icon: const Icon(Icons.refresh_rounded),
            onPressed: _loadAllAnalytics,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _loadAllAnalytics,
        color: AppTokens.teal,
        backgroundColor: AppTokens.card,
        child: _buildBody(),
      ),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const Center(
        child: LoadingState(
          message: 'Aggregating citywide traffic metrics...',
          subtitle: 'Querying SQL aggregations, hotspots & incident trends',
        ),
      );
    }

    if (_errorMessage != null && _buckets.isEmpty && _hotspots.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(AppTokens.spaceMd),
          child: ErrorState(
            title: 'Analytics Query Failed',
            message: _errorMessage!,
            onRetry: _loadAllAnalytics,
          ),
        ),
      );
    }

    return ListView(
      controller: _scrollController,
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      children: [
        _buildHeaderAndBucketSelector(),
        const SizedBox(height: AppTokens.spaceMd),
        _buildSummaryKpiGrid(),
        const SizedBox(height: AppTokens.spaceMd),
        _buildVolumeTrendChartCard(),
        const SizedBox(height: AppTokens.spaceMd),
        _buildHotspotsCard(),
        const SizedBox(height: AppTokens.spaceMd),
        _buildIncidentsDistributionCard(),
      ],
    );
  }

  Widget _buildHeaderAndBucketSelector() {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: AppTokens.teal.withAlpha(25),
              borderRadius: BorderRadius.circular(8),
            ),
            child: const Icon(Icons.insights_rounded, color: AppTokens.teal, size: 20),
          ),
          const SizedBox(width: AppTokens.spaceSm),
          const Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Telemetry Aggregation',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: AppTokens.textPrimary,
                  ),
                ),
                Text(
                  'Statistical summaries across network sensors',
                  style: TextStyle(color: AppTokens.muted, fontSize: 11),
                ),
              ],
            ),
          ),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(
                value: 'hour',
                label: Text('Hourly'),
              ),
              ButtonSegment(
                value: 'day',
                label: Text('Daily'),
              ),
            ],
            selected: {_selectedBucket},
            onSelectionChanged: (val) {
              if (val.isNotEmpty && val.first != _selectedBucket) {
                setState(() => _selectedBucket = val.first);
                _loadAllAnalytics();
              }
            },
            style: SegmentedButton.styleFrom(
              selectedBackgroundColor: AppTokens.teal.withAlpha(40),
              selectedForegroundColor: AppTokens.teal,
              foregroundColor: AppTokens.muted,
              backgroundColor: AppTokens.surface,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSummaryKpiGrid() {
    double avgSpeed = 0.0;
    double maxCongestion = 0.0;
    double avgVehicles = 0.0;

    if (_buckets.isNotEmpty) {
      double totalSpeed = 0.0;
      int speedSamples = 0;
      double totalV = 0.0;

      for (final b in _buckets) {
        totalV += b.avgVehicleCount;
        if (b.avgSpeed != null) {
          totalSpeed += b.avgSpeed!;
          speedSamples++;
        }
        if (b.avgCongestion > maxCongestion) {
          maxCongestion = b.avgCongestion;
        }
      }

      avgVehicles = totalV / _buckets.length;
      avgSpeed = speedSamples > 0 ? (totalSpeed / speedSamples) : 0.0;
    }

    final activeIncidents = _incidentsSummary?.activeCount ?? 0;
    final totalIncidents = _incidentsSummary?.total ?? 0;

    return LayoutBuilder(
      builder: (context, constraints) {
        final cardWidth = (constraints.maxWidth - AppTokens.spaceSm) / 2;

        return Wrap(
          spacing: AppTokens.spaceSm,
          runSpacing: AppTokens.spaceSm,
          children: [
            SizedBox(
              width: cardWidth,
              child: _buildMetricTile(
                title: 'Active Incidents',
                value: '$activeIncidents of $totalIncidents',
                icon: Icons.warning_amber_rounded,
                color: activeIncidents > 0 ? AppTokens.danger : AppTokens.success,
              ),
            ),
            SizedBox(
              width: cardWidth,
              child: _buildMetricTile(
                title: 'Network Average Speed',
                value: avgSpeed > 0 ? '${avgSpeed.toStringAsFixed(1)} km/h' : '--',
                icon: Icons.speed_rounded,
                color: AppTokens.teal,
              ),
            ),
            SizedBox(
              width: cardWidth,
              child: _buildMetricTile(
                title: 'Peak Congestion Index',
                value: '${maxCongestion.toStringAsFixed(0)}%',
                icon: Icons.compress_rounded,
                color: maxCongestion > 70 ? AppTokens.danger : AppTokens.amber,
              ),
            ),
            SizedBox(
              width: cardWidth,
              child: _buildMetricTile(
                title: 'Avg Flow Density',
                value: '${avgVehicles.toStringAsFixed(0)} veh/bkt',
                icon: Icons.directions_car_rounded,
                color: AppTokens.teal,
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _buildMetricTile({
    required String title,
    required String value,
    required IconData icon,
    required Color color,
  }) {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: color, size: 16),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(color: AppTokens.muted, fontSize: 11),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            value,
            style: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w800,
              color: AppTokens.textPrimary,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildVolumeTrendChartCard() {
    if (_buckets.isEmpty) {
      return const AppCard(
        padding: EdgeInsets.all(AppTokens.spaceLg),
        child: EmptyState(
          icon: Icons.timeline_rounded,
          title: 'No Telemetry Ingestion',
          message: 'No traffic summary buckets available for the active timeframe.',
        ),
      );
    }

    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text(
                'Volume Trend & Congestion Curve',
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                  color: AppTokens.textPrimary,
                ),
              ),
              const Spacer(),
              Row(
                children: [
                  Container(width: 8, height: 8, color: AppTokens.teal),
                  const SizedBox(width: 4),
                  const Text('Volume', style: TextStyle(color: AppTokens.muted, fontSize: 10)),
                  const SizedBox(width: 10),
                  Container(width: 8, height: 8, color: AppTokens.amber),
                  const SizedBox(width: 4),
                  const Text('Congestion %', style: TextStyle(color: AppTokens.muted, fontSize: 10)),
                ],
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceMd),
          SizedBox(
            height: 180,
            width: double.infinity,
            child: CustomPaint(
              painter: _AnalyticsVolumeChartPainter(
                buckets: _buckets,
                isHourly: _selectedBucket == 'hour',
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildHotspotsCard() {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.local_fire_department_rounded, color: AppTokens.danger, size: 20),
              const SizedBox(width: AppTokens.spaceSm),
              const Text(
                'Top Congestion Hotspots',
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: AppTokens.textPrimary,
                ),
              ),
              const Spacer(),
              AppBadge(
                label: '${_hotspots.length} MONITORED',
                color: AppTokens.amber,
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceMd),
          if (_hotspots.isEmpty)
            const Padding(
              padding: EdgeInsets.all(AppTokens.spaceMd),
              child: Text(
                'No congestion hotspots detected.',
                style: TextStyle(color: AppTokens.muted),
              ),
            )
          else
            ListView.separated(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              itemCount: _hotspots.length,
              separatorBuilder: (_, _) => const Divider(
                color: AppTokens.borderDark,
                height: 12,
              ),
              itemBuilder: (context, index) {
                final h = _hotspots[index];
                final congPct = h.avgCongestionLevel.clamp(0.0, 100.0);
                Color congColor = AppTokens.teal;
                if (congPct > 70) {
                  congColor = AppTokens.danger;
                } else if (congPct > 40) {
                  congColor = AppTokens.amber;
                }

                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Container(
                            width: 22,
                            height: 22,
                            alignment: Alignment.center,
                            decoration: BoxDecoration(
                              color: index < 3
                                  ? AppTokens.danger.withAlpha(30)
                                  : AppTokens.surface,
                              shape: BoxShape.circle,
                            ),
                            child: Text(
                              '${index + 1}',
                              style: TextStyle(
                                fontSize: 11,
                                fontWeight: FontWeight.w800,
                                color: index < 3
                                    ? AppTokens.danger
                                    : AppTokens.muted,
                              ),
                            ),
                          ),
                          const SizedBox(width: AppTokens.spaceSm),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  h.name,
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w600,
                                    fontSize: 13,
                                    color: AppTokens.textPrimary,
                                  ),
                                ),
                                Text(
                                  '${h.code} • ${h.recordCount} observations',
                                  style: const TextStyle(
                                    fontSize: 11,
                                    color: AppTokens.muted,
                                  ),
                                ),
                              ],
                            ),
                          ),
                          Text(
                            '${congPct.toStringAsFixed(1)}%',
                            style: TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w700,
                              color: congColor,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 6),
                      ClipRRect(
                        borderRadius: BorderRadius.circular(3),
                        child: LinearProgressIndicator(
                          value: congPct / 100.0,
                          backgroundColor: AppTokens.surface,
                          valueColor: AlwaysStoppedAnimation(congColor),
                          minHeight: 5,
                        ),
                      ),
                    ],
                  ),
                );
              },
            ),
        ],
      ),
    );
  }

  Widget _buildIncidentsDistributionCard() {
    if (_incidentsSummary == null) {
      return const SizedBox.shrink();
    }

    final summary = _incidentsSummary!;

    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.pie_chart_rounded, color: AppTokens.teal, size: 20),
              const SizedBox(width: AppTokens.spaceSm),
              const Text(
                'Incidents Distribution',
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: AppTokens.textPrimary,
                ),
              ),
              const Spacer(),
              Text(
                '${summary.total} Total',
                style: const TextStyle(color: AppTokens.muted, fontSize: 12),
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceMd),
          const Text(
            'By Status Lifecycle:',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: AppTokens.muted,
            ),
          ),
          const SizedBox(height: 6),
          Wrap(
            spacing: AppTokens.spaceSm,
            runSpacing: AppTokens.spaceSm,
            children: summary.byStatus.entries.map((entry) {
              Color col = AppTokens.muted;
              if (entry.key == 'reported') col = AppTokens.danger;
              if (entry.key == 'acknowledged') col = AppTokens.amber;
              if (entry.key == 'resolved') col = AppTokens.success;

              return Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                decoration: BoxDecoration(
                  color: col.withAlpha(25),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: col.withAlpha(70)),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      entry.key.toUpperCase(),
                      style: TextStyle(
                        color: col,
                        fontWeight: FontWeight.w700,
                        fontSize: 11,
                      ),
                    ),
                    const SizedBox(width: 6),
                    Text(
                      '${entry.value}',
                      style: const TextStyle(
                        color: AppTokens.textPrimary,
                        fontWeight: FontWeight.w800,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              );
            }).toList(),
          ),
          const SizedBox(height: AppTokens.spaceMd),
          const Text(
            'By Severity Breakdown:',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: AppTokens.muted,
            ),
          ),
          const SizedBox(height: 6),
          Wrap(
            spacing: AppTokens.spaceSm,
            runSpacing: AppTokens.spaceSm,
            children: summary.bySeverity.entries.map((entry) {
              Color col = AppTokens.muted;
              if (entry.key == 'critical') col = AppTokens.danger;
              if (entry.key == 'high') col = const Color(0xFFFF7A00);
              if (entry.key == 'medium') col = AppTokens.amber;
              if (entry.key == 'low') col = AppTokens.teal;

              return Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                decoration: BoxDecoration(
                  color: AppTokens.surface,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: AppTokens.borderDark),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(width: 6, height: 6, color: col),
                    const SizedBox(width: 6),
                    Text(
                      entry.key.toUpperCase(),
                      style: const TextStyle(color: AppTokens.muted, fontSize: 11),
                    ),
                    const SizedBox(width: 6),
                    Text(
                      '${entry.value}',
                      style: const TextStyle(
                        color: AppTokens.textPrimary,
                        fontWeight: FontWeight.w700,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              );
            }).toList(),
          ),
        ],
      ),
    );
  }
}

/// Custom vector chart painter rendering volume bars and congestion curve.
/// Reuses the custom chart painter design pattern from traffic_screen.
class _AnalyticsVolumeChartPainter extends CustomPainter {
  _AnalyticsVolumeChartPainter({
    required this.buckets,
    required this.isHourly,
  });

  final List<TrafficSummaryBucket> buckets;
  final bool isHourly;

  @override
  void paint(Canvas canvas, Size size) {
    if (buckets.isEmpty) return;

    final n = buckets.length;
    final maxVol = buckets
        .map((b) => b.avgVehicleCount)
        .fold<double>(1.0, (a, b) => a > b ? a : b);

    // Gridlines
    final gridPaint = Paint()
      ..color = AppTokens.borderDark
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

    final linePaint = Paint()
      ..color = AppTokens.amber
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.0;

    final linePath = Path();

    for (int i = 0; i < n; i++) {
      final b = buckets[i];
      final centerX = (i * slotWidth) + (slotWidth / 2);

      // Volume bar
      final normalizedVol = b.avgVehicleCount / maxVol;
      final barHeight = normalizedVol * (size.height - 24);
      final barRect = RRect.fromRectAndRadius(
        Rect.fromLTWH(
          centerX - (barWidth / 2),
          size.height - barHeight - 16,
          barWidth,
          barHeight,
        ),
        const Radius.circular(3),
      );
      canvas.drawRRect(barRect, barPaint);

      // Congestion curve point
      final congY = (size.height - 24) -
          ((b.avgCongestion / 100.0) * (size.height - 30));
      if (i == 0) {
        linePath.moveTo(centerX, congY);
      } else {
        linePath.lineTo(centerX, congY);
      }

      canvas.drawCircle(
        Offset(centerX, congY),
        2.5,
        Paint()..color = AppTokens.amber,
      );
    }

    canvas.drawPath(linePath, linePaint);
  }

  @override
  bool shouldRepaint(covariant _AnalyticsVolumeChartPainter oldDelegate) {
    return oldDelegate.buckets != buckets || oldDelegate.isHourly != isHourly;
  }
}
