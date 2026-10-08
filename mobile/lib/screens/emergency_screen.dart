import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/emergency_event.dart';
import '../models/junction.dart';
import '../providers/realtime_providers.dart';
import '../services/api_client.dart';
import '../services/auth_service.dart';
import '../services/emergency_service.dart';
import '../services/junction_service.dart';
import '../services/realtime_protocol.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_card.dart';
import '../widgets/empty_state.dart';
import '../widgets/error_state.dart';
import '../widgets/loading_state.dart';
import '../widgets/offline_banner.dart';

/// Emergency vehicle preemption management and green wave corridor orchestrator.
class EmergencyScreen extends ConsumerStatefulWidget {
  const EmergencyScreen({super.key});

  @override
  ConsumerState<EmergencyScreen> createState() => _EmergencyScreenState();
}

class _EmergencyScreenState extends ConsumerState<EmergencyScreen> {
  final ScrollController _scrollController = ScrollController();
  final List<EmergencyEvent> _events = [];
  bool _isLoading = true;
  bool _isLoadingMore = false;
  String? _errorMessage;
  int _page = 1;
  int _totalPages = 1;
  String? _statusFilter;
  Timer? _debounceTimer;
  bool _isSyncing = false;

  @override
  void initState() {
    super.initState();
    _loadInitialEvents();
    _scrollController.addListener(_onScroll);
  }

  @override
  void dispose() {
    _debounceTimer?.cancel();
    _scrollController.removeListener(_onScroll);
    _scrollController.dispose();
    super.dispose();
  }

  void _scheduleDebouncedRefresh() {
    _debounceTimer?.cancel();
    _debounceTimer = Timer(const Duration(milliseconds: 1500), () {
      if (mounted && !_isSyncing) {
        _loadInitialEvents(isBackgroundRefresh: true);
      }
    });
  }

  void _onScroll() {
    if (_scrollController.position.pixels >=
            _scrollController.position.maxScrollExtent - 200 &&
        !_isLoadingMore &&
        _page < _totalPages) {
      _loadMoreEvents();
    }
  }

  Future<void> _loadInitialEvents({bool isBackgroundRefresh = false}) async {
    if (_isSyncing) return;
    _isSyncing = true;
    if (!isBackgroundRefresh) {
      setState(() {
        _page = 1;
        _isLoading = true;
        _errorMessage = null;
      });
    }

    try {
      final service = ref.read(emergencyServiceProvider);
      final paged = await service.getEmergencyEvents(
        page: 1,
        perPage: 20,
        status: _statusFilter,
      );
      if (mounted) {
        setState(() {
          _page = 1;
          _events.clear();
          _events.addAll(paged.items);
          _totalPages = paged.pages;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoading = false;
          _errorMessage =
              e is ApiException ? e.message : 'Failed to query emergency events: $e';
        });
      }
    } finally {
      _isSyncing = false;
    }
  }

  Future<void> _loadMoreEvents() async {
    if (_isLoadingMore) return;
    setState(() {
      _isLoadingMore = true;
    });

    try {
      final service = ref.read(emergencyServiceProvider);
      final nextPage = _page + 1;
      final paged = await service.getEmergencyEvents(
        page: nextPage,
        perPage: 20,
        status: _statusFilter,
      );
      if (mounted) {
        setState(() {
          _page = nextPage;
          _events.addAll(paged.items);
          _totalPages = paged.pages;
          _isLoadingMore = false;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _isLoadingMore = false;
        });
      }
    }
  }

  void _openCreateEmergencySheet() {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Theme.of(context).colorScheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
        side: BorderSide(color: AppTokens.borderOf(context)),
      ),
      builder: (ctx) {
        return _CreateEmergencyFormSheet(
          onCreated: () {
            Navigator.of(ctx).pop();
            _loadInitialEvents();
          },
        );
      },
    );
  }

  Future<void> _handlePrioritize(EmergencyEvent event) async {
    // Show destination picker dialog
    final junctionsPaged =
        await ref.read(junctionServiceProvider).getJunctions(perPage: 50);
    final junctions = junctionsPaged.items;

    if (!mounted) return;

    final destinationId = await showDialog<int?>(
      context: context,
      builder: (ctx) {
        int? selectedId = junctions.isNotEmpty ? junctions.first.id : null;
        return StatefulBuilder(
          builder: (ctx, setDialogState) {
            return AlertDialog(
              backgroundColor: Theme.of(context).colorScheme.surface,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(16),
                side: BorderSide(color: AppTokens.borderOf(context)),
              ),
              title: Row(
                children: [
                  const Icon(Icons.alt_route_rounded, color: AppTokens.teal),
                  const SizedBox(width: AppTokens.spaceSm),
                  Text('Prioritize #${event.id}'),
                ],
              ),
              content: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Select Destination Junction for Green Corridor:',
                    style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 13),
                  ),
                  const SizedBox(height: AppTokens.spaceMd),
                  DropdownButtonFormField<int>(
                    initialValue: selectedId,
                    dropdownColor: Theme.of(context).colorScheme.surface,
                    decoration: InputDecoration(
                      filled: true,
                      fillColor: Theme.of(context).colorScheme.surface,
                    ),
                    items: junctions.map((j) {
                      return DropdownMenuItem<int>(
                        value: j.id,
                        child: Text('${j.name} (#${j.id})'),
                      );
                    }).toList(),
                    onChanged: (val) {
                      setDialogState(() {
                        selectedId = val;
                      });
                    },
                  ),
                ],
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(ctx).pop(null),
                  child: Text('Cancel',
                      style: TextStyle(color: AppTokens.mutedOf(context))),
                ),
                ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppTokens.teal,
                    foregroundColor: Theme.of(context).brightness == Brightness.dark
                        ? AppTokens.ink
                        : Colors.white,
                  ),
                  onPressed: () => Navigator.of(ctx).pop(selectedId),
                  child: const Text('Calculate Corridor'),
                ),
              ],
            );
          },
        );
      },
    );

    if (destinationId == null) return;

    // Show loading dialog
    if (!mounted) return;
    showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (_) => const Center(
        child: CircularProgressIndicator(color: AppTokens.teal),
      ),
    );

    try {
      final service = ref.read(emergencyServiceProvider);
      final prioritizeResult = await service.prioritize(
        emergencyEventId: event.id,
        destinationIntersectionId: destinationId,
      );

      if (mounted) {
        Navigator.of(context).pop(); // dismiss loading
        _showCorridorPlanSheet(prioritizeResult.corridorPlan, event);
        _loadInitialEvents();
      }
    } catch (e) {
      if (mounted) {
        Navigator.of(context).pop(); // dismiss loading
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: AppTokens.danger,
            content: Text(
              e is ApiException ? e.message : 'Corridor optimization failed: $e',
              style: const TextStyle(color: Colors.white),
            ),
          ),
        );
      }
    }
  }

  void _showCorridorPlanSheet(CorridorPlan plan, EmergencyEvent event) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Theme.of(context).colorScheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
        side: BorderSide(color: AppTokens.borderOf(context)),
      ),
      builder: (ctx) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(AppTokens.spaceLg),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Center(
                  child: Container(
                    width: 36,
                    height: 4,
                    decoration: BoxDecoration(
                      color: AppTokens.mutedOf(context).withAlpha(80),
                      borderRadius: BorderRadius.circular(2),
                    ),
                  ),
                ),
                const SizedBox(height: AppTokens.spaceMd),
                Row(
                  children: [
                    const Icon(Icons.route_rounded,
                        color: AppTokens.teal, size: 24),
                    const SizedBox(width: AppTokens.spaceSm),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Green Corridor Recommendation',
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w700,
                              color: Theme.of(context).colorScheme.onSurface,
                            ),
                          ),
                          Text(
                            'Corridor ID: ${plan.corridorId}',
                            style: TextStyle(
                                color: AppTokens.mutedOf(context), fontSize: 11),
                          ),
                        ],
                      ),
                    ),
                    AppBadge(
                      label: '${plan.estimatedMinutes.toStringAsFixed(1)} MIN',
                      color: AppTokens.teal,
                    ),
                  ],
                ),
                const SizedBox(height: AppTokens.spaceMd),
                Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: AppTokens.amber.withAlpha(25),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: AppTokens.amber.withAlpha(80)),
                  ),
                  child: const Text(
                    'AI advisory route preemption plan. Signals synchronized along the corridor.',
                    style: TextStyle(color: AppTokens.amber, fontSize: 11),
                  ),
                ),
                const SizedBox(height: AppTokens.spaceMd),
                Text(
                  'Path: Junctions ${plan.path.join(" -> ")}',
                  style: TextStyle(
                    fontWeight: FontWeight.w600,
                    color: Theme.of(context).colorScheme.onSurface,
                    fontSize: 13,
                  ),
                ),
                const SizedBox(height: AppTokens.spaceMd),
                Text(
                  'Planned Signal Preemption Directives:',
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: Theme.of(context).colorScheme.onSurface,
                  ),
                ),
                const SizedBox(height: 6),
                ConstrainedBox(
                  constraints: const BoxConstraints(maxHeight: 220),
                  child: ListView.separated(
                    shrinkWrap: true,
                    itemCount: plan.signalActions.length,
                    separatorBuilder: (_, _) => Divider(
                      height: 1,
                      color: AppTokens.borderOf(context),
                    ),
                    itemBuilder: (context, idx) {
                      final action = plan.signalActions[idx];
                      return Padding(
                        padding: const EdgeInsets.symmetric(vertical: 8),
                        child: Row(
                          children: [
                            Container(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 8, vertical: 4),
                              decoration: BoxDecoration(
                                color: AppTokens.teal.withAlpha(20),
                                borderRadius: BorderRadius.circular(6),
                              ),
                              child: Text(
                                '#${action.intersectionId}',
                                style: const TextStyle(
                                  color: AppTokens.teal,
                                  fontWeight: FontWeight.w700,
                                  fontSize: 12,
                                ),
                              ),
                            ),
                            const SizedBox(width: AppTokens.spaceSm),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    action.action.toUpperCase(),
                                    style: TextStyle(
                                      fontWeight: FontWeight.w700,
                                      color: Theme.of(context).colorScheme.onSurface,
                                      fontSize: 12,
                                    ),
                                  ),
                                  Text(
                                    action.reason,
                                    style: TextStyle(
                                      color: AppTokens.mutedOf(context),
                                      fontSize: 11,
                                    ),
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ],
                              ),
                            ),
                            Text(
                              '${action.durationSeconds.toStringAsFixed(0)}s',
                              style: const TextStyle(
                                color: AppTokens.amber,
                                fontWeight: FontWeight.w600,
                                fontSize: 12,
                              ),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
                ),
                const SizedBox(height: AppTokens.spaceMd),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppTokens.teal,
                      foregroundColor: Theme.of(context).brightness == Brightness.dark
                          ? AppTokens.ink
                          : Colors.white,
                    ),
                    onPressed: () => Navigator.of(ctx).pop(),
                    child: const Text('Acknowledge Plan'),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Future<void> _handleRestore(EmergencyEvent event) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: Theme.of(context).colorScheme.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: BorderSide(color: AppTokens.borderOf(context)),
        ),
        title: const Text('Restore Signal Coordination?'),
        content: Text(
          'Conclude preemption for ${event.vehicleTypeDisplay} (#${event.id}) and return controllers to standard cyclic operations?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: Text('Cancel', style: TextStyle(color: AppTokens.mutedOf(context))),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: AppTokens.success,
              foregroundColor: Colors.white,
            ),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Restore Signals'),
          ),
        ],
      ),
    );

    if (confirmed != true) return;

    try {
      final service = ref.read(emergencyServiceProvider);
      final res = await service.restore(emergencyEventId: event.id);

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: AppTokens.success,
            content: Text(
              'Signals restored to standard plan: ${res.reason}',
              style: const TextStyle(color: Colors.white),
            ),
          ),
        );
        _loadInitialEvents();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: AppTokens.danger,
            content: Text(
              e is ApiException ? e.message : 'Signal restoration failed: $e',
              style: const TextStyle(color: Colors.white),
            ),
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    // Real-time WebSocket invalidation: on emergency.created and emergency.updated,
    // refresh emergency preemption events (debounced to avoid burst storms)
    for (final topic in const [
      RealtimeTopics.emergencyCreated,
      RealtimeTopics.emergencyUpdated,
    ]) {
      ref.listen(realtimeTopicEventProvider(topic), (_, next) {
        if (next.hasValue) {
          _scheduleDebouncedRefresh();
        }
      });
    }

    final user = ref.watch(currentUserProvider);
    final isAnalyst = user?.isAnalyst ?? false;
    final canWrite = (user?.canWrite ?? false) && !isAnalyst;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Emergency Green Corridors'),
        actions: [
          IconButton(
            tooltip: 'Reload Events',
            icon: const Icon(Icons.refresh_rounded),
            onPressed: _loadInitialEvents,
          ),
        ],
      ),
      floatingActionButton: canWrite
          ? FloatingActionButton.extended(
              onPressed: _openCreateEmergencySheet,
              backgroundColor: AppTokens.danger,
              foregroundColor: Colors.white,
              icon: const Icon(Icons.add_moderator_rounded),
              label: const Text(
                'New Emergency',
                style: TextStyle(fontWeight: FontWeight.w700),
              ),
            )
          : null,
      body: RefreshIndicator(
        onRefresh: _loadInitialEvents,
        color: AppTokens.teal,
        backgroundColor: Theme.of(context).colorScheme.surface,
        child: CustomScrollView(
          controller: _scrollController,
          physics: const AlwaysScrollableScrollPhysics(),
          slivers: [
            if (ref.watch(isOfflineProvider))
              const SliverToBoxAdapter(child: OfflineBanner()),
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.all(AppTokens.spaceMd),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _buildSafetyBanner(),
                    const SizedBox(height: AppTokens.spaceSm),
                    if (isAnalyst) ...[
                      _buildAnalystBanner(),
                      const SizedBox(height: AppTokens.spaceSm),
                    ],
                    _buildStatusFilterRow(),
                  ],
                ),
              ),
            ),
            _buildListContent(canWrite),
          ],
        ),
      ),
    );
  }

  Widget _buildSafetyBanner() {
    return Container(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      decoration: BoxDecoration(
        color: AppTokens.amber.withAlpha(25),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTokens.amber.withAlpha(90)),
      ),
      child: Row(
        children: [
          const Icon(Icons.shield_outlined, color: AppTokens.amber, size: 24),
          const SizedBox(width: AppTokens.spaceMd),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'AI recommendation — does not control physical hardware',
                  style: TextStyle(
                    fontWeight: FontWeight.w700,
                    color: AppTokens.amber,
                    fontSize: 13,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  'Preemption outputs are supervisory proposals requiring authorized field translation.',
                  style: TextStyle(
                    color: Theme.of(context).colorScheme.onSurface,
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAnalystBanner() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppTokens.borderOf(context)),
      ),
      child: Row(
        children: [
          Icon(Icons.lock_outline_rounded, color: AppTokens.mutedOf(context), size: 16),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              'Analyst mode: Emergency corridors and signal preemption controls are read-only.',
              style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 11),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildStatusFilterRow() {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          _buildFilterChip('All', null),
          const SizedBox(width: AppTokens.spaceSm),
          _buildFilterChip('Active', 'active'),
          const SizedBox(width: AppTokens.spaceSm),
          _buildFilterChip('Dispatched', 'dispatched'),
          const SizedBox(width: AppTokens.spaceSm),
          _buildFilterChip('On Scene', 'on_scene'),
          const SizedBox(width: AppTokens.spaceSm),
          _buildFilterChip('Resolved', 'resolved'),
        ],
      ),
    );
  }

  Widget _buildFilterChip(String label, String? status) {
    final isSelected = _statusFilter == status;
    return ChoiceChip(
      label: Text(label),
      selected: isSelected,
      onSelected: (_) {
        setState(() => _statusFilter = status);
        _loadInitialEvents();
      },
      selectedColor: AppTokens.teal.withAlpha(35),
      backgroundColor: Theme.of(context).colorScheme.surface,
      labelStyle: TextStyle(
        color: isSelected ? AppTokens.teal : AppTokens.mutedOf(context),
        fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
        fontSize: 11,
      ),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: BorderSide(
          color: isSelected ? AppTokens.teal.withAlpha(90) : AppTokens.borderOf(context),
        ),
      ),
    );
  }

  Widget _buildListContent(bool canWrite) {
    if (_isLoading) {
      return const SliverToBoxAdapter(
        child: Padding(
          padding: EdgeInsets.all(AppTokens.spaceXl),
          child: LoadingState(
            message: 'Loading active emergency transit events...',
            subtitle: 'Checking audio-visual sirens and dispatch sensors',
          ),
        ),
      );
    }

    if (_errorMessage != null && _events.isEmpty) {
      return SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.all(AppTokens.spaceMd),
          child: ErrorState(
            title: 'Emergency Feed Unavailable',
            message: _errorMessage!,
            onRetry: _loadInitialEvents,
          ),
        ),
      );
    }

    if (_events.isEmpty) {
      return const SliverToBoxAdapter(
        child: Padding(
          padding: EdgeInsets.all(AppTokens.spaceMd),
          child: EmptyState(
            icon: Icons.emergency_rounded,
            title: 'No Emergency Events',
            message:
                'No priority emergency vehicles currently detected or dispatched across the network.',
          ),
        ),
      );
    }

    return SliverPadding(
      padding: const EdgeInsets.symmetric(horizontal: AppTokens.spaceMd),
      sliver: SliverList(
        delegate: SliverChildBuilderDelegate(
          (context, index) {
            if (index == _events.length) {
              if (_isLoadingMore) {
                return const Padding(
                  padding: EdgeInsets.symmetric(vertical: AppTokens.spaceMd),
                  child: Center(
                    child: SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        valueColor: AlwaysStoppedAnimation(AppTokens.teal),
                      ),
                    ),
                  ),
                );
              }
              return const SizedBox(height: 72);
            }

            final event = _events[index];
            return Padding(
              padding: const EdgeInsets.only(bottom: AppTokens.spaceSm),
              child: _buildEventCard(event, canWrite),
            );
          },
          childCount: _events.length + 1,
        ),
      ),
    );
  }

  Widget _buildEventCard(EmergencyEvent event, bool canWrite) {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: event.priorityColor.withAlpha(25),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: event.priorityColor.withAlpha(80)),
                ),
                child: Icon(event.vehicleIcon,
                    color: event.priorityColor, size: 22),
              ),
              const SizedBox(width: AppTokens.spaceMd),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      event.vehicleTypeDisplay,
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: Theme.of(context).colorScheme.onSurface,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      'Event #${event.id} • ${event.detectedAt.toLocal().toString().split(".")[0]}',
                      style:
                          TextStyle(color: AppTokens.mutedOf(context), fontSize: 11),
                    ),
                  ],
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  AppBadge(
                    label: event.priorityLabel.toUpperCase(),
                    color: event.priorityColor,
                  ),
                  const SizedBox(height: 4),
                  AppBadge(
                    label: event.status.toUpperCase(),
                    color: event.statusColor,
                  ),
                ],
              ),
            ],
          ),
          if (event.intersectionId != null) ...[
            const SizedBox(height: AppTokens.spaceSm),
            Row(
              children: [
                const Icon(Icons.traffic_rounded,
                    size: 14, color: AppTokens.teal),
                const SizedBox(width: 4),
                Text(
                  'Associated Junction #${event.intersectionId}',
                  style: const TextStyle(
                      color: AppTokens.teal,
                      fontSize: 12,
                      fontWeight: FontWeight.w600),
                ),
              ],
            ),
          ],
          if (canWrite) ...[
            const SizedBox(height: AppTokens.spaceMd),
            Row(
              children: [
                if (!event.isResolved) ...[
                  Expanded(
                    child: ElevatedButton.icon(
                      icon: const Icon(Icons.alt_route_rounded, size: 16),
                      label: const Text('Prioritize Corridor'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppTokens.teal,
                        foregroundColor: Theme.of(context).brightness == Brightness.dark
                            ? AppTokens.ink
                            : Colors.white,
                      ),
                      onPressed: () => _handlePrioritize(event),
                    ),
                  ),
                  const SizedBox(width: AppTokens.spaceSm),
                  Expanded(
                    child: OutlinedButton.icon(
                      icon: const Icon(Icons.restore_rounded, size: 16),
                      label: const Text('Restore Signals'),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: AppTokens.amber,
                        side: const BorderSide(color: AppTokens.amber),
                      ),
                      onPressed: () => _handleRestore(event),
                    ),
                  ),
                ] else ...[
                  Expanded(
                    child: Container(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                        color: AppTokens.surface,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: const Text(
                        'Event Resolved — Standard Plan Active',
                        style: TextStyle(
                          color: AppTokens.success,
                          fontWeight: FontWeight.w600,
                          fontSize: 12,
                        ),
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ],
        ],
      ),
    );
  }
}

/// Form sheet to dispatch or log a new emergency vehicle transit event.
class _CreateEmergencyFormSheet extends ConsumerStatefulWidget {
  const _CreateEmergencyFormSheet({required this.onCreated});

  final VoidCallback onCreated;

  @override
  ConsumerState<_CreateEmergencyFormSheet> createState() =>
      _CreateEmergencyFormSheetState();
}

class _CreateEmergencyFormSheetState
    extends ConsumerState<_CreateEmergencyFormSheet> {
  final _formKey = GlobalKey<FormState>();

  String _vehicleType = 'ambulance';
  int _priority = 1;
  int? _intersectionId;
  List<Junction> _junctions = [];
  bool _isLoadingJunctions = true;
  bool _isSubmitting = false;
  String? _submitError;

  @override
  void initState() {
    super.initState();
    _loadJunctions();
  }

  Future<void> _loadJunctions() async {
    try {
      final service = ref.read(junctionServiceProvider);
      final paged = await service.getJunctions(perPage: 50);
      if (mounted) {
        setState(() {
          _junctions = paged.items;
          _isLoadingJunctions = false;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _isLoadingJunctions = false;
        });
      }
    }
  }

  Future<void> _submit() async {
    setState(() {
      _isSubmitting = true;
      _submitError = null;
    });

    try {
      final service = ref.read(emergencyServiceProvider);
      await service.createEmergencyEvent(
        vehicleType: _vehicleType,
        priority: _priority,
        intersectionId: _intersectionId,
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            backgroundColor: AppTokens.success,
            content: Text('Emergency vehicle transit event created'),
          ),
        );
        widget.onCreated();
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isSubmitting = false;
          _submitError =
              e is ApiException ? e.message : 'Failed to register emergency event: $e';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom,
        left: AppTokens.spaceMd,
        right: AppTokens.spaceMd,
        top: AppTokens.spaceLg,
      ),
      child: SafeArea(
        child: SingleChildScrollView(
          child: Form(
            key: _formKey,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Center(
                  child: Container(
                    width: 36,
                    height: 4,
                    decoration: BoxDecoration(
                      color: AppTokens.mutedOf(context).withAlpha(80),
                      borderRadius: BorderRadius.circular(2),
                    ),
                  ),
                ),
                const SizedBox(height: AppTokens.spaceMd),
                Row(
                  children: [
                    const Icon(Icons.emergency_rounded, color: AppTokens.danger),
                    const SizedBox(width: AppTokens.spaceSm),
                    Text(
                      'Dispatch Emergency Vehicle',
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w700,
                        color: Theme.of(context).colorScheme.onSurface,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: AppTokens.spaceMd),
                if (_submitError != null) ...[
                  Container(
                    padding: const EdgeInsets.all(AppTokens.spaceSm),
                    decoration: BoxDecoration(
                      color: AppTokens.danger.withAlpha(25),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: AppTokens.danger.withAlpha(80)),
                    ),
                    child: Text(
                      _submitError!,
                      style:
                          const TextStyle(color: AppTokens.danger, fontSize: 12),
                    ),
                  ),
                  const SizedBox(height: AppTokens.spaceMd),
                ],
                Text(
                  'Vehicle Type',
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: Theme.of(context).colorScheme.onSurface,
                  ),
                ),
                const SizedBox(height: 6),
                Wrap(
                  spacing: AppTokens.spaceSm,
                  children: [
                    ('ambulance', 'Ambulance', Icons.medical_services_rounded),
                    ('fire_engine', 'Fire Engine', Icons.local_fire_department_rounded),
                    ('police', 'Police', Icons.local_police_rounded),
                    ('rescue', 'Rescue Unit', Icons.emergency_rounded),
                  ].map((v) {
                    final isSel = _vehicleType == v.$1;
                    return ChoiceChip(
                      avatar: Icon(v.$3, size: 14, color: isSel ? AppTokens.teal : AppTokens.mutedOf(context)),
                      label: Text(v.$2),
                      selected: isSel,
                      onSelected: (val) {
                        if (val) setState(() => _vehicleType = v.$1);
                      },
                      selectedColor: AppTokens.teal.withAlpha(35),
                      backgroundColor: Theme.of(context).colorScheme.surface,
                      labelStyle: TextStyle(
                        color: isSel ? AppTokens.teal : AppTokens.mutedOf(context),
                        fontWeight: isSel ? FontWeight.w700 : FontWeight.w500,
                        fontSize: 11,
                      ),
                    );
                  }).toList(),
                ),
                const SizedBox(height: AppTokens.spaceMd),
                Text(
                  'Priority Level',
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: Theme.of(context).colorScheme.onSurface,
                  ),
                ),
                const SizedBox(height: 6),
                Wrap(
                  spacing: AppTokens.spaceSm,
                  children: [
                    (1, 'P1 - Critical'),
                    (2, 'P2 - High'),
                    (3, 'P3 - Medium'),
                    (4, 'P4 - Low'),
                  ].map((p) {
                    final isSel = _priority == p.$1;
                    return ChoiceChip(
                      label: Text(p.$2),
                      selected: isSel,
                      onSelected: (val) {
                        if (val) setState(() => _priority = p.$1);
                      },
                      selectedColor: AppTokens.danger.withAlpha(35),
                      backgroundColor: Theme.of(context).colorScheme.surface,
                      labelStyle: TextStyle(
                        color: isSel ? AppTokens.danger : AppTokens.mutedOf(context),
                        fontWeight: isSel ? FontWeight.w700 : FontWeight.w500,
                        fontSize: 11,
                      ),
                    );
                  }).toList(),
                ),
                const SizedBox(height: AppTokens.spaceMd),
                Text(
                  'Transit Origin Junction',
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: Theme.of(context).colorScheme.onSurface,
                  ),
                ),
                const SizedBox(height: 6),
                _isLoadingJunctions
                    ? const LinearProgressIndicator(color: AppTokens.teal)
                    : DropdownButtonFormField<int?>(
                        initialValue: _intersectionId,
                        dropdownColor: Theme.of(context).colorScheme.surface,
                        decoration: InputDecoration(
                          filled: true,
                          fillColor: Theme.of(context).colorScheme.surface,
                        ),
                        hint: const Text('Select origin junction'),
                        items: [
                          const DropdownMenuItem<int?>(
                            value: null,
                            child: Text('Auto-detect / Nearby sensor'),
                          ),
                          ..._junctions.map((j) => DropdownMenuItem<int?>(
                                value: j.id,
                                child: Text('${j.name} (${j.code})'),
                              )),
                        ],
                        onChanged: (val) {
                          setState(() => _intersectionId = val);
                        },
                      ),
                const SizedBox(height: AppTokens.spaceLg),
                SizedBox(
                  width: double.infinity,
                  height: 48,
                  child: ElevatedButton(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppTokens.danger,
                      foregroundColor: Colors.white,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                    ),
                    onPressed: _isSubmitting ? null : _submit,
                    child: _isSubmitting
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              valueColor: AlwaysStoppedAnimation(Colors.white),
                            ),
                          )
                        : const Text(
                            'Dispatch Emergency Event',
                            style: TextStyle(fontWeight: FontWeight.w700),
                          ),
                  ),
                ),
                const SizedBox(height: AppTokens.spaceLg),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
