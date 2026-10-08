import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/signal.dart';
import '../providers/realtime_providers.dart';
import '../services/auth_service.dart';
import '../services/realtime_protocol.dart';
import '../services/signal_service.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_button.dart';
import '../widgets/app_card.dart';
import '../widgets/empty_state.dart';
import '../widgets/error_state.dart';
import '../widgets/loading_state.dart';

/// Screen displaying detailed signal controller timings, phase sequence timeline,
/// and supervisory manual override controls.
class SignalDetailScreen extends ConsumerStatefulWidget {
  const SignalDetailScreen({super.key, required this.signalId});

  final int signalId;

  @override
  ConsumerState<SignalDetailScreen> createState() => _SignalDetailScreenState();
}

class _SignalDetailScreenState extends ConsumerState<SignalDetailScreen> {
  bool _isLoading = true;
  String? _errorMessage;
  Signal? _signal;
  bool _isSubmittingOverride = false;

  @override
  void initState() {
    super.initState();
    _loadSignal();
  }

  Future<void> _loadSignal({bool isBackgroundRefresh = false}) async {
    if (!isBackgroundRefresh) {
      setState(() {
        _isLoading = true;
        _errorMessage = null;
      });
    }

    try {
      final signalService = ref.read(signalServiceProvider);
      final sig = await signalService.getSignal(widget.signalId);
      if (mounted) {
        setState(() {
          _signal = sig;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _errorMessage = e.toString();
          _isLoading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    // Real-time WebSocket invalidation: refresh signal detail on signal.change
    ref.listen(
      realtimeTopicEventProvider(RealtimeTopics.signalChange),
      (_, next) {
        if (next.hasValue) {
          _loadSignal(isBackgroundRefresh: true);
        }
      },
    );

    final theme = Theme.of(context);
    final user = ref.watch(currentUserProvider);
    final isAnalyst = user?.isAnalyst ?? false;

    return Scaffold(
      appBar: AppBar(
        title: Text(_signal != null ? _signal!.name : 'Signal Controller #${widget.signalId}'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Refresh Signal',
            onPressed: _loadSignal,
          ),
        ],
      ),
      body: SafeArea(
        child: _buildBody(theme, isAnalyst),
      ),
    );
  }

  Widget _buildBody(ThemeData theme, bool isAnalyst) {
    if (_isLoading) {
      return const LoadingState(message: 'Loading signal controller details...');
    }

    if (_errorMessage != null) {
      return ErrorState(
        message: _errorMessage!,
        title: 'Unable to Load Signal',
        onRetry: _loadSignal,
      );
    }

    final signal = _signal;
    if (signal == null) {
      return const EmptyState(
        icon: Icons.traffic_rounded,
        title: 'Signal Not Found',
        message: 'No hardware controller record was found for this identifier.',
      );
    }

    return ListView(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      children: [
        _buildSignalHeaderCard(theme, signal),
        const SizedBox(height: AppTokens.spaceMd),
        _buildOpticalObservationCard(theme, signal),
        const SizedBox(height: AppTokens.spaceLg),
        _buildPhaseTimelineHeader(theme, signal),
        const SizedBox(height: AppTokens.spaceSm),
        ..._buildPhaseList(theme, signal),
        const SizedBox(height: AppTokens.spaceLg),
        _buildOverrideSection(theme, signal, isAnalyst),
        const SizedBox(height: AppTokens.spaceXl),
      ],
    );
  }

  Widget _buildSignalHeaderCard(ThemeData theme, Signal signal) {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 50,
                height: 50,
                decoration: BoxDecoration(
                  color: signal.stateColor.withAlpha(30),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(
                    color: signal.stateColor.withAlpha(120),
                    width: 2,
                  ),
                ),
                child: Center(
                  child: Icon(
                    Icons.traffic_rounded,
                    color: signal.stateColor,
                    size: 26,
                  ),
                ),
              ),
              const SizedBox(width: AppTokens.spaceMd),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      signal.name,
                      style: theme.textTheme.titleMedium?.copyWith(
                        color: AppTokens.textPrimary,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      'Hardware Code: ${signal.code}',
                      style: const TextStyle(
                        color: AppTokens.muted,
                        fontSize: 12,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        AppBadge(
                          label: signal.status.toUpperCase(),
                          color: signal.statusColor,
                        ),
                        const SizedBox(width: AppTokens.spaceSm),
                        AppBadge(
                          label: 'Junction #${signal.intersectionId}',
                          color: AppTokens.teal,
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceMd),
          const Divider(color: AppTokens.borderDark),
          const SizedBox(height: AppTokens.spaceSm),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Active Optical State',
                    style: TextStyle(color: AppTokens.muted, fontSize: 11),
                  ),
                  const SizedBox(height: 2),
                  Row(
                    children: [
                      Container(
                        width: 10,
                        height: 10,
                        decoration: BoxDecoration(
                          color: signal.stateColor,
                          shape: BoxShape.circle,
                        ),
                      ),
                      const SizedBox(width: 6),
                      Text(
                        signal.state.label.toUpperCase(),
                        style: TextStyle(
                          color: signal.stateColor,
                          fontWeight: FontWeight.w700,
                          fontSize: 13,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  const Text(
                    'Current Phase',
                    style: TextStyle(color: AppTokens.muted, fontSize: 11),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    signal.currentPhase ?? 'Default Cycle',
                    style: const TextStyle(
                      color: AppTokens.textPrimary,
                      fontWeight: FontWeight.w700,
                      fontSize: 13,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildOpticalObservationCard(ThemeData theme, Signal signal) {
    final hasObs = signal.observedState != null || signal.observedConfidence != null;

    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      child: Row(
        children: [
          const Icon(
            Icons.camera_alt_rounded,
            color: AppTokens.teal,
            size: 20,
          ),
          const SizedBox(width: AppTokens.spaceSm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'CV Optical Ground Truth',
                  style: TextStyle(
                    color: AppTokens.textPrimary,
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                Text(
                  hasObs
                      ? 'Observed: ${signal.observedState?.toUpperCase() ?? "N/A"} (${((signal.observedConfidence ?? 1.0) * 100).toInt()}% conf)'
                      : 'No optical camera telemetry ingested yet',
                  style: const TextStyle(
                    color: AppTokens.muted,
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ),
          if (signal.observedAt != null)
            Text(
              '${signal.observedAt!.hour.toString().padLeft(2, '0')}:${signal.observedAt!.minute.toString().padLeft(2, '0')}',
              style: const TextStyle(color: AppTokens.muted, fontSize: 11),
            ),
        ],
      ),
    );
  }

  Widget _buildPhaseTimelineHeader(ThemeData theme, Signal signal) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Row(
          children: [
            const Icon(Icons.timeline_rounded, color: AppTokens.teal, size: 20),
            const SizedBox(width: AppTokens.spaceSm),
            Text(
              'Phase Interval Sequence (${signal.phases.length})',
              style: theme.textTheme.titleSmall?.copyWith(
                color: AppTokens.textPrimary,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
        Text(
          'Total: ${signal.phases.fold<int>(0, (sum, p) => sum + p.durationSeconds)}s cycle',
          style: const TextStyle(
            color: AppTokens.muted,
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }

  List<Widget> _buildPhaseList(ThemeData theme, Signal signal) {
    if (signal.phases.isEmpty) {
      return [
        const Padding(
          padding: EdgeInsets.symmetric(vertical: AppTokens.spaceMd),
          child: EmptyState(
            icon: Icons.alt_route_rounded,
            title: 'No Phases Configured',
            message: 'This signal controller does not have configured cycle intervals.',
          ),
        ),
      ];
    }

    return signal.phases.map((phase) {
      final isCurrent = phase.isActive || phase.name == signal.currentPhase;

      return Padding(
        padding: const EdgeInsets.only(bottom: AppTokens.spaceSm),
        child: AppCard(
          padding: const EdgeInsets.symmetric(
            horizontal: AppTokens.spaceMd,
            vertical: AppTokens.spaceSm,
          ),
          child: Row(
            children: [
              Container(
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                  color: isCurrent
                      ? phase.color.withAlpha(40)
                      : AppTokens.surface,
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: isCurrent ? phase.color : AppTokens.borderDark,
                    width: isCurrent ? 2 : 1,
                  ),
                ),
                child: Center(
                  child: Text(
                    '${phase.phaseOrder}',
                    style: TextStyle(
                      color: isCurrent ? phase.color : AppTokens.muted,
                      fontWeight: FontWeight.w700,
                      fontSize: 12,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: AppTokens.spaceMd),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            phase.name,
                            style: TextStyle(
                              color: isCurrent
                                  ? AppTokens.textPrimary
                                  : AppTokens.muted,
                              fontWeight: isCurrent
                                  ? FontWeight.w700
                                  : FontWeight.w500,
                              fontSize: 13,
                            ),
                          ),
                        ),
                        if (isCurrent)
                          const AppBadge(
                            label: 'ACTIVE',
                            color: AppTokens.teal,
                          ),
                      ],
                    ),
                    const SizedBox(height: 2),
                    Row(
                      children: [
                        Container(
                          width: 8,
                          height: 8,
                          decoration: BoxDecoration(
                            color: phase.color,
                            shape: BoxShape.circle,
                          ),
                        ),
                        const SizedBox(width: 4),
                        Text(
                          phase.state.label,
                          style: TextStyle(
                            color: phase.color,
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        const SizedBox(width: AppTokens.spaceMd),
                        Text(
                          'Duration: ${phase.durationSeconds}s',
                          style: const TextStyle(
                            color: AppTokens.muted,
                            fontSize: 11,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
    }).toList();
  }

  Widget _buildOverrideSection(ThemeData theme, Signal signal, bool isAnalyst) {
    if (isAnalyst) {
      return Container(
        padding: const EdgeInsets.all(AppTokens.spaceMd),
        decoration: BoxDecoration(
          color: AppTokens.amber.withAlpha(20),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppTokens.amber.withAlpha(80)),
        ),
        child: const Row(
          children: [
            Icon(Icons.lock_outline_rounded, color: AppTokens.amber, size: 24),
            SizedBox(width: AppTokens.spaceMd),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Read-Only Access',
                    style: TextStyle(
                      color: AppTokens.textPrimary,
                      fontWeight: FontWeight.w700,
                      fontSize: 13,
                    ),
                  ),
                  SizedBox(height: 2),
                  Text(
                    'Operators with Analyst role cannot execute signal phase overrides or modify timings.',
                    style: TextStyle(color: AppTokens.muted, fontSize: 12),
                  ),
                ],
              ),
            ),
          ],
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
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: AppTokens.danger.withAlpha(25),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Icon(
                  Icons.pan_tool_rounded,
                  color: AppTokens.danger,
                  size: 20,
                ),
              ),
              const SizedBox(width: AppTokens.spaceSm),
              Text(
                'Manual Signal Override',
                style: theme.textTheme.titleSmall?.copyWith(
                  color: AppTokens.textPrimary,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceSm),
          const Text(
            'Traffic Officers & Admins may manually command a phase extension or emergency state hold. Every manual override action is recorded in the municipal audit log.',
            style: TextStyle(color: AppTokens.muted, fontSize: 12),
          ),
          const SizedBox(height: AppTokens.spaceMd),
          AppButton(
            text: 'Configure Phase Override',
            icon: Icons.tune_rounded,
            isLoading: _isSubmittingOverride,
            isFullWidth: true,
            onPressed: () => _openOverrideModal(signal),
          ),
        ],
      ),
    );
  }

  void _openOverrideModal(Signal signal) {
    String selectedPhase = signal.phases.isNotEmpty
        ? signal.phases.first.name
        : 'All-Red Hold';
    int? selectedPhaseId =
        signal.phases.isNotEmpty ? signal.phases.first.id : null;
    double durationSeconds = 30.0;
    String selectedState = 'green';
    final reasonController = TextEditingController(text: 'Congestion relief');

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppTokens.card,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (modalCtx) {
        return StatefulBuilder(
          builder: (ctx, setModalState) {
            return Padding(
              padding: EdgeInsets.only(
                left: AppTokens.spaceLg,
                right: AppTokens.spaceLg,
                top: AppTokens.spaceLg,
                bottom: MediaQuery.of(modalCtx).viewInsets.bottom + AppTokens.spaceLg,
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text(
                        'Manual Phase Override',
                        style: TextStyle(
                          color: AppTokens.textPrimary,
                          fontSize: 18,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.close_rounded, color: AppTokens.muted),
                        onPressed: () => Navigator.of(modalCtx).pop(),
                      ),
                    ],
                  ),
                  const SizedBox(height: AppTokens.spaceSm),
                  const Text(
                    'Select target phase and commanded duration:',
                    style: TextStyle(color: AppTokens.muted, fontSize: 12),
                  ),
                  const SizedBox(height: AppTokens.spaceMd),
                  const Text(
                    'Target Phase Interval',
                    style: TextStyle(
                      color: AppTokens.textPrimary,
                      fontWeight: FontWeight.w600,
                      fontSize: 13,
                    ),
                  ),
                  const SizedBox(height: AppTokens.spaceXs),
                  DropdownButtonFormField<String>(
                    initialValue: selectedPhase,
                    dropdownColor: AppTokens.card,
                    decoration: InputDecoration(
                      filled: true,
                      fillColor: AppTokens.surface,
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(10),
                        borderSide: const BorderSide(color: AppTokens.borderDark),
                      ),
                    ),
                    items: [
                      if (signal.phases.isEmpty)
                        const DropdownMenuItem(
                          value: 'All-Red Hold',
                          child: Text('All-Red Hold'),
                        )
                      else
                        ...signal.phases.map(
                          (p) => DropdownMenuItem(
                            value: p.name,
                            child: Text(
                              '${p.name} (${p.state.label})',
                              style: const TextStyle(color: AppTokens.textPrimary),
                            ),
                          ),
                        ),
                    ],
                    onChanged: (val) {
                      if (val != null) {
                        setModalState(() {
                          selectedPhase = val;
                          final match = signal.phases.firstWhere(
                            (p) => p.name == val,
                            orElse: () => signal.phases.first,
                          );
                          selectedPhaseId = match.id;
                          selectedState = match.state.name;
                        });
                      }
                    },
                  ),
                  const SizedBox(height: AppTokens.spaceMd),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text(
                        'Override Duration',
                        style: TextStyle(
                          color: AppTokens.textPrimary,
                          fontWeight: FontWeight.w600,
                          fontSize: 13,
                        ),
                      ),
                      Text(
                        '${durationSeconds.toInt()} seconds',
                        style: const TextStyle(
                          color: AppTokens.teal,
                          fontWeight: FontWeight.w700,
                          fontSize: 14,
                        ),
                      ),
                    ],
                  ),
                  Slider(
                    value: durationSeconds,
                    min: 10,
                    max: 120,
                    divisions: 11,
                    activeColor: AppTokens.teal,
                    inactiveColor: AppTokens.surface,
                    onChanged: (val) {
                      setModalState(() => durationSeconds = val);
                    },
                  ),
                  const SizedBox(height: AppTokens.spaceSm),
                  const Text(
                    'Operational Reason / Rationale',
                    style: TextStyle(
                      color: AppTokens.textPrimary,
                      fontWeight: FontWeight.w600,
                      fontSize: 13,
                    ),
                  ),
                  const SizedBox(height: AppTokens.spaceXs),
                  TextField(
                    controller: reasonController,
                    decoration: InputDecoration(
                      hintText: 'Enter justification (e.g. queue discharge)...',
                      hintStyle: const TextStyle(color: AppTokens.muted, fontSize: 13),
                      filled: true,
                      fillColor: AppTokens.surface,
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(10),
                        borderSide: const BorderSide(color: AppTokens.borderDark),
                      ),
                    ),
                  ),
                  const SizedBox(height: AppTokens.spaceLg),
                  AppButton(
                    text: 'Confirm & Command Override',
                    icon: Icons.check_circle_outline_rounded,
                    isFullWidth: true,
                    onPressed: () {
                      Navigator.of(modalCtx).pop();
                      _showConfirmOverrideDialog(
                        signal: signal,
                        phase: selectedPhase,
                        phaseId: selectedPhaseId,
                        durationSeconds: durationSeconds.toInt(),
                        state: selectedState,
                        reason: reasonController.text.trim(),
                      );
                    },
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }

  void _showConfirmOverrideDialog({
    required Signal signal,
    required String phase,
    required int? phaseId,
    required int durationSeconds,
    required String state,
    required String reason,
  }) {
    showDialog(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        backgroundColor: AppTokens.card,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: AppTokens.borderDark),
        ),
        title: const Row(
          children: [
            Icon(Icons.warning_amber_rounded, color: AppTokens.amber),
            SizedBox(width: AppTokens.spaceSm),
            Text('Audit Trail Confirmation'),
          ],
        ),
        content: Text(
          'This action is an AI supervisory override and will be permanently recorded in the municipal audit trail.\n\nCommand override for "$phase" for $durationSeconds seconds?',
          style: const TextStyle(color: AppTokens.textPrimary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogCtx).pop(),
            child: const Text('Cancel', style: TextStyle(color: AppTokens.muted)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: AppTokens.teal,
              foregroundColor: AppTokens.ink,
            ),
            onPressed: () async {
              Navigator.of(dialogCtx).pop();
              await _executeOverride(
                signalId: signal.id,
                phase: phase,
                phaseId: phaseId,
                durationSeconds: durationSeconds,
                state: state,
                reason: reason,
              );
            },
            child: const Text('Execute Override', style: TextStyle(fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    );
  }

  Future<void> _executeOverride({
    required int signalId,
    required String phase,
    required int? phaseId,
    required int durationSeconds,
    required String state,
    required String reason,
  }) async {
    setState(() => _isSubmittingOverride = true);
    try {
      final signalService = ref.read(signalServiceProvider);
      final updatedSignal = await signalService.overrideSignal(
        signalId,
        phase: phase,
        phaseId: phaseId,
        durationSeconds: durationSeconds,
        state: state,
        reason: reason,
      );

      if (mounted) {
        setState(() {
          _signal = updatedSignal;
          _isSubmittingOverride = false;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            backgroundColor: AppTokens.success,
            content: Text(
              'Signal override successfully commanded and recorded in audit log.',
            ),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        setState(() => _isSubmittingOverride = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: AppTokens.danger,
            content: Text('Override failed: $e'),
          ),
        );
      }
    }
  }
}
