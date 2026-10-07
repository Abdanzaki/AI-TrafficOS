import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/incident.dart';
import '../models/junction.dart';
import '../models/traffic_record.dart';
import '../models/user.dart';
import '../services/api_client.dart';
import '../services/auth_service.dart';
import '../services/incident_service.dart';
import '../services/junction_service.dart';
import '../services/traffic_service.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_card.dart';
import '../widgets/empty_state.dart';
import '../widgets/error_state.dart';
import '../widgets/loading_state.dart';

/// Screen detailing junction signals, phases, lanes, telemetry, and linked incidents.
class JunctionDetailScreen extends ConsumerStatefulWidget {
  const JunctionDetailScreen({
    super.key,
    required this.junctionId,
    this.initialJunction,
  });

  final int junctionId;
  final Junction? initialJunction;

  @override
  ConsumerState<JunctionDetailScreen> createState() =>
      _JunctionDetailScreenState();
}

class _JunctionDetailScreenState extends ConsumerState<JunctionDetailScreen> {
  Junction? _junction;
  List<TrafficRecord> _recentRecords = [];
  List<Incident> _linkedIncidents = [];
  bool _isLoading = true;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _junction = widget.initialJunction;
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final junctionService = ref.read(junctionServiceProvider);
      final trafficService = ref.read(trafficServiceProvider);
      final incidentService = ref.read(incidentServiceProvider);

      final junctionFuture = junctionService.getJunction(widget.junctionId);
      final recordsFuture = trafficService.getTrafficRecords(
        intersectionId: widget.junctionId,
        perPage: 15,
      );
      final incidentsFuture = incidentService.getIncidents(
        intersectionId: widget.junctionId,
        perPage: 10,
      );

      final results = await Future.wait([
        junctionFuture,
        recordsFuture,
        incidentsFuture,
      ]);

      if (mounted) {
        setState(() {
          _junction = results[0] as Junction;
          _recentRecords = (results[1] as PaginatedTrafficRecords).items;
          _linkedIncidents = (results[2] as PaginatedIncidents).items;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoading = false;
          _errorMessage = e is ApiException ? e.message : 'Failed to load junction details: $e';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(currentUserProvider);
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: Text(
          _junction?.name ?? 'Junction #${widget.junctionId}',
          overflow: TextOverflow.ellipsis,
        ),
        actions: [
          IconButton(
            tooltip: 'Refresh Telemetry',
            icon: const Icon(Icons.refresh_rounded),
            onPressed: _loadData,
          ),
        ],
      ),
      body: _buildBody(context, user, theme),
    );
  }

  Widget _buildBody(BuildContext context, User? user, ThemeData theme) {
    if (_isLoading && _junction == null) {
      return const LoadingState(
        message: 'Loading junction architecture...',
        subtitle: 'Retrieving hardware signals, lane layout, and sensor streams',
      );
    }

    if (_errorMessage != null && _junction == null) {
      return ErrorState(
        title: 'Junction Offline or Unavailable',
        message: _errorMessage!,
        onRetry: _loadData,
      );
    }

    final junction = _junction;
    if (junction == null) {
      return const EmptyState(
        icon: Icons.traffic_rounded,
        title: 'Junction Not Found',
        message: 'The requested municipal junction node does not exist.',
      );
    }

    return RefreshIndicator(
      onRefresh: _loadData,
      color: AppTokens.teal,
      backgroundColor: AppTokens.card,
      child: ListView(
        padding: const EdgeInsets.all(AppTokens.spaceMd),
        children: [
          _buildRoleNotice(user),
          _buildHeaderCard(junction, theme),
          const SizedBox(height: AppTokens.spaceMd),
          _buildTrafficTrendsCard(theme),
          const SizedBox(height: AppTokens.spaceMd),
          _buildSignalsSection(junction, theme),
          const SizedBox(height: AppTokens.spaceMd),
          _buildLanesSection(junction, theme),
          const SizedBox(height: AppTokens.spaceMd),
          _buildIncidentsSection(theme),
        ],
      ),
    );
  }

  Widget _buildRoleNotice(User? user) {
    if (user?.isAnalyst ?? true) {
      return Container(
        margin: const EdgeInsets.only(bottom: AppTokens.spaceMd),
        padding: const EdgeInsets.all(AppTokens.spaceMd),
        decoration: BoxDecoration(
          color: AppTokens.amber.withAlpha(20),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppTokens.amber.withAlpha(70)),
        ),
        child: const Row(
          children: [
            Icon(Icons.lock_outline_rounded, color: AppTokens.amber, size: 22),
            SizedBox(width: AppTokens.spaceSm),
            Expanded(
              child: Text(
                'Analyst Role: Read-only telemetry access. Signal phase overrides and timing modifications require Traffic Officer or Admin privileges.',
                style: TextStyle(
                  color: AppTokens.amber,
                  fontSize: 12,
                  fontWeight: FontWeight.w500,
                  height: 1.3,
                ),
              ),
            ),
          ],
        ),
      );
    }
    return const SizedBox.shrink();
  }

  Widget _buildHeaderCard(Junction junction, ThemeData theme) {
    Color statusColor = AppTokens.teal;
    if (junction.status.toLowerCase() == 'maintenance') {
      statusColor = AppTokens.amber;
    } else if (junction.status.toLowerCase() == 'inactive') {
      statusColor = AppTokens.danger;
    }

    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      junction.name,
                      style: theme.textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.w800,
                        color: AppTokens.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Operational Code: ${junction.code}',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: AppTokens.muted,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              ),
              AppBadge(
                label: junction.status.toUpperCase(),
                color: statusColor,
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceMd),
          Wrap(
            spacing: AppTokens.spaceSm,
            runSpacing: AppTokens.spaceSm,
            children: [
              if (junction.city != null)
                _buildInfoPill(Icons.location_city_rounded, junction.city!),
              if (junction.zone != null)
                _buildInfoPill(Icons.map_rounded, 'Zone: ${junction.zone!}'),
              if (junction.latitude != null && junction.longitude != null)
                _buildInfoPill(
                  Icons.gps_fixed_rounded,
                  '${junction.latitude!.toStringAsFixed(4)}, ${junction.longitude!.toStringAsFixed(4)}',
                ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildInfoPill(IconData icon, String label) {
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
          Icon(icon, size: 14, color: AppTokens.teal),
          const SizedBox(width: 6),
          Text(
            label,
            style: const TextStyle(
              fontSize: 12,
              color: AppTokens.textPrimary,
              fontWeight: FontWeight.w500,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTrafficTrendsCard(ThemeData theme) {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.analytics_rounded, color: AppTokens.teal, size: 20),
              const SizedBox(width: AppTokens.spaceSm),
              Text(
                'Recent Telemetry Observations',
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                  color: AppTokens.textPrimary,
                ),
              ),
              const Spacer(),
              Text(
                '${_recentRecords.length} samples',
                style: const TextStyle(color: AppTokens.muted, fontSize: 12),
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceMd),
          if (_recentRecords.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: AppTokens.spaceMd),
              child: Center(
                child: Text(
                  'No sensor records ingested yet for this junction',
                  style: TextStyle(color: AppTokens.muted, fontSize: 13),
                ),
              ),
            )
          else ...[
            SizedBox(
              height: 120,
              width: double.infinity,
              child: CustomPaint(
                painter: MiniTrafficChartPainter(records: _recentRecords),
              ),
            ),
            const SizedBox(height: AppTokens.spaceSm),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                _buildStatLabel('Latest Count', '${_recentRecords.first.vehicleCount} veh'),
                _buildStatLabel(
                  'Avg Speed',
                  _recentRecords.first.avgSpeedKmh != null
                      ? '${_recentRecords.first.avgSpeedKmh!.toStringAsFixed(1)} km/h'
                      : '--',
                ),
                _buildStatLabel(
                  'Congestion',
                  '${_recentRecords.first.congestionLevel}%',
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildStatLabel(String title, String val) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: const TextStyle(color: AppTokens.muted, fontSize: 11)),
        Text(
          val,
          style: const TextStyle(
            color: AppTokens.textPrimary,
            fontWeight: FontWeight.w700,
            fontSize: 14,
          ),
        ),
      ],
    );
  }

  Widget _buildSignalsSection(Junction junction, ThemeData theme) {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.traffic_rounded, color: AppTokens.teal, size: 20),
              const SizedBox(width: AppTokens.spaceSm),
              Text(
                'Hardware Signals & Phases',
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                  color: AppTokens.textPrimary,
                ),
              ),
              const Spacer(),
              AppBadge(
                label: '${junction.signals.length} Controllers',
                color: AppTokens.teal,
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceMd),
          if (junction.signals.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: AppTokens.spaceMd),
              child: Center(
                child: Text(
                  'No physical signal controllers registered',
                  style: TextStyle(color: AppTokens.muted, fontSize: 13),
                ),
              ),
            )
          else
            ...junction.signals.map((sig) => _buildSignalItem(sig)),
        ],
      ),
    );
  }

  Widget _buildSignalItem(SignalSummary sig) {
    Color stateColor = AppTokens.muted;
    if (sig.observedState != null) {
      switch (sig.observedState!.toLowerCase()) {
        case 'green':
          stateColor = AppTokens.success;
          break;
        case 'yellow':
          stateColor = AppTokens.amber;
          break;
        case 'red':
          stateColor = AppTokens.danger;
          break;
      }
    }

    return Container(
      margin: const EdgeInsets.only(bottom: AppTokens.spaceSm),
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      decoration: BoxDecoration(
        color: AppTokens.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTokens.borderDark),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 12,
                height: 12,
                decoration: BoxDecoration(
                  color: stateColor,
                  shape: BoxShape.circle,
                  boxShadow: [
                    BoxShadow(
                      color: stateColor.withAlpha(100),
                      blurRadius: 6,
                      spreadRadius: 1,
                    ),
                  ],
                ),
              ),
              const SizedBox(width: AppTokens.spaceSm),
              Text(
                'Signal ${sig.code}',
                style: const TextStyle(
                  fontWeight: FontWeight.w700,
                  color: AppTokens.textPrimary,
                ),
              ),
              const Spacer(),
              AppBadge(
                label: sig.status.toUpperCase(),
                color: sig.status.toLowerCase() == 'active'
                    ? AppTokens.teal
                    : AppTokens.amber,
              ),
            ],
          ),
          if (sig.observedState != null) ...[
            const SizedBox(height: 6),
            Text(
              'CV Observation: ${sig.observedState!.toUpperCase()} (${((sig.observedConfidence ?? 1.0) * 100).toStringAsFixed(0)}% confidence)',
              style: TextStyle(
                color: stateColor,
                fontSize: 12,
                fontWeight: FontWeight.w500,
              ),
            ),
          ],
          if (sig.phases.isNotEmpty) ...[
            const SizedBox(height: AppTokens.spaceSm),
            const Divider(color: AppTokens.borderDark, height: 1),
            const SizedBox(height: AppTokens.spaceSm),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: sig.phases.map((p) {
                Color phaseColor = AppTokens.muted;
                if (p.state.toLowerCase() == 'green') phaseColor = AppTokens.success;
                if (p.state.toLowerCase() == 'yellow') phaseColor = AppTokens.amber;
                if (p.state.toLowerCase() == 'red') phaseColor = AppTokens.danger;

                return Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: phaseColor.withAlpha(25),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: phaseColor.withAlpha(80)),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: 6,
                        height: 6,
                        decoration: BoxDecoration(
                          color: phaseColor,
                          shape: BoxShape.circle,
                        ),
                      ),
                      const SizedBox(width: 4),
                      Text(
                        '#${p.phaseOrder} ${p.name} (${p.durationSeconds}s)',
                        style: TextStyle(
                          color: phaseColor,
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                );
              }).toList(),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildLanesSection(Junction junction, ThemeData theme) {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.alt_route_rounded, color: AppTokens.teal, size: 20),
              const SizedBox(width: AppTokens.spaceSm),
              Text(
                'Lanes & Directional Geometry',
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                  color: AppTokens.textPrimary,
                ),
              ),
              const Spacer(),
              Text(
                '${junction.lanes.length} lanes',
                style: const TextStyle(color: AppTokens.muted, fontSize: 12),
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceMd),
          if (junction.lanes.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: AppTokens.spaceMd),
              child: Center(
                child: Text(
                  'No physical lanes mapped to this intersection',
                  style: TextStyle(color: AppTokens.muted, fontSize: 13),
                ),
              ),
            )
          else
            ...junction.lanes.map((lane) {
              return Container(
                margin: const EdgeInsets.only(bottom: AppTokens.spaceSm),
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                decoration: BoxDecoration(
                  color: AppTokens.surface,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: AppTokens.borderDark),
                ),
                child: Row(
                  children: [
                    Container(
                      width: 28,
                      height: 28,
                      decoration: BoxDecoration(
                        color: AppTokens.teal.withAlpha(30),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Center(
                        child: Text(
                          '${lane.laneNumber}',
                          style: const TextStyle(
                            fontWeight: FontWeight.w700,
                            color: AppTokens.teal,
                            fontSize: 13,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(width: AppTokens.spaceSm),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            lane.direction.toUpperCase(),
                            style: const TextStyle(
                              fontWeight: FontWeight.w600,
                              color: AppTokens.textPrimary,
                              fontSize: 13,
                            ),
                          ),
                          Text(
                            'Type: ${lane.laneType}',
                            style: const TextStyle(
                              color: AppTokens.muted,
                              fontSize: 11,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              );
            }),
        ],
      ),
    );
  }

  Widget _buildIncidentsSection(ThemeData theme) {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.warning_amber_rounded, color: AppTokens.amber, size: 20),
              const SizedBox(width: AppTokens.spaceSm),
              Text(
                'Linked Safety Incidents',
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                  color: AppTokens.textPrimary,
                ),
              ),
              const Spacer(),
              AppBadge(
                label: '${_linkedIncidents.length}',
                color: _linkedIncidents.isEmpty ? AppTokens.success : AppTokens.amber,
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceMd),
          if (_linkedIncidents.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: AppTokens.spaceMd),
              child: Center(
                child: Text(
                  'No active incidents linked to this junction node',
                  style: TextStyle(color: AppTokens.muted, fontSize: 13),
                ),
              ),
            )
          else
            ..._linkedIncidents.map((inc) {
              return Container(
                margin: const EdgeInsets.only(bottom: AppTokens.spaceSm),
                padding: const EdgeInsets.all(AppTokens.spaceMd),
                decoration: BoxDecoration(
                  color: AppTokens.surface,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: AppTokens.borderDark),
                ),
                child: Row(
                  children: [
                    Icon(
                      Icons.warning_rounded,
                      color: inc.severityColor,
                      size: 20,
                    ),
                    const SizedBox(width: AppTokens.spaceSm),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            inc.description ?? 'Unspecified traffic incident',
                            style: const TextStyle(
                              fontWeight: FontWeight.w600,
                              color: AppTokens.textPrimary,
                              fontSize: 13,
                            ),
                          ),
                          Text(
                            'Severity: ${inc.severity.toUpperCase()} • Status: ${inc.status.toUpperCase()}',
                            style: TextStyle(
                              color: inc.severityColor,
                              fontSize: 11,
                              fontWeight: FontWeight.w500,
                            ),
                          ),
                        ],
                      ),
                    ),
                    AppBadge(
                      label: inc.status.toUpperCase(),
                      color: inc.statusColor,
                    ),
                  ],
                ),
              );
            }),
        ],
      ),
    );
  }
}

/// Lightweight mini-chart custom painter for recent traffic records.
class MiniTrafficChartPainter extends CustomPainter {
  MiniTrafficChartPainter({required this.records});

  final List<TrafficRecord> records;

  @override
  void paint(Canvas canvas, Size size) {
    if (records.isEmpty) return;

    final sorted = records.reversed.toList();
    final maxCount = sorted.map((r) => r.vehicleCount).fold<int>(1, (a, b) => a > b ? a : b);

    final linePaint = Paint()
      ..color = AppTokens.teal
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.0;

    final fillPaint = Paint()
      ..shader = LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [
          AppTokens.teal.withAlpha(80),
          AppTokens.teal.withAlpha(0),
        ],
      ).createShader(Rect.fromLTWH(0, 0, size.width, size.height));

    final path = Path();
    final fillPath = Path();

    final stepX = size.width / (sorted.length > 1 ? sorted.length - 1 : 1);

    for (int i = 0; i < sorted.length; i++) {
      final x = i * stepX;
      final normalizedY = sorted[i].vehicleCount / maxCount;
      final y = size.height - (normalizedY * (size.height - 12)) - 6;

      if (i == 0) {
        path.moveTo(x, y);
        fillPath.moveTo(x, size.height);
        fillPath.lineTo(x, y);
      } else {
        path.lineTo(x, y);
        fillPath.lineTo(x, y);
      }

      // Draw point
      canvas.drawCircle(Offset(x, y), 3.0, Paint()..color = AppTokens.teal);
    }

    fillPath.lineTo(size.width, size.height);
    fillPath.close();

    canvas.drawPath(fillPath, fillPaint);
    canvas.drawPath(path, linePaint);
  }

  @override
  bool shouldRepaint(covariant MiniTrafficChartPainter oldDelegate) {
    return oldDelegate.records != records;
  }
}
