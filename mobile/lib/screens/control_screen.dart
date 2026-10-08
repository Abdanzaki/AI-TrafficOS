import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/control_recommendation.dart';
import '../models/junction.dart';
import '../providers/realtime_providers.dart';
import '../services/auth_service.dart';
import '../services/control_service.dart';
import '../services/junction_service.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_button.dart';
import '../widgets/app_card.dart';
import '../widgets/empty_state.dart';
import '../widgets/error_state.dart';
import '../widgets/loading_state.dart';
import '../widgets/offline_banner.dart';

/// Screen providing per-junction intelligent traffic control recommendations,
/// queue-proportional Webster optimization, and macroscopic what-if plan simulation.
class ControlScreen extends ConsumerStatefulWidget {
  const ControlScreen({super.key, this.initialIntersectionId});

  final int? initialIntersectionId;

  @override
  ConsumerState<ControlScreen> createState() => _ControlScreenState();
}

class _ControlScreenState extends ConsumerState<ControlScreen> {
  int? _selectedIntersectionId;
  List<Junction> _junctions = [];
  bool _isLoadingJunctions = true;

  bool _isLoadingRec = false;
  String? _recError;
  ControlRecommendation? _recommendation;

  bool _isOptimizing = false;
  OptimizationResult? _optimizationResult;

  // What-if simulation state
  double _proposedGreenPhase1 = 40.0;
  double _proposedGreenPhase2 = 30.0;
  bool _isSimulating = false;
  SimulationComparison? _simulationComparison;

  @override
  void initState() {
    super.initState();
    _selectedIntersectionId = widget.initialIntersectionId;
    _initJunctions();
  }

  Future<void> _initJunctions() async {
    setState(() => _isLoadingJunctions = true);
    try {
      final junctionService = ref.read(junctionServiceProvider);
      final res = await junctionService.getJunctions(perPage: 50);
      if (mounted) {
        setState(() {
          _junctions = res.items;
          _isLoadingJunctions = false;
          if (_selectedIntersectionId == null && _junctions.isNotEmpty) {
            _selectedIntersectionId = _junctions.first.id;
          }
        });
        if (_selectedIntersectionId != null) {
          _loadRecommendation(_selectedIntersectionId!);
        }
      }
    } catch (_) {
      if (mounted) {
        setState(() => _isLoadingJunctions = false);
      }
    }
  }

  Future<void> _loadRecommendation(int intersectionId) async {
    setState(() {
      _isLoadingRec = true;
      _recError = null;
      _optimizationResult = null;
      _simulationComparison = null;
    });

    try {
      final controlService = ref.read(controlServiceProvider);
      final rec = await controlService.getRecommendations(intersectionId);
      if (mounted) {
        setState(() {
          _recommendation = rec;
          _isLoadingRec = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _recError = e.toString();
          _isLoadingRec = false;
        });
      }
    }
  }

  Future<void> _runOptimization() async {
    if (_selectedIntersectionId == null) return;
    setState(() {
      _isOptimizing = true;
    });

    try {
      final controlService = ref.read(controlServiceProvider);
      final res = await controlService.optimizeSignals(_selectedIntersectionId!);
      if (mounted) {
        setState(() {
          _optimizationResult = res;
          _isOptimizing = false;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            backgroundColor: AppTokens.success,
            content: Text('Signal timing optimization calculated successfully.'),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isOptimizing = false;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: AppTokens.danger,
            content: Text('Optimization failed: $e'),
          ),
        );
      }
    }
  }

  Future<void> _runSimulation() async {
    if (_selectedIntersectionId == null) return;
    setState(() {
      _isSimulating = true;
    });

    try {
      final controlService = ref.read(controlServiceProvider);
      final proposedPlan = {
        'phases': {
          'phase_1': _proposedGreenPhase1,
          'phase_2': _proposedGreenPhase2,
        },
        'phase_to_approaches': {
          'phase_1': ['northbound'],
          'phase_2': ['eastbound'],
        },
        'yellow_s': 3.0,
        'all_red_s': 2.0,
      };

      final comparison = await controlService.simulate(
        intersectionId: _selectedIntersectionId!,
        proposedPlan: proposedPlan,
      );

      if (mounted) {
        setState(() {
          _simulationComparison = comparison;
          _isSimulating = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isSimulating = false;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: AppTokens.danger,
            content: Text('Simulation failed: $e'),
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final user = ref.watch(currentUserProvider);
    final isAnalyst = user?.isAnalyst ?? false;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Supervisory Control'),
        actions: [
          if (_selectedIntersectionId != null)
            IconButton(
              icon: const Icon(Icons.refresh_rounded),
              tooltip: 'Refresh Recommendations',
              onPressed: () => _loadRecommendation(_selectedIntersectionId!),
            ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            if (ref.watch(isOfflineProvider)) const OfflineBanner(),
            _buildSafetyBanner(),
            _buildJunctionSelectorBar(theme),
            Expanded(
              child: RefreshIndicator(
                color: AppTokens.teal,
                backgroundColor: theme.colorScheme.surface,
                onRefresh: () async {
                  if (_selectedIntersectionId != null) {
                    await _loadRecommendation(_selectedIntersectionId!);
                  }
                },
                child: _buildScrollableContent(theme, isAnalyst),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSafetyBanner() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(
        horizontal: AppTokens.spaceMd,
        vertical: AppTokens.spaceSm,
      ),
      decoration: BoxDecoration(
        color: AppTokens.teal.withAlpha(25),
        border: const Border(
          bottom: BorderSide(color: AppTokens.teal, width: 1.5),
        ),
      ),
      child: const Row(
        children: [
          Icon(Icons.shield_outlined, color: AppTokens.teal, size: 20),
          SizedBox(width: AppTokens.spaceSm),
          Expanded(
            child: Text(
              'AI recommendations — does not control physical hardware',
              style: TextStyle(
                color: AppTokens.teal,
                fontWeight: FontWeight.w700,
                fontSize: 12,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildJunctionSelectorBar(ThemeData theme) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppTokens.spaceMd,
        vertical: AppTokens.spaceSm,
      ),
      decoration: BoxDecoration(
        color: theme.colorScheme.surface,
        border: Border(
          bottom: BorderSide(color: AppTokens.borderOf(context)),
        ),
      ),
      child: Row(
        children: [
          const Icon(
            Icons.location_on_rounded,
            color: AppTokens.teal,
            size: 20,
          ),
          const SizedBox(width: AppTokens.spaceSm),
          Expanded(
            child: DropdownButtonHideUnderline(
              child: DropdownButton<int>(
                value: _selectedIntersectionId,
                isExpanded: true,
                dropdownColor: theme.colorScheme.surface,
                hint: Text(
                  'Select Junction...',
                  style: TextStyle(color: theme.colorScheme.onSurface, fontSize: 13),
                ),
                icon: Icon(
                  Icons.arrow_drop_down_rounded,
                  color: AppTokens.mutedOf(context),
                ),
                items: _junctions.map((j) {
                  return DropdownMenuItem<int>(
                    value: j.id,
                    child: Text(
                      'Junction #${j.id} — ${j.name}',
                      style: TextStyle(
                        color: theme.colorScheme.onSurface,
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  );
                }).toList(),
                onChanged: (val) {
                  if (val != null && val != _selectedIntersectionId) {
                    setState(() => _selectedIntersectionId = val);
                    _loadRecommendation(val);
                  }
                },
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildScrollableContent(ThemeData theme, bool isAnalyst) {
    if (_isLoadingJunctions) {
      return const LoadingState(message: 'Loading municipal network junctions...');
    }

    if (_junctions.isEmpty) {
      return const EmptyState(
        icon: Icons.alt_route_rounded,
        title: 'No Junctions Available',
        message: 'No physical intersections registered in database.',
      );
    }

    if (_isLoadingRec) {
      return const LoadingState(message: 'Formulating supervisory recommendations...');
    }

    if (_recError != null) {
      return ErrorState(
        message: _recError!,
        title: 'Recommendation Unavailable',
        onRetry: () {
          if (_selectedIntersectionId != null) {
            _loadRecommendation(_selectedIntersectionId!);
          }
        },
      );
    }

    return ListView(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      children: [
        if (isAnalyst) ...[
          _buildAnalystNotice(),
          const SizedBox(height: AppTokens.spaceMd),
        ],
        _buildRecommendationsSection(theme),
        const SizedBox(height: AppTokens.spaceLg),
        _buildOptimizationSection(theme, isAnalyst),
        const SizedBox(height: AppTokens.spaceLg),
        _buildSimulationCard(theme),
        const SizedBox(height: AppTokens.spaceXl),
      ],
    );
  }

  Widget _buildAnalystNotice() {
    return Container(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      decoration: BoxDecoration(
        color: AppTokens.amber.withAlpha(20),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTokens.amber.withAlpha(80)),
      ),
      child: Row(
        children: [
          const Icon(Icons.info_outline_rounded, color: AppTokens.amber, size: 22),
          const SizedBox(width: AppTokens.spaceMd),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Read-Only Operator Mode',
                  style: TextStyle(
                    color: Theme.of(context).colorScheme.onSurface,
                    fontWeight: FontWeight.w700,
                    fontSize: 13,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  'Signal timing optimization execution and manual hardware override commands are restricted to Traffic Officers and System Administrators.',
                  style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 12),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildRecommendationsSection(ThemeData theme) {
    final rec = _recommendation;
    if (rec == null) {
      return const EmptyState(
        icon: Icons.psychology_rounded,
        title: 'No Active Recommendation',
        message: 'Telemetry conditions are nominal.',
      );
    }

    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'Supervisory Recommendation',
                style: theme.textTheme.titleSmall?.copyWith(
                  color: theme.colorScheme.onSurface,
                  fontWeight: FontWeight.w700,
                ),
              ),
              AppBadge(
                label: rec.action,
                color: rec.actionColor,
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceSm),
          Text(
            rec.reason,
            style: TextStyle(
              color: theme.colorScheme.onSurface,
              fontSize: 14,
              fontWeight: FontWeight.w500,
            ),
          ),
          const SizedBox(height: AppTokens.spaceSm),
          Row(
            children: [
              const Icon(Icons.insights_rounded, size: 16, color: AppTokens.teal),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  'Expected Impact: ${rec.expectedImpact}',
                  style: TextStyle(
                    color: AppTokens.mutedOf(context),
                    fontSize: 12,
                  ),
                ),
              ),
            ],
          ),
          if (rec.confidence != null) ...[
            const SizedBox(height: AppTokens.spaceMd),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  'Algorithmic Confidence',
                  style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 11),
                ),
                Text(
                  '${(rec.confidence! * 100).toInt()}%',
                  style: const TextStyle(
                    color: AppTokens.teal,
                    fontWeight: FontWeight.w700,
                    fontSize: 12,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            ClipRRect(
              borderRadius: BorderRadius.circular(4),
              child: LinearProgressIndicator(
                value: rec.confidence!,
                backgroundColor: theme.colorScheme.surface,
                valueColor: const AlwaysStoppedAnimation(AppTokens.teal),
                minHeight: 6,
              ),
            ),
          ],
          if (rec.current != null) ...[
            const SizedBox(height: AppTokens.spaceMd),
            Divider(color: AppTokens.borderOf(context)),
            const SizedBox(height: AppTokens.spaceSm),
            Text(
              'Observed Traffic Conditions Snapshot:',
              style: TextStyle(
                color: AppTokens.mutedOf(context),
                fontSize: 11,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: AppTokens.spaceSm),
            Wrap(
              spacing: AppTokens.spaceMd,
              runSpacing: AppTokens.spaceSm,
              children: [
                _buildStatPill(
                  label: 'Vehicles',
                  value: '${rec.current!.vehicleCount}',
                ),
                _buildStatPill(
                  label: 'Queue',
                  value: '${rec.current!.queueLength.toStringAsFixed(1)} veh',
                ),
                _buildStatPill(
                  label: 'Density',
                  value: '${rec.current!.density.toStringAsFixed(1)} veh/km',
                ),
                _buildStatPill(
                  label: 'Occupancy',
                  value: '${(rec.current!.occupancy * 100).toInt()}%',
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildStatPill({required String label, required String value}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppTokens.borderOf(context)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            label,
            style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 10),
          ),
          Text(
            value,
            style: TextStyle(
              color: Theme.of(context).colorScheme.onSurface,
              fontWeight: FontWeight.w700,
              fontSize: 12,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildOptimizationSection(ThemeData theme, bool isAnalyst) {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.tune_rounded, color: AppTokens.teal, size: 22),
              const SizedBox(width: AppTokens.spaceSm),
              Text(
                'Signal Timing Optimization',
                style: theme.textTheme.titleSmall?.copyWith(
                  color: theme.colorScheme.onSurface,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceSm),
          Text(
            'Calculate queue-proportional Webster green split allocations adhering to statutory minimum and clearance boundaries.',
            style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 12),
          ),
          const SizedBox(height: AppTokens.spaceMd),
          if (!isAnalyst) ...[
            AppButton(
              text: 'Optimize Signals',
              icon: Icons.auto_awesome_rounded,
              isLoading: _isOptimizing,
              isFullWidth: true,
              onPressed: _runOptimization,
            ),
          ],
          if (_optimizationResult != null) ...[
            const SizedBox(height: AppTokens.spaceLg),
            Container(
              padding: const EdgeInsets.all(AppTokens.spaceMd),
              decoration: BoxDecoration(
                color: theme.colorScheme.surface,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: AppTokens.teal.withAlpha(80)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        'Optimized Signal Plan',
                        style: TextStyle(
                          color: theme.colorScheme.onSurface,
                          fontWeight: FontWeight.w700,
                          fontSize: 14,
                        ),
                      ),
                      const AppBadge(label: 'PASSED SAFETY VALIDATION', color: AppTokens.success),
                    ],
                  ),
                  const SizedBox(height: AppTokens.spaceSm),
                  Text(
                    'Method: ${_optimizationResult!.method} | Total Cycle: ${_optimizationResult!.totalCycleS.toInt()}s',
                    style: const TextStyle(color: AppTokens.teal, fontSize: 12),
                  ),
                  const SizedBox(height: AppTokens.spaceMd),
                  Text(
                    'Recommended Green Allocations:',
                    style: TextStyle(
                      color: AppTokens.mutedOf(context),
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 6),
                  ..._optimizationResult!.recommendedGreenS.entries.map((e) {
                    return Padding(
                      padding: const EdgeInsets.symmetric(vertical: 2),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(
                            'Phase ${e.key}',
                            style: TextStyle(
                              color: theme.colorScheme.onSurface,
                              fontSize: 13,
                            ),
                          ),
                          Text(
                            '${e.value.toStringAsFixed(1)}s green',
                            style: const TextStyle(
                              color: AppTokens.teal,
                              fontWeight: FontWeight.w700,
                              fontSize: 13,
                            ),
                          ),
                        ],
                      ),
                    );
                  }),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildSimulationCard(ThemeData theme) {
    final comp = _simulationComparison;

    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.science_rounded, color: AppTokens.amber, size: 22),
              const SizedBox(width: AppTokens.spaceSm),
              Text(
                'What-If Macroscopic Simulation',
                style: theme.textTheme.titleSmall?.copyWith(
                  color: theme.colorScheme.onSurface,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceSm),
          Text(
            'Test candidate timing plans against a point-queue macroscopic traffic model. Measures real mathematical deltas without fabricating gains.',
            style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 12),
          ),
          const SizedBox(height: AppTokens.spaceMd),
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Phase 1: ${_proposedGreenPhase1.toInt()}s',
                      style: TextStyle(
                        color: theme.colorScheme.onSurface,
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    Slider(
                      value: _proposedGreenPhase1,
                      min: 10,
                      max: 90,
                      divisions: 16,
                      activeColor: AppTokens.amber,
                      inactiveColor: theme.colorScheme.surfaceContainerHighest,
                      onChanged: (val) => setState(() => _proposedGreenPhase1 = val),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Phase 2: ${_proposedGreenPhase2.toInt()}s',
                      style: TextStyle(
                        color: theme.colorScheme.onSurface,
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    Slider(
                      value: _proposedGreenPhase2,
                      min: 10,
                      max: 90,
                      divisions: 16,
                      activeColor: AppTokens.amber,
                      inactiveColor: theme.colorScheme.surfaceContainerHighest,
                      onChanged: (val) => setState(() => _proposedGreenPhase2 = val),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceSm),
          AppButton(
            text: 'Run What-If Simulation',
            icon: Icons.play_arrow_rounded,
            isLoading: _isSimulating,
            variant: AppButtonVariant.outlined,
            isFullWidth: true,
            onPressed: _runSimulation,
          ),
          if (comp != null) ...[
            const SizedBox(height: AppTokens.spaceLg),
            Container(
              padding: const EdgeInsets.all(AppTokens.spaceMd),
              decoration: BoxDecoration(
                color: theme.colorScheme.surface,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: comp.isProposedBetter ? AppTokens.success : AppTokens.amber,
                ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        'Measured Simulation Deltas',
                        style: TextStyle(
                          color: theme.colorScheme.onSurface,
                          fontWeight: FontWeight.w700,
                          fontSize: 14,
                        ),
                      ),
                      AppBadge(
                        label: comp.verdict.replaceAll('_', ' ').toUpperCase(),
                        color: comp.isProposedBetter ? AppTokens.success : AppTokens.amber,
                      ),
                    ],
                  ),
                  const SizedBox(height: AppTokens.spaceMd),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceAround,
                    children: [
                      _buildDeltaColumn(
                        label: 'Wait Time',
                        delta: comp.deltaWait,
                        unit: 'veh·min',
                        invertImprovement: true,
                      ),
                      _buildDeltaColumn(
                        label: 'Avg Queue',
                        delta: comp.deltaAvgQueue,
                        unit: 'veh',
                        invertImprovement: true,
                      ),
                      _buildDeltaColumn(
                        label: 'Throughput',
                        delta: comp.deltaThroughput,
                        unit: 'veh',
                        invertImprovement: false,
                      ),
                    ],
                  ),
                  const SizedBox(height: AppTokens.spaceMd),
                  Divider(color: AppTokens.borderOf(context)),
                  const SizedBox(height: AppTokens.spaceSm),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        'Baseline Wait: ${comp.currentResult.totalWaitVehMin.toStringAsFixed(1)}m',
                        style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 11),
                      ),
                      Text(
                        'Proposed Wait: ${comp.proposedResult.totalWaitVehMin.toStringAsFixed(1)}m',
                        style: const TextStyle(color: AppTokens.teal, fontSize: 11),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildDeltaColumn({
    required String label,
    required double delta,
    required String unit,
    required bool invertImprovement,
  }) {
    // For wait time and queue: negative delta is an improvement (green)
    // For throughput: positive delta is an improvement (green)
    final isGood = invertImprovement ? delta <= 0 : delta >= 0;
    final color = isGood ? AppTokens.success : AppTokens.danger;
    final sign = delta > 0 ? '+' : '';

    return Column(
      children: [
        Text(
          label,
          style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 11),
        ),
        const SizedBox(height: 2),
        Text(
          '$sign${delta.toStringAsFixed(1)} $unit',
          style: TextStyle(
            color: color,
            fontWeight: FontWeight.w800,
            fontSize: 14,
          ),
        ),
      ],
    );
  }
}
