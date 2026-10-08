import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/incident.dart';
import '../providers/realtime_providers.dart';
import '../services/api_client.dart';
import '../services/auth_service.dart';
import '../services/incident_service.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_card.dart';
import '../widgets/error_state.dart';
import '../widgets/loading_state.dart';
import '../widgets/offline_banner.dart';

/// Detailed view for an individual incident featuring a visual status timeline,
/// metadata chips, and RBAC-governed lifecycle status progression.
class IncidentDetailScreen extends ConsumerStatefulWidget {
  const IncidentDetailScreen({
    super.key,
    required this.incidentId,
    this.initialIncident,
  });

  final int incidentId;
  final Incident? initialIncident;

  @override
  ConsumerState<IncidentDetailScreen> createState() =>
      _IncidentDetailScreenState();
}

class _IncidentDetailScreenState extends ConsumerState<IncidentDetailScreen> {
  late Incident? _incident;
  bool _isLoading = false;
  bool _isTransitioning = false;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _incident = widget.initialIncident;
    if (_incident == null) {
      _loadIncident();
    }
  }

  Future<void> _loadIncident() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final service = ref.read(incidentServiceProvider);
      final item = await service.getIncident(widget.incidentId);
      if (mounted) {
        setState(() {
          _incident = item;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoading = false;
          _errorMessage =
              e is ApiException ? e.message : 'Failed to load incident #$widget.incidentId';
        });
      }
    }
  }

  Future<void> _transitionStatus(String newStatus) async {
    if (_incident == null || _isTransitioning) return;

    setState(() {
      _isTransitioning = true;
    });

    try {
      final service = ref.read(incidentServiceProvider);
      final updated = await service.updateIncidentStatus(
        id: _incident!.id,
        status: newStatus,
        currentStatus: _incident!.status,
      );

      if (mounted) {
        setState(() {
          _incident = updated;
          _isTransitioning = false;
        });

        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: Theme.of(context).colorScheme.surface,
            content: Text(
              'Incident #${updated.id} transitioned to ${updated.status.toUpperCase()}',
              style: TextStyle(color: Theme.of(context).colorScheme.onSurface),
            ),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isTransitioning = false;
        });

        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: AppTokens.danger,
            content: Text(
              e is ApiException ? e.message : 'Transition failed: $e',
              style: const TextStyle(color: Colors.white),
            ),
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(currentUserProvider);
    final isAnalyst = user?.isAnalyst ?? false;
    final canWrite = (user?.canWrite ?? false) && !isAnalyst;

    return Scaffold(
      appBar: AppBar(
        title: Text('Incident #${widget.incidentId}'),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh_rounded),
            onPressed: _loadIncident,
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            if (ref.watch(isOfflineProvider)) const OfflineBanner(),
            Expanded(child: _buildBody(context, canWrite, isAnalyst)),
          ],
        ),
      ),
    );
  }

  Widget _buildBody(BuildContext context, bool canWrite, bool isAnalyst) {
    if (_isLoading) {
      return const Center(
        child: LoadingState(
          message: 'Fetching incident lifecycle records...',
          subtitle: 'Querying vision perception and dispatch history',
        ),
      );
    }

    if (_errorMessage != null && _incident == null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(AppTokens.spaceMd),
          child: ErrorState(
            title: 'Incident Record Unavailable',
            message: _errorMessage!,
            onRetry: _loadIncident,
          ),
        ),
      );
    }

    if (_incident == null) {
      return const SizedBox.shrink();
    }

    final inc = _incident!;

    return RefreshIndicator(
      onRefresh: _loadIncident,
      color: AppTokens.teal,
      backgroundColor: Theme.of(context).colorScheme.surface,
      child: ListView(
        padding: const EdgeInsets.all(AppTokens.spaceMd),
        children: [
          _buildSummaryHeader(inc),
          const SizedBox(height: AppTokens.spaceMd),
          _buildStatusTimeline(inc),
          const SizedBox(height: AppTokens.spaceMd),
          _buildTransitionActions(inc, canWrite, isAnalyst),
          const SizedBox(height: AppTokens.spaceMd),
          _buildDescriptionCard(inc),
          const SizedBox(height: AppTokens.spaceMd),
          _buildTelemetryMetadata(inc),
        ],
      ),
    );
  }

  Widget _buildSummaryHeader(Incident inc) {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: inc.severityColor.withAlpha(25),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: inc.severityColor.withAlpha(80)),
                ),
                child: Icon(
                  Icons.warning_amber_rounded,
                  color: inc.severityColor,
                  size: 24,
                ),
              ),
              const SizedBox(width: AppTokens.spaceMd),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      inc.displayTitle,
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w700,
                        color: Theme.of(context).colorScheme.onSurface,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      'Reported: ${inc.createdAt.toLocal().toString().split(".")[0]}',
                      style: TextStyle(
                        color: AppTokens.mutedOf(context),
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  AppBadge(
                    label: inc.status.toUpperCase(),
                    color: inc.statusColor,
                  ),
                  const SizedBox(height: 4),
                  AppBadge(
                    label: inc.severity.toUpperCase(),
                    color: inc.severityColor,
                  ),
                ],
              ),
            ],
          ),
          if (inc.intersectionId != null) ...[
            const SizedBox(height: AppTokens.spaceMd),
            Row(
              children: [
                const Icon(Icons.traffic_rounded, size: 16, color: AppTokens.teal),
                const SizedBox(width: 6),
                Text(
                  'Associated Intersection #${inc.intersectionId}',
                  style: const TextStyle(
                    color: AppTokens.teal,
                    fontWeight: FontWeight.w600,
                    fontSize: 13,
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildStatusTimeline(Incident inc) {
    final status = inc.incidentStatus;

    final steps = [
      _TimelineStep(
        title: 'Reported',
        subtitle: 'Hazard registered by operator or vision AI',
        isPassed: true,
        isActive: status == IncidentStatus.reported,
        color: AppTokens.danger,
      ),
      _TimelineStep(
        title: 'Acknowledged',
        subtitle: 'Traffic officer assigned & units dispatched',
        isPassed: status == IncidentStatus.acknowledged || status == IncidentStatus.resolved,
        isActive: status == IncidentStatus.acknowledged,
        color: AppTokens.amber,
      ),
      _TimelineStep(
        title: 'Resolved',
        subtitle: inc.resolvedAt != null
            ? 'Cleared at ${inc.resolvedAt!.toLocal().toString().split(".")[0]}'
            : 'Hazard mitigations complete and normal flow restored',
        isPassed: status == IncidentStatus.resolved,
        isActive: status == IncidentStatus.resolved,
        color: AppTokens.success,
      ),
    ];

    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Lifecycle Progression',
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w700,
              color: Theme.of(context).colorScheme.onSurface,
            ),
          ),
          const SizedBox(height: AppTokens.spaceMd),
          for (int i = 0; i < steps.length; i++) ...[
            _buildTimelineItem(steps[i], isLast: i == steps.length - 1),
          ],
        ],
      ),
    );
  }

  Widget _buildTimelineItem(_TimelineStep step, {required bool isLast}) {
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Column(
            children: [
              Container(
                width: 22,
                height: 22,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: step.isPassed
                      ? step.color
                      : Theme.of(context).colorScheme.surface,
                  border: Border.all(
                    color: step.isPassed ? step.color : AppTokens.borderOf(context),
                    width: 2,
                  ),
                ),
                child: step.isPassed
                    ? const Icon(Icons.check, size: 13, color: Colors.white)
                    : null,
              ),
              if (!isLast)
                Expanded(
                  child: Container(
                    width: 2,
                    color: step.isPassed
                        ? step.color.withAlpha(120)
                        : AppTokens.borderOf(context),
                  ),
                ),
            ],
          ),
          const SizedBox(width: AppTokens.spaceMd),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(bottom: AppTokens.spaceMd),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    step.title,
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight:
                          step.isActive ? FontWeight.w800 : FontWeight.w600,
                      color: step.isActive ? step.color : Theme.of(context).colorScheme.onSurface,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    step.subtitle,
                    style: TextStyle(
                      fontSize: 12,
                      color: AppTokens.mutedOf(context),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTransitionActions(
    Incident inc,
    bool canWrite,
    bool isAnalyst,
  ) {
    if (isAnalyst) {
      return AppCard(
        padding: const EdgeInsets.all(AppTokens.spaceMd),
        child: Row(
          children: [
            const Icon(Icons.lock_outline_rounded, color: AppTokens.amber, size: 20),
            const SizedBox(width: AppTokens.spaceSm),
            const Expanded(
              child: Text(
                'Analyst mode: Status transitions and updates are read-only.',
                style: TextStyle(color: AppTokens.amber, fontSize: 12),
              ),
            ),
          ],
        ),
      );
    }

    if (!canWrite) {
      return const SizedBox.shrink();
    }

    if (inc.isResolved) {
      return AppCard(
        padding: const EdgeInsets.all(AppTokens.spaceMd),
        child: Row(
          children: [
            const Icon(Icons.check_circle_outline_rounded,
                color: AppTokens.success, size: 20),
            const SizedBox(width: AppTokens.spaceSm),
            Expanded(
              child: Text(
                'This incident has been resolved. Transition back to reported is prohibited by safety policy.',
                style: TextStyle(color: Theme.of(context).colorScheme.onSurface, fontSize: 12),
              ),
            ),
          ],
        ),
      );
    }

    final validNext = inc.incidentStatus.validNextStatuses;

    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.published_with_changes_rounded,
                  color: AppTokens.teal, size: 18),
              const SizedBox(width: AppTokens.spaceSm),
              Text(
                'Lifecycle Action Transition',
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                  color: Theme.of(context).colorScheme.onSurface,
                ),
              ),
              const Spacer(),
              if (_isTransitioning)
                const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    valueColor: AlwaysStoppedAnimation(AppTokens.teal),
                  ),
                ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceMd),
          Wrap(
            spacing: AppTokens.spaceSm,
            runSpacing: AppTokens.spaceSm,
            children: [
              for (final target in validNext) ...[
                ElevatedButton.icon(
                  icon: Icon(
                    target == IncidentStatus.acknowledged
                        ? Icons.assignment_turned_in_rounded
                        : Icons.check_circle_rounded,
                    size: 16,
                  ),
                  label: Text('Mark as ${target.label}'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: target == IncidentStatus.resolved
                        ? AppTokens.success
                        : AppTokens.amber,
                    foregroundColor: Colors.white,
                    disabledBackgroundColor: Theme.of(context).colorScheme.surface,
                  ),
                  onPressed: _isTransitioning
                      ? null
                      : () => _transitionStatus(target.value),
                ),
              ],
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildDescriptionCard(Incident inc) {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Incident Description',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: Theme.of(context).colorScheme.onSurface,
            ),
          ),
          const SizedBox(height: AppTokens.spaceSm),
          Text(
            inc.description ?? 'No narrative description recorded.',
            style: TextStyle(
              color: Theme.of(context).colorScheme.onSurface,
              fontSize: 14,
              height: 1.5,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTelemetryMetadata(Incident inc) {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Telemetry & Geographic Records',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: Theme.of(context).colorScheme.onSurface,
            ),
          ),
          const SizedBox(height: AppTokens.spaceMd),
          _buildMetaRow(
            'Incident ID',
            '#${inc.id}',
          ),
          if (inc.reportedBy != null)
            _buildMetaRow(
              'Reported By',
              'User ID ${inc.reportedBy}',
            ),
          if (inc.latitude != null && inc.longitude != null)
            _buildMetaRow(
              'Coordinates',
              '${inc.latitude!.toStringAsFixed(5)}, ${inc.longitude!.toStringAsFixed(5)}',
            ),
          _buildMetaRow(
            'Updated At',
            inc.updatedAt.toLocal().toString().split(".")[0],
          ),
          if (inc.resolvedAt != null)
            _buildMetaRow(
              'Resolved At',
              inc.resolvedAt!.toLocal().toString().split(".")[0],
            ),
        ],
      ),
    );
  }

  Widget _buildMetaRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppTokens.spaceSm),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            label,
            style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 12),
          ),
          Text(
            value,
            style: TextStyle(
              color: Theme.of(context).colorScheme.onSurface,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

class _TimelineStep {
  const _TimelineStep({
    required this.title,
    required this.subtitle,
    required this.isPassed,
    required this.isActive,
    required this.color,
  });

  final String title;
  final String subtitle;
  final bool isPassed;
  final bool isActive;
  final Color color;
}
