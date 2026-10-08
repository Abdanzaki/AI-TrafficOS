import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/hotspot.dart';
import '../models/incident.dart';
import '../models/traffic_summary.dart';
import '../models/user.dart';
import '../providers/realtime_providers.dart';
import '../services/api_client.dart';
import '../services/auth_service.dart';
import '../services/incident_service.dart';
import '../services/junction_service.dart';
import '../services/realtime_protocol.dart';
import '../services/traffic_service.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_card.dart';
import '../widgets/error_state.dart';
import '../widgets/loading_state.dart';
import 'junction_detail_screen.dart';

/// Mobile Operations Dashboard featuring live KPI metrics, congestion hotspots,
/// and incident dispatch queues.
class DashboardScreen extends ConsumerStatefulWidget {
  const DashboardScreen({
    super.key,
    this.onNavigateTab,
  });

  final ValueChanged<int>? onNavigateTab;

  @override
  ConsumerState<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends ConsumerState<DashboardScreen> {
  bool _isLoading = true;
  String? _errorMessage;

  int _totalJunctions = 0;
  int _activeSignals = 0;
  int _activeIncidents = 0;
  double _avgCongestion = 0.0;

  List<CongestionHotspot> _hotspots = [];
  List<Incident> _recentIncidents = [];

  Timer? _wsDebounceTimer;
  bool _isSyncing = false;

  @override
  void initState() {
    super.initState();
    _loadAllDashboardData();
  }

  @override
  void dispose() {
    _wsDebounceTimer?.cancel();
    super.dispose();
  }

  void _scheduleDebouncedRefresh() {
    _wsDebounceTimer?.cancel();
    _wsDebounceTimer = Timer(const Duration(milliseconds: 1500), () {
      if (mounted && !_isSyncing) {
        _loadAllDashboardData(isBackgroundRefresh: true);
      }
    });
  }

  Future<void> _loadAllDashboardData({bool isBackgroundRefresh = false}) async {
    if (_isSyncing) return;
    _isSyncing = true;

    if (!isBackgroundRefresh) {
      setState(() {
        _isLoading = true;
        _errorMessage = null;
      });
    }

    try {
      final trafficService = ref.read(trafficServiceProvider);
      final junctionService = ref.read(junctionServiceProvider);
      final incidentService = ref.read(incidentServiceProvider);

      final junctionsFuture = junctionService.getJunctions(page: 1, perPage: 50);
      final hotspotsFuture = trafficService.getHotspots(limit: 5);
      final incidentsSummaryFuture = trafficService.getIncidentsSummary();
      final recentIncidentsFuture = incidentService.getIncidents(page: 1, perPage: 5);
      final summaryFuture = trafficService.getTrafficSummary(bucket: 'hour');

      final results = await Future.wait([
        junctionsFuture,
        hotspotsFuture,
        incidentsSummaryFuture,
        recentIncidentsFuture,
        summaryFuture,
      ]);

      if (mounted) {
        final junctionsRes = results[0] as dynamic;
        final hotspotsRes = results[1] as List<CongestionHotspot>;
        final incidentsSummaryRes = results[2] as IncidentsSummary;
        final recentIncidentsRes = results[3] as dynamic;
        final summaryList = results[4] as List<TrafficSummaryBucket>;

        int signalsCount = 0;
        if (junctionsRes.items is List) {
          for (final j in junctionsRes.items) {
            signalsCount += (j.signals as List).length;
          }
        }

        double calculatedCongestion = 0.0;
        if (summaryList.isNotEmpty) {
          calculatedCongestion = summaryList.last.avgCongestion;
        } else if (hotspotsRes.isNotEmpty) {
          final total = hotspotsRes.fold<double>(0.0, (acc, h) => acc + h.avgCongestionLevel);
          calculatedCongestion = total / hotspotsRes.length;
        }

        setState(() {
          _totalJunctions = junctionsRes.total ?? 0;
          _activeSignals = signalsCount;
          _activeIncidents = incidentsSummaryRes.activeCount;
          _avgCongestion = calculatedCongestion;
          _hotspots = hotspotsRes;
          _recentIncidents = recentIncidentsRes.items ?? [];
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoading = false;
          _errorMessage = e is ApiException ? e.message : 'Unable to synchronize dashboard: $e';
        });
      }
    } finally {
      _isSyncing = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    // Real-time WebSocket invalidation: debounced on burst events
    for (final topic in const [
      RealtimeTopics.trafficUpdate,
      RealtimeTopics.congestionChange,
      RealtimeTopics.signalChange,
      RealtimeTopics.incidentCreated,
      RealtimeTopics.incidentUpdated,
    ]) {
      ref.listen(realtimeTopicEventProvider(topic), (_, next) {
        if (next.hasValue) {
          _scheduleDebouncedRefresh();
        }
      });
    }

    final user = ref.watch(currentUserProvider);
    final theme = Theme.of(context);

    return RefreshIndicator(
      onRefresh: _loadAllDashboardData,
      color: AppTokens.teal,
      backgroundColor: theme.cardTheme.color ?? AppTokens.cardOf(context),
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(AppTokens.spaceMd),
        children: [
          _buildGreetingSection(context, user, theme),
          const SizedBox(height: AppTokens.spaceMd),
          if (_isLoading)
            _buildLoadingShimmer(theme)
          else if (_errorMessage != null)
            _buildErrorSection(theme)
          else ...[
            _buildKpiSection(theme),
            const SizedBox(height: AppTokens.spaceLg),
            _buildHotspotsSection(theme),
            const SizedBox(height: AppTokens.spaceLg),
            _buildRecentIncidentsSection(theme),
          ],
        ],
      ),
    );
  }

  Widget _buildGreetingSection(BuildContext context, User? user, ThemeData theme) {
    final roleName = user?.roleDisplay ?? 'Operator';
    final roleBadgeColor = user?.roleBadgeColor ?? AppTokens.teal;

    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      'Operational Control Center',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: AppTokens.mutedOf(context),
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(width: AppTokens.spaceSm),
                    AppBadge(
                      label: user?.role.toUpperCase() ?? 'OFFICER',
                      color: roleBadgeColor,
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  'Welcome, ${user?.fullName ?? roleName}',
                  style: theme.textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.w800,
                    color: theme.colorScheme.onSurface,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  'Autonomous municipal traffic orchestration network active',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: AppTokens.mutedOf(context),
                  ),
                ),
              ],
            ),
          ),
          IconButton(
            tooltip: 'Refresh Dashboard',
            icon: const Icon(Icons.refresh_rounded, color: AppTokens.teal),
            onPressed: _loadAllDashboardData,
          ),
        ],
      ),
    );
  }

  Widget _buildLoadingShimmer(ThemeData theme) {
    return const Column(
      children: [
        SizedBox(height: AppTokens.spaceLg),
        LoadingState(
          message: 'Synchronizing real-time telemetry...',
          subtitle: 'Querying junctions, incidents summary, and congestion hotspots',
        ),
      ],
    );
  }

  Widget _buildErrorSection(ThemeData theme) {
    return ErrorState(
      title: 'Dashboard Telemetry Unavailable',
      message: _errorMessage ?? 'Failed to query operational data',
      onRetry: _loadAllDashboardData,
    );
  }

  Widget _buildKpiSection(ThemeData theme) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final cardWidth = (constraints.maxWidth - AppTokens.spaceSm) / 2;

        return Wrap(
          spacing: AppTokens.spaceSm,
          runSpacing: AppTokens.spaceSm,
          children: [
            SizedBox(
              width: cardWidth,
              child: _buildKpiCard(
                title: 'Total Junctions',
                value: '$_totalJunctions',
                subtitle: 'Physical nodes monitored',
                icon: Icons.alt_route_rounded,
                accentColor: AppTokens.teal,
                onTap: () => widget.onNavigateTab?.call(2), // Navigate to Map
              ),
            ),
            SizedBox(
              width: cardWidth,
              child: _buildKpiCard(
                title: 'Active Incidents',
                value: '$_activeIncidents',
                subtitle: _activeIncidents > 0 ? 'Urgent attention required' : 'All clear',
                icon: Icons.warning_amber_rounded,
                accentColor: _activeIncidents > 0 ? AppTokens.danger : AppTokens.success,
                onTap: () => widget.onNavigateTab?.call(3), // Navigate to Incidents
              ),
            ),
            SizedBox(
              width: cardWidth,
              child: _buildKpiCard(
                title: 'Avg Congestion',
                value: '${_avgCongestion.toStringAsFixed(1)}%',
                subtitle: _avgCongestion > 65 ? 'Elevated city corridor flow' : 'Fluid city circulation',
                icon: Icons.speed_rounded,
                accentColor: _avgCongestion > 65 ? AppTokens.amber : AppTokens.teal,
                onTap: () => widget.onNavigateTab?.call(1), // Navigate to Traffic
              ),
            ),
            SizedBox(
              width: cardWidth,
              child: _buildKpiCard(
                title: 'Signals Online',
                value: '$_activeSignals',
                subtitle: 'Hardware units synced',
                icon: Icons.traffic_rounded,
                accentColor: AppTokens.teal,
                onTap: () => widget.onNavigateTab?.call(2),
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _buildKpiCard({
    required String title,
    required String value,
    required String subtitle,
    required IconData icon,
    required Color accentColor,
    VoidCallback? onTap,
  }) {
    return Semantics(
      label: '$title KPI: $value. $subtitle',
      button: onTap != null,
      child: AppCard(
        padding: const EdgeInsets.all(AppTokens.spaceMd),
        onTap: onTap,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(6),
                  decoration: BoxDecoration(
                    color: accentColor.withAlpha(25),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Icon(icon, color: accentColor, size: 18),
                ),
                const Spacer(),
                ExcludeSemantics(
                  child: Icon(Icons.arrow_forward_ios_rounded,
                      size: 12, color: AppTokens.mutedOf(context)),
                ),
              ],
            ),
          const SizedBox(height: AppTokens.spaceSm),
          Text(
            value,
            style: TextStyle(
              fontSize: 22,
              fontWeight: FontWeight.w800,
              color: Theme.of(context).colorScheme.onSurface,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            title,
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: Theme.of(context).colorScheme.onSurface,
            ),
          ),
          Text(
            subtitle,
            style: TextStyle(
              fontSize: 10,
              color: AppTokens.mutedOf(context),
            ),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    ),
  );
}

  Widget _buildHotspotsSection(ThemeData theme) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.local_fire_department_rounded, color: AppTokens.amber, size: 20),
            const SizedBox(width: AppTokens.spaceSm),
            Text(
              'Congestion Hotspots',
              style: theme.textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.w700,
                color: theme.colorScheme.onSurface,
              ),
            ),
            const Spacer(),
            TextButton(
              onPressed: () => widget.onNavigateTab?.call(1),
              child: const Text('View All', style: TextStyle(color: AppTokens.teal)),
            ),
          ],
        ),
        const SizedBox(height: AppTokens.spaceSm),
        if (_hotspots.isEmpty)
          AppCard(
            padding: const EdgeInsets.all(AppTokens.spaceMd),
            child: Center(
              child: Text(
                'No congestion hotspots detected in current time window',
                style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 13),
              ),
            ),
          )
        else
          ..._hotspots.map((h) => _buildHotspotCard(h)),
      ],
    );
  }

  Widget _buildHotspotCard(CongestionHotspot hotspot) {
    Color levelColor = AppTokens.teal;
    if (hotspot.avgCongestionLevel >= 75) {
      levelColor = AppTokens.danger;
    } else if (hotspot.avgCongestionLevel >= 50) {
      levelColor = AppTokens.amber;
    }

    return Semantics(
      label:
          'Congestion hotspot: ${hotspot.name}, ${hotspot.avgCongestionLevel.toStringAsFixed(1)}% congestion',
      button: true,
      child: Padding(
        padding: const EdgeInsets.only(bottom: AppTokens.spaceSm),
        child: AppCard(
          padding: const EdgeInsets.all(AppTokens.spaceMd),
          onTap: () {
            Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => JunctionDetailScreen(
                  junctionId: hotspot.intersectionId,
                ),
              ),
            );
          },
          child: Row(
          children: [
            Container(
              width: 38,
              height: 38,
              decoration: BoxDecoration(
                color: levelColor.withAlpha(25),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: levelColor.withAlpha(80)),
              ),
              child: Center(
                child: Text(
                  '${hotspot.avgCongestionLevel.toStringAsFixed(0)}%',
                  style: TextStyle(
                    color: levelColor,
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ),
            const SizedBox(width: AppTokens.spaceMd),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    hotspot.name,
                    style: TextStyle(
                      fontWeight: FontWeight.w700,
                      color: Theme.of(context).colorScheme.onSurface,
                      fontSize: 14,
                    ),
                  ),
                  Text(
                    'Code: ${hotspot.code} • ${hotspot.recordCount} observations',
                    style: TextStyle(
                      color: AppTokens.mutedOf(context),
                      fontSize: 11,
                    ),
                  ),
                ],
              ),
            ),
            Icon(Icons.chevron_right_rounded, color: AppTokens.mutedOf(context)),
          ],
        ),
      ),
    ),
  );
}

  Widget _buildRecentIncidentsSection(ThemeData theme) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.notification_important_rounded, color: AppTokens.danger, size: 20),
            const SizedBox(width: AppTokens.spaceSm),
            Text(
              'Recent Incidents Queue',
              style: theme.textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.w700,
                color: theme.colorScheme.onSurface,
              ),
            ),
            const Spacer(),
            TextButton(
              onPressed: () => widget.onNavigateTab?.call(3),
              child: const Text('All Incidents', style: TextStyle(color: AppTokens.teal)),
            ),
          ],
        ),
        const SizedBox(height: AppTokens.spaceSm),
        if (_recentIncidents.isEmpty)
          AppCard(
            padding: const EdgeInsets.all(AppTokens.spaceMd),
            child: Center(
              child: Text(
                'No active safety anomalies or traffic incidents reported',
                style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 13),
              ),
            ),
          )
        else
          ..._recentIncidents.map((inc) => _buildIncidentCard(inc)),
      ],
    );
  }

  Widget _buildIncidentCard(Incident incident) {
    return Semantics(
      label:
          'Incident: ${incident.title}, severity ${incident.severity}, status ${incident.status}',
      button: true,
      child: Padding(
        padding: const EdgeInsets.only(bottom: AppTokens.spaceSm),
        child: AppCard(
          padding: const EdgeInsets.all(AppTokens.spaceMd),
          onTap: () {
            widget.onNavigateTab?.call(3);
          },
          child: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: incident.severityColor.withAlpha(25),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Icon(
                Icons.warning_amber_rounded,
                color: incident.severityColor,
                size: 20,
              ),
            ),
            const SizedBox(width: AppTokens.spaceMd),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    incident.description ?? 'Traffic incident reported',
                    style: TextStyle(
                      fontWeight: FontWeight.w600,
                      color: Theme.of(context).colorScheme.onSurface,
                      fontSize: 13,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: 2),
                  Text(
                    'Severity: ${incident.severity.toUpperCase()} • Status: ${incident.status.toUpperCase()}',
                    style: TextStyle(
                      color: incident.severityColor,
                      fontSize: 11,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ],
              ),
            ),
            AppBadge(
              label: incident.status.toUpperCase(),
              color: incident.statusColor,
            ),
          ],
        ),
      ),
    ),
  );
}
}
