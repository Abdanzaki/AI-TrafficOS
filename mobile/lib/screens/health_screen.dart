import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/app_config.dart';
import '../services/api_client.dart';
import '../services/auth_service.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_card.dart';
import '../widgets/empty_state.dart';
import '../widgets/error_state.dart';
import '../widgets/loading_state.dart';

/// Live diagnostic representation of system connectivity and operational components.
class HealthReport {
  const HealthReport({
    required this.backendStatus,
    required this.backendVersion,
    required this.backendLatencyMs,
    required this.isReachable,
    required this.aiForecastingStatus,
    required this.aiForecastingDetails,
    required this.aiControlStatus,
    required this.aiControlDetails,
    required this.checkedAt,
    this.backendError,
  });

  final String backendStatus;
  final String backendVersion;
  final int? backendLatencyMs;
  final bool isReachable;
  final String aiForecastingStatus;
  final String? aiForecastingDetails;
  final String aiControlStatus;
  final String? aiControlDetails;
  final DateTime checkedAt;
  final String? backendError;
}

/// Screen presenting real-time system health, API reachability, and AI subsystem status.
class HealthScreen extends ConsumerStatefulWidget {
  const HealthScreen({super.key});

  @override
  ConsumerState<HealthScreen> createState() => _HealthScreenState();
}

class _HealthScreenState extends ConsumerState<HealthScreen> {
  HealthReport? _report;
  bool _isLoading = true;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _checkHealth();
  }

  Future<void> _checkHealth() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    final apiClient = ref.read(apiClientProvider);

    // 1. Backend /health & latency measurement
    String backendStatus = 'unknown';
    String backendVersion = 'unknown';
    int? latencyMs;
    String? backendError;
    bool isReachable = false;

    final sw = Stopwatch()..start();
    try {
      final healthRes = await apiClient.getHealth();
      sw.stop();
      latencyMs = sw.elapsedMilliseconds;

      if (healthRes.isSuccess && healthRes.dataOrNull != null) {
        final data = healthRes.dataOrNull!;
        backendStatus = data.status;
        backendVersion = data.version;
        isReachable = true;
      } else {
        backendStatus = 'unreachable';
        backendError = healthRes.errorOrNull ?? 'Health check request failed';
        isReachable = false;
      }
    } catch (e) {
      sw.stop();
      backendStatus = 'offline';
      backendError = e.toString();
      isReachable = false;
    }

    // 2. AI Forecasting status from GET /forecasting/models/latest
    String aiForecastingStatus = 'unknown';
    String? aiForecastingDetails;
    try {
      final dynamic foreRes =
          await apiClient.get('/forecasting/models/latest');
      if (foreRes is Map<String, dynamic>) {
        final ver = foreRes['version']?.toString() ?? 'registered';
        aiForecastingStatus = 'active';
        aiForecastingDetails = 'Model v$ver';
      } else {
        aiForecastingStatus = 'unknown';
      }
    } on ApiException catch (e) {
      if (e.statusCode == 404) {
        aiForecastingStatus = 'unregistered';
        aiForecastingDetails = 'No model trained';
      } else if (e.isForbidden) {
        aiForecastingStatus = 'restricted';
        aiForecastingDetails = 'Admin permission required';
      } else {
        aiForecastingStatus = 'unknown';
        aiForecastingDetails = e.message;
      }
    } catch (_) {
      aiForecastingStatus = 'unknown';
    }

    // 3. AI Control status from GET /control/decisions?per_page=1
    String aiControlStatus = 'unknown';
    String? aiControlDetails;
    try {
      final dynamic ctrlRes = await apiClient.get(
        '/control/decisions',
        queryParameters: {'per_page': 1},
      );
      if (ctrlRes is Map<String, dynamic>) {
        aiControlStatus = 'active';
        final total = ctrlRes['total'];
        aiControlDetails = total != null ? '$total policy decisions logged' : 'Advisory active';
      } else {
        aiControlStatus = 'unknown';
      }
    } on ApiException catch (e) {
      if (e.isForbidden) {
        aiControlStatus = 'restricted';
        aiControlDetails = 'Unauthorized access';
      } else {
        aiControlStatus = 'unknown';
        aiControlDetails = e.message;
      }
    } catch (_) {
      aiControlStatus = 'unknown';
    }

    if (mounted) {
      setState(() {
        _report = HealthReport(
          backendStatus: backendStatus,
          backendVersion: backendVersion,
          backendLatencyMs: latencyMs,
          isReachable: isReachable,
          aiForecastingStatus: aiForecastingStatus,
          aiForecastingDetails: aiForecastingDetails,
          aiControlStatus: aiControlStatus,
          aiControlDetails: aiControlDetails,
          checkedAt: DateTime.now(),
          backendError: backendError,
        );
        _isLoading = false;
      });
    }
  }

  Color _getStatusColor(String status) {
    switch (status.toLowerCase()) {
      case 'ok':
      case 'healthy':
      case 'active':
        return AppTokens.success;
      case 'degraded':
      case 'unregistered':
        return AppTokens.amber;
      case 'offline':
      case 'unreachable':
      case 'error':
        return AppTokens.danger;
      case 'restricted':
        return const Color(0xFFA855F7);
      case 'unknown':
      default:
        return AppTokens.muted;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('System Health'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Run Health Diagnostics',
            onPressed: _checkHealth,
          ),
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const LoadingState(
        message: 'Running system connectivity checks...',
        subtitle: 'Probing backend API, latency, and AI services',
      );
    }

    if (_errorMessage != null) {
      return ErrorState(
        message: _errorMessage!,
        onRetry: _checkHealth,
      );
    }

    final report = _report;
    if (report == null) {
      return const EmptyState(
        icon: Icons.favorite_border_rounded,
        title: 'No Health Data',
        message: 'Diagnostics have not been executed yet.',
      );
    }

    final user = ref.watch(currentUserProvider);

    return RefreshIndicator(
      onRefresh: _checkHealth,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(AppTokens.spaceMd),
        children: [
          _buildBackendCard(report),
          const SizedBox(height: AppTokens.spaceMd),
          _buildConnectivityCard(report),
          const SizedBox(height: AppTokens.spaceMd),
          _buildAiServicesCard(report),
          const SizedBox(height: AppTokens.spaceMd),
          _buildAppInfoCard(user, report),
        ],
      ),
    );
  }

  Widget _buildBackendCard(HealthReport report) {
    final statusColor = _getStatusColor(report.backendStatus);

    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(
                  color: statusColor.withAlpha(25),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: statusColor.withAlpha(70)),
                ),
                child: Icon(
                  Icons.dns_rounded,
                  color: statusColor,
                  size: 22,
                ),
              ),
              const SizedBox(width: AppTokens.spaceMd),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'FastAPI Core Backend',
                      style: TextStyle(
                        color: AppTokens.textPrimary,
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    Text(
                      'Endpoint: /health',
                      style: TextStyle(
                        color: AppTokens.muted,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              ),
              AppBadge(
                label: report.backendStatus.toUpperCase(),
                color: statusColor,
              ),
            ],
          ),
          const Divider(height: 24, color: AppTokens.borderDark),
          Row(
            children: [
              Expanded(
                child: _buildMetricTile(
                  label: 'Version',
                  value: report.backendVersion,
                  icon: Icons.tag_rounded,
                ),
              ),
              Expanded(
                child: _buildMetricTile(
                  label: 'Latency',
                  value: report.backendLatencyMs != null
                      ? '${report.backendLatencyMs} ms'
                      : 'Unavailable',
                  icon: Icons.speed_rounded,
                  color: (report.backendLatencyMs ?? 999) < 200
                      ? AppTokens.success
                      : AppTokens.amber,
                ),
              ),
            ],
          ),
          if (report.backendError != null) ...[
            const SizedBox(height: AppTokens.spaceSm),
            Container(
              padding: const EdgeInsets.all(AppTokens.spaceSm),
              decoration: BoxDecoration(
                color: AppTokens.danger.withAlpha(20),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppTokens.danger.withAlpha(60)),
              ),
              child: Row(
                children: [
                  const Icon(
                    Icons.error_outline_rounded,
                    color: AppTokens.danger,
                    size: 16,
                  ),
                  const SizedBox(width: AppTokens.spaceXs),
                  Expanded(
                    child: Text(
                      report.backendError!,
                      style: const TextStyle(
                        color: AppTokens.danger,
                        fontSize: 11,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildConnectivityCard(HealthReport report) {
    final connectedColor =
        report.isReachable ? AppTokens.success : AppTokens.danger;

    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Row(
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: connectedColor.withAlpha(25),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: connectedColor.withAlpha(70)),
            ),
            child: Icon(
              report.isReachable
                  ? Icons.wifi_rounded
                  : Icons.wifi_off_rounded,
              color: connectedColor,
              size: 22,
            ),
          ),
          const SizedBox(width: AppTokens.spaceMd),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'API Network Connectivity',
                  style: TextStyle(
                    color: AppTokens.textPrimary,
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                Text(
                  report.isReachable
                      ? 'Connected to municipal control network'
                      : 'Network unreachable or service offline',
                  style: const TextStyle(
                    color: AppTokens.muted,
                    fontSize: 12,
                  ),
                ),
              ],
            ),
          ),
          AppBadge(
            label: report.isReachable ? 'ONLINE' : 'OFFLINE',
            color: connectedColor,
          ),
        ],
      ),
    );
  }

  Widget _buildAiServicesCard(HealthReport report) {
    final forecastingColor = _getStatusColor(report.aiForecastingStatus);
    final controlColor = _getStatusColor(report.aiControlStatus);

    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.psychology_rounded, color: AppTokens.teal, size: 20),
              SizedBox(width: AppTokens.spaceSm),
              Text(
                'AI Subsystems Diagnostics',
                style: TextStyle(
                  color: AppTokens.textPrimary,
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceSm),
          const Text(
            'Derived from registered models and live control decision logs.',
            style: TextStyle(color: AppTokens.muted, fontSize: 12),
          ),
          const Divider(height: 24, color: AppTokens.borderDark),
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: CircleAvatar(
              radius: 18,
              backgroundColor: forecastingColor.withAlpha(25),
              child: Icon(Icons.timeline_rounded, color: forecastingColor, size: 18),
            ),
            title: const Text(
              'Traffic Forecasting ML',
              style: TextStyle(
                color: AppTokens.textPrimary,
                fontSize: 13,
                fontWeight: FontWeight.w600,
              ),
            ),
            subtitle: Text(
              report.aiForecastingDetails ?? 'Endpoint: /forecasting/models/latest',
              style: const TextStyle(color: AppTokens.muted, fontSize: 11),
            ),
            trailing: AppBadge(
              label: report.aiForecastingStatus.toUpperCase(),
              color: forecastingColor,
            ),
          ),
          const Divider(height: 16, color: AppTokens.borderDark),
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: CircleAvatar(
              radius: 18,
              backgroundColor: controlColor.withAlpha(25),
              child: Icon(Icons.tune_rounded, color: controlColor, size: 18),
            ),
            title: const Text(
              'Supervisory Control Engine',
              style: TextStyle(
                color: AppTokens.textPrimary,
                fontSize: 13,
                fontWeight: FontWeight.w600,
              ),
            ),
            subtitle: Text(
              report.aiControlDetails ?? 'Endpoint: /control/decisions',
              style: const TextStyle(color: AppTokens.muted, fontSize: 11),
            ),
            trailing: AppBadge(
              label: report.aiControlStatus.toUpperCase(),
              color: controlColor,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAppInfoCard(dynamic user, HealthReport report) {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.info_outline_rounded, color: AppTokens.muted, size: 20),
              SizedBox(width: AppTokens.spaceSm),
              Text(
                'Application Metadata',
                style: TextStyle(
                  color: AppTokens.textPrimary,
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          const Divider(height: 20, color: AppTokens.borderDark),
          _buildInfoRow('Application', 'AI TrafficOS Mobile'),
          _buildInfoRow('Client Version', '1.0.0 (build 1)'),
          _buildInfoRow('API Target', AppConfig.apiBaseUrl),
          _buildInfoRow(
            'Active Session',
            user != null ? '${user.email} (${user.roleDisplay})' : 'Unauthenticated',
          ),
          _buildInfoRow(
            'Last Check',
            '${report.checkedAt.hour.toString().padLeft(2, '0')}:${report.checkedAt.minute.toString().padLeft(2, '0')}:${report.checkedAt.second.toString().padLeft(2, '0')}',
          ),
        ],
      ),
    );
  }

  Widget _buildMetricTile({
    required String label,
    required String value,
    required IconData icon,
    Color color = AppTokens.textPrimary,
  }) {
    return Row(
      children: [
        Icon(icon, size: 16, color: AppTokens.muted),
        const SizedBox(width: AppTokens.spaceXs),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              label,
              style: const TextStyle(
                color: AppTokens.muted,
                fontSize: 11,
              ),
            ),
            Text(
              value,
              style: TextStyle(
                color: color,
                fontSize: 13,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildInfoRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 110,
            child: Text(
              label,
              style: const TextStyle(
                color: AppTokens.muted,
                fontSize: 12,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: const TextStyle(
                color: AppTokens.textPrimary,
                fontSize: 12,
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
