import 'package:flutter/material.dart';

import '../models/health_status.dart';
import '../services/api_client.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_button.dart';
import '../widgets/app_card.dart';
import '../widgets/section_header.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({
    super.key,
    this.apiClient,
    this.onNavigateTab,
  });

  final ApiClient? apiClient;
  final void Function(int tabIndex)? onNavigateTab;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late final ApiClient _apiClient;
  bool _isLoadingHealth = false;
  ApiResult<HealthStatus>? _healthResult;

  @override
  void initState() {
    super.initState();
    _apiClient = widget.apiClient ?? ApiClient();
    _checkHealth();
  }

  Future<void> _checkHealth() async {
    if (!mounted) return;
    setState(() {
      _isLoadingHealth = true;
    });

    final result = await _apiClient.getHealth();

    if (!mounted) return;
    setState(() {
      _healthResult = result;
      _isLoadingHealth = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _checkHealth,
          color: AppTokens.teal,
          backgroundColor: theme.colorScheme.surface,
          child: ListView(
            padding: const EdgeInsets.symmetric(
              horizontal: AppTokens.spaceMd,
              vertical: AppTokens.spaceMd,
            ),
            children: [
              _buildHero(theme),
              const SizedBox(height: AppTokens.spaceLg),
              _buildSystemStatusCard(theme),
              const SizedBox(height: AppTokens.spaceXl),
              _buildRoadmapPreview(theme),
              const SizedBox(height: AppTokens.space2xl),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildHero(ThemeData theme) {
    return Container(
      decoration: BoxDecoration(
        borderRadius: AppTokens.cardBorderRadius,
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            Color(0xFF16203D),
            Color(0xFF0F1528),
          ],
        ),
        border: Border.all(
          color: AppTokens.borderDark,
          width: 1,
        ),
        boxShadow: const [
          BoxShadow(
            color: Color(0x2200D9A8),
            blurRadius: 28,
            offset: Offset(0, 10),
          ),
        ],
      ),
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(AppTokens.spaceSm),
                decoration: BoxDecoration(
                  color: AppTokens.teal.withAlpha(30),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(
                    color: AppTokens.teal.withAlpha(80),
                  ),
                ),
                child: const Icon(
                  Icons.traffic_rounded,
                  color: AppTokens.teal,
                  size: 24,
                ),
              ),
              const SizedBox(width: AppTokens.spaceSm),
              const AppBadge(
                label: 'Phase 1 • Foundation',
                color: AppTokens.teal,
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceMd),
          Text(
            'AI TrafficOS',
            style: theme.textTheme.displaySmall?.copyWith(
              color: theme.colorScheme.onSurface,
              fontWeight: FontWeight.w800,
              letterSpacing: -0.5,
            ),
          ),
          const SizedBox(height: AppTokens.spaceXs),
          Text(
            'Intelligent traffic management, reimagined.',
            style: theme.textTheme.bodyMedium?.copyWith(
              color: AppTokens.mutedOf(context),
              fontSize: 15,
            ),
          ),
          const SizedBox(height: AppTokens.spaceLg),
          Wrap(
            spacing: AppTokens.spaceSm,
            runSpacing: AppTokens.spaceSm,
            children: [
              AppButton(
                text: 'Explore Roadmap',
                icon: Icons.alt_route_rounded,
                variant: AppButtonVariant.primary,
                onPressed: () {
                  widget.onNavigateTab?.call(1);
                },
              ),
              AppButton(
                text: 'Platform Preview',
                icon: Icons.dashboard_customize_outlined,
                variant: AppButtonVariant.outlined,
                onPressed: () {
                  widget.onNavigateTab?.call(2);
                },
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildSystemStatusCard(ThemeData theme) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SectionHeader(
          title: 'System Status',
          subtitle: 'Real-time connection to AI TrafficOS API',
        ),
        AppCard(
          padding: const EdgeInsets.all(AppTokens.spaceLg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (_isLoadingHealth) ...[
                Row(
                  children: [
                    const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        valueColor:
                            AlwaysStoppedAnimation<Color>(AppTokens.teal),
                      ),
                    ),
                    const SizedBox(width: AppTokens.spaceMd),
                    Expanded(
                      child: Text(
                        'Checking backend health at ${_apiClient.baseUrl}...',
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: theme.colorScheme.onSurface,
                        ),
                      ),
                    ),
                  ],
                ),
              ] else if (_healthResult != null) ...[
                switch (_healthResult!) {
                  ApiSuccess(data: final health) => _buildHealthyContent(
                      theme,
                      health,
                    ),
                  ApiFailure(error: final error, statusCode: final code) =>
                    _buildUnhealthyContent(
                      theme,
                      error,
                      code,
                    ),
                },
              ] else ...[
                Text(
                  'Health check not initialized',
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: AppTokens.mutedOf(context),
                  ),
                ),
              ],
              const SizedBox(height: AppTokens.spaceMd),
              Divider(color: AppTokens.borderOf(context)),
              const SizedBox(height: AppTokens.spaceSm),
              Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  Icon(
                    Icons.info_outline_rounded,
                    size: 15,
                    color: AppTokens.mutedOf(context),
                  ),
                  const SizedBox(width: AppTokens.spaceXs),
                  Expanded(
                    child: Text(
                      'Phase 1 foundation — live data arrives in later phases.',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: AppTokens.mutedOf(context),
                        fontSize: 11,
                        fontStyle: FontStyle.italic,
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildHealthyContent(ThemeData theme, HealthStatus health) {
    final isOperational = health.isHealthy;
    final statusColor = isOperational ? AppTokens.success : AppTokens.amber;
    final statusText = isOperational ? 'Online' : 'Degraded';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Container(
              width: 12,
              height: 12,
              decoration: BoxDecoration(
                color: statusColor,
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(
                    color: statusColor.withAlpha(120),
                    blurRadius: 8,
                    spreadRadius: 2,
                  ),
                ],
              ),
            ),
            const SizedBox(width: AppTokens.spaceSm),
            Text(
              statusText,
              style: theme.textTheme.titleMedium?.copyWith(
                color: statusColor,
                fontWeight: FontWeight.w700,
              ),
            ),
            const Spacer(),
            AppButton(
              text: 'Recheck',
              icon: Icons.refresh_rounded,
              variant: AppButtonVariant.outlined,
              height: 34,
              isLoading: _isLoadingHealth,
              onPressed: _checkHealth,
            ),
          ],
        ),
        const SizedBox(height: AppTokens.spaceMd),
        Wrap(
          spacing: AppTokens.spaceSm,
          runSpacing: AppTokens.spaceXs,
          children: [
            AppBadge(
              label: 'Service: ${health.service}',
              color: AppTokens.teal,
            ),
            AppBadge(
              label: 'Version: ${health.version}',
              color: AppTokens.teal,
            ),
            AppBadge(
              label: 'Status: ${health.status}',
              color: statusColor,
            ),
          ],
        ),
        if (health.timestamp != null) ...[
          const SizedBox(height: AppTokens.spaceSm),
          Text(
            'Timestamp: ${health.timestamp!.toUtc().toIso8601String()}',
            style: theme.textTheme.bodySmall?.copyWith(
              color: AppTokens.mutedOf(context),
              fontSize: 11,
            ),
          ),
        ],
      ],
    );
  }

  Widget _buildUnhealthyContent(
    ThemeData theme,
    String error,
    int? statusCode,
  ) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Container(
              width: 12,
              height: 12,
              decoration: BoxDecoration(
                color: AppTokens.danger,
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(
                    color: AppTokens.danger.withAlpha(120),
                    blurRadius: 8,
                    spreadRadius: 2,
                  ),
                ],
              ),
            ),
            const SizedBox(width: AppTokens.spaceSm),
            Text(
              'Offline',
              style: theme.textTheme.titleMedium?.copyWith(
                color: AppTokens.danger,
                fontWeight: FontWeight.w700,
              ),
            ),
            const Spacer(),
            AppButton(
              text: 'Retry',
              icon: Icons.refresh_rounded,
              variant: AppButtonVariant.outlined,
              height: 34,
              isLoading: _isLoadingHealth,
              onPressed: _checkHealth,
            ),
          ],
        ),
        const SizedBox(height: AppTokens.spaceSm),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(AppTokens.spaceSm),
          decoration: BoxDecoration(
            color: AppTokens.danger.withAlpha(25),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(
              color: AppTokens.danger.withAlpha(70),
            ),
          ),
          child: Text(
            error,
            style: theme.textTheme.bodySmall?.copyWith(
              color: AppTokens.danger,
              fontFamily: 'monospace',
              fontSize: 11,
            ),
          ),
        ),
        const SizedBox(height: AppTokens.spaceSm),
        Text(
          'Target: ${_apiClient.baseUrl}/api/v1/health',
          style: theme.textTheme.bodySmall?.copyWith(
            color: AppTokens.mutedOf(context),
            fontSize: 11,
          ),
        ),
      ],
    );
  }

  Widget _buildRoadmapPreview(ThemeData theme) {
    final roadmapCapabilities = [
      (
        icon: Icons.directions_car_rounded,
        name: 'Vehicle Detection',
        description: 'Real-time edge CV vehicle classification and counting',
      ),
      (
        icon: Icons.traffic_rounded,
        name: 'Signal Detection',
        description: 'Automated optical inspection of traffic light phases',
      ),
      (
        icon: Icons.timeline_rounded,
        name: 'Traffic Prediction',
        description: 'Deep learning predictive congestion forecasting',
      ),
      (
        icon: Icons.alt_route_rounded,
        name: 'Route Guidance',
        description:
            'Dynamic multi-criteria graph routing & load rebalancing',
      ),
      (
        icon: Icons.emergency_rounded,
        name: 'Emergency Detection',
        description:
            'Audio-visual siren detection and rapid green wave clearance',
      ),
      (
        icon: Icons.warning_amber_rounded,
        name: 'Incident Detection',
        description:
            'Automated collision and stalled vehicle anomaly detection',
      ),
      (
        icon: Icons.tune_rounded,
        name: 'Signal Optimization',
        description: 'Multi-intersection adaptive timing algorithms',
      ),
      (
        icon: Icons.insights_rounded,
        name: 'Analytics',
        description: 'Historical throughput, delay metrics, and density maps',
      ),
      (
        icon: Icons.smart_toy_rounded,
        name: 'AI Assistant',
        description:
            'Interactive LLM copilot for municipal traffic operators',
      ),
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(
          title: 'Roadmap Preview',
          subtitle: 'Core capabilities arriving across upcoming phases',
          trailing: TextButton(
            onPressed: () {
              widget.onNavigateTab?.call(1);
            },
            child: const Text(
              'View All',
              style: TextStyle(
                color: AppTokens.teal,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ),
        ...roadmapCapabilities.map((item) {
          return Padding(
            padding: const EdgeInsets.only(bottom: AppTokens.spaceSm),
            child: AppCard(
              padding: const EdgeInsets.symmetric(
                horizontal: AppTokens.spaceMd,
                vertical: AppTokens.spaceMd,
              ),
              child: Row(
                children: [
                  Container(
                    width: 40,
                    height: 40,
                    decoration: BoxDecoration(
                      color: AppTokens.teal.withAlpha(25),
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(
                        color: AppTokens.teal.withAlpha(60),
                      ),
                    ),
                    child: Icon(
                      item.icon,
                      color: AppTokens.teal,
                      size: 20,
                    ),
                  ),
                  const SizedBox(width: AppTokens.spaceMd),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          item.name,
                          style: theme.textTheme.titleSmall?.copyWith(
                            color: theme.colorScheme.onSurface,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          item.description,
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: AppTokens.mutedOf(context),
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: AppTokens.spaceSm),
                  const AppBadge(
                    label: 'Phase 2+',
                    color: AppTokens.amber,
                  ),
                ],
              ),
            ),
          );
        }),
      ],
    );
  }
}
