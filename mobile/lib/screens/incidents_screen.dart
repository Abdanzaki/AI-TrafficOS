import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/incident.dart';
import '../models/junction.dart';
import '../providers/realtime_providers.dart';
import '../services/api_client.dart';
import '../services/auth_service.dart';
import '../services/incident_service.dart';
import '../services/junction_service.dart';
import '../services/realtime_protocol.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_card.dart';
import '../widgets/empty_state.dart';
import '../widgets/error_state.dart';
import '../widgets/loading_state.dart';
import '../widgets/offline_banner.dart';
import 'incident_detail_screen.dart';

/// Comprehensive incidents queue and lifecycle management screen.
class IncidentsScreen extends ConsumerStatefulWidget {
  const IncidentsScreen({super.key});

  @override
  ConsumerState<IncidentsScreen> createState() => _IncidentsScreenState();
}

class _IncidentsScreenState extends ConsumerState<IncidentsScreen> {
  final ScrollController _scrollController = ScrollController();
  final List<Incident> _incidents = [];
  bool _isLoading = true;
  bool _isLoadingMore = false;
  String? _errorMessage;
  int _page = 1;
  int _totalPages = 1;

  String? _statusFilter;
  String? _severityFilter;

  @override
  void initState() {
    super.initState();
    _loadInitialIncidents();
    _scrollController.addListener(_onScroll);
  }

  @override
  void dispose() {
    _scrollController.removeListener(_onScroll);
    _scrollController.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (_scrollController.position.pixels >=
            _scrollController.position.maxScrollExtent - 200 &&
        !_isLoadingMore &&
        _page < _totalPages) {
      _loadMoreIncidents();
    }
  }

  Future<void> _loadInitialIncidents({bool isBackgroundRefresh = false}) async {
    if (!isBackgroundRefresh) {
      setState(() {
        _page = 1;
        _isLoading = true;
        _errorMessage = null;
      });
    }

    try {
      final service = ref.read(incidentServiceProvider);
      final paged = await service.getIncidents(
        page: 1,
        perPage: 20,
        status: _statusFilter,
        severity: _severityFilter,
      );
      if (mounted) {
        setState(() {
          _page = 1;
          _incidents.clear();
          _incidents.addAll(paged.items);
          _totalPages = paged.pages;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoading = false;
          _errorMessage =
              e is ApiException ? e.message : 'Failed to query incidents: $e';
        });
      }
    }
  }

  Future<void> _loadMoreIncidents() async {
    if (_isLoadingMore) return;
    setState(() {
      _isLoadingMore = true;
    });

    try {
      final service = ref.read(incidentServiceProvider);
      final nextPage = _page + 1;
      final paged = await service.getIncidents(
        page: nextPage,
        perPage: 20,
        status: _statusFilter,
        severity: _severityFilter,
      );
      if (mounted) {
        setState(() {
          _page = nextPage;
          _incidents.addAll(paged.items);
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

  void _navigateToDetail(Incident incident) async {
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => IncidentDetailScreen(
          incidentId: incident.id,
          initialIncident: incident,
        ),
      ),
    );
    _loadInitialIncidents();
  }

  void _openCreateIncidentSheet() {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Theme.of(context).colorScheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
        side: BorderSide(color: AppTokens.borderOf(context)),
      ),
      builder: (ctx) {
        return _CreateIncidentFormSheet(
          onIncidentCreated: () {
            Navigator.of(ctx).pop();
            _loadInitialIncidents();
          },
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    // Real-time WebSocket invalidation: on incident.created and incident.updated,
    // refresh incident queue
    for (final topic in const [
      RealtimeTopics.incidentCreated,
      RealtimeTopics.incidentUpdated,
    ]) {
      ref.listen(realtimeTopicEventProvider(topic), (_, next) {
        if (next.hasValue) {
          _loadInitialIncidents(isBackgroundRefresh: true);
        }
      });
    }

    final user = ref.watch(currentUserProvider);
    final canWrite = (user?.canWrite ?? false) && !(user?.isAnalyst ?? false);

    return Scaffold(
      floatingActionButton: canWrite
          ? FloatingActionButton.extended(
              onPressed: _openCreateIncidentSheet,
              backgroundColor: AppTokens.teal,
              foregroundColor: Theme.of(context).brightness == Brightness.dark
                  ? AppTokens.ink
                  : Colors.white,
              icon: const Icon(Icons.add_alert_rounded),
              label: const Text(
                'Report Incident',
                style: TextStyle(fontWeight: FontWeight.w700),
              ),
            )
          : null,
      body: Column(
        children: [
          if (ref.watch(isOfflineProvider)) const OfflineBanner(),
          Expanded(
            child: RefreshIndicator(
              onRefresh: _loadInitialIncidents,
              color: AppTokens.teal,
              backgroundColor: Theme.of(context).colorScheme.surface,
              child: CustomScrollView(
                controller: _scrollController,
                physics: const AlwaysScrollableScrollPhysics(),
                slivers: [
                  SliverToBoxAdapter(
                    child: Padding(
                      padding: const EdgeInsets.all(AppTokens.spaceMd),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          _buildHeader(),
                          const SizedBox(height: AppTokens.spaceSm),
                          _buildStatusFilterRow(),
                          const SizedBox(height: AppTokens.spaceXs),
                          _buildSeverityFilterRow(),
                        ],
                      ),
                    ),
                  ),
                  _buildListContent(),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildHeader() {
    final theme = Theme.of(context);
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: AppTokens.amber.withAlpha(25),
              borderRadius: BorderRadius.circular(8),
            ),
            child: const Icon(
              Icons.warning_amber_rounded,
              color: AppTokens.amber,
              size: 20,
            ),
          ),
          const SizedBox(width: AppTokens.spaceSm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Incident Dispatch Queue',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: theme.colorScheme.onSurface,
                  ),
                ),
                Text(
                  'Active hazards, lane blockages & perception anomalies',
                  style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 11),
                ),
              ],
            ),
          ),
          IconButton(
            tooltip: 'Reload Incidents',
            icon: const Icon(
              Icons.refresh_rounded,
              color: AppTokens.teal,
              size: 20,
            ),
            onPressed: _loadInitialIncidents,
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
          _buildFilterChip(
            label: 'All Statuses',
            isSelected: _statusFilter == null,
            onSelected: () {
              setState(() => _statusFilter = null);
              _loadInitialIncidents();
            },
          ),
          const SizedBox(width: AppTokens.spaceSm),
          _buildFilterChip(
            label: 'Reported',
            isSelected: _statusFilter == 'reported',
            onSelected: () {
              setState(() => _statusFilter = 'reported');
              _loadInitialIncidents();
            },
          ),
          const SizedBox(width: AppTokens.spaceSm),
          _buildFilterChip(
            label: 'Acknowledged',
            isSelected: _statusFilter == 'acknowledged',
            onSelected: () {
              setState(() => _statusFilter = 'acknowledged');
              _loadInitialIncidents();
            },
          ),
          const SizedBox(width: AppTokens.spaceSm),
          _buildFilterChip(
            label: 'Resolved',
            isSelected: _statusFilter == 'resolved',
            onSelected: () {
              setState(() => _statusFilter = 'resolved');
              _loadInitialIncidents();
            },
          ),
        ],
      ),
    );
  }

  Widget _buildSeverityFilterRow() {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          _buildFilterChip(
            label: 'All Severities',
            isSelected: _severityFilter == null,
            activeColor: AppTokens.teal,
            onSelected: () {
              setState(() => _severityFilter = null);
              _loadInitialIncidents();
            },
          ),
          const SizedBox(width: AppTokens.spaceSm),
          _buildFilterChip(
            label: 'Low',
            isSelected: _severityFilter == 'low',
            activeColor: AppTokens.teal,
            onSelected: () {
              setState(() => _severityFilter = 'low');
              _loadInitialIncidents();
            },
          ),
          const SizedBox(width: AppTokens.spaceSm),
          _buildFilterChip(
            label: 'Medium',
            isSelected: _severityFilter == 'medium',
            activeColor: AppTokens.amber,
            onSelected: () {
              setState(() => _severityFilter = 'medium');
              _loadInitialIncidents();
            },
          ),
          const SizedBox(width: AppTokens.spaceSm),
          _buildFilterChip(
            label: 'High',
            isSelected: _severityFilter == 'high',
            activeColor: const Color(0xFFFF7A00),
            onSelected: () {
              setState(() => _severityFilter = 'high');
              _loadInitialIncidents();
            },
          ),
          const SizedBox(width: AppTokens.spaceSm),
          _buildFilterChip(
            label: 'Critical',
            isSelected: _severityFilter == 'critical',
            activeColor: AppTokens.danger,
            onSelected: () {
              setState(() => _severityFilter = 'critical');
              _loadInitialIncidents();
            },
          ),
        ],
      ),
    );
  }

  Widget _buildFilterChip({
    required String label,
    required bool isSelected,
    required VoidCallback onSelected,
    Color activeColor = AppTokens.teal,
  }) {
    final theme = Theme.of(context);
    return ChoiceChip(
      label: Text(label),
      selected: isSelected,
      onSelected: (_) => onSelected(),
      selectedColor: activeColor.withAlpha(35),
      backgroundColor: theme.colorScheme.surface,
      labelPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
      visualDensity: VisualDensity.standard,
      labelStyle: TextStyle(
        color: isSelected ? activeColor : AppTokens.mutedOf(context),
        fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
        fontSize: 12,
      ),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: BorderSide(
          color: isSelected ? activeColor.withAlpha(90) : theme.colorScheme.outline.withAlpha(60),
        ),
      ),
    );
  }

  Widget _buildListContent() {
    if (_isLoading) {
      return const SliverToBoxAdapter(
        child: Padding(
          padding: EdgeInsets.all(AppTokens.spaceXl),
          child: LoadingState(
            message: 'Loading active incident queue...',
            subtitle: 'Checking vision detections and operator alerts',
          ),
        ),
      );
    }

    if (_errorMessage != null && _incidents.isEmpty) {
      return SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.all(AppTokens.spaceMd),
          child: ErrorState(
            title: 'Queue Query Failed',
            message: _errorMessage!,
            onRetry: _loadInitialIncidents,
          ),
        ),
      );
    }

    if (_incidents.isEmpty) {
      return const SliverToBoxAdapter(
        child: Padding(
          padding: EdgeInsets.all(AppTokens.spaceMd),
          child: EmptyState(
            icon: Icons.verified_user_rounded,
            title: 'Zero Active Incidents',
            message:
                'All municipal corridors are flowing normally with no pending safety alerts.',
          ),
        ),
      );
    }

    return SliverPadding(
      padding: const EdgeInsets.symmetric(horizontal: AppTokens.spaceMd),
      sliver: SliverList(
        delegate: SliverChildBuilderDelegate(
          (context, index) {
            if (index == _incidents.length) {
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
              return const SizedBox(height: 72); // FAB spacing
            }

            final inc = _incidents[index];
            return Padding(
              padding: const EdgeInsets.only(bottom: AppTokens.spaceSm),
              child: _buildIncidentRow(inc),
            );
          },
          childCount: _incidents.length + 1,
        ),
      ),
    );
  }

  Widget _buildIncidentRow(Incident incident) {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      onTap: () => _navigateToDetail(incident),
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
                  incident.displayTitle,
                  style: TextStyle(
                    fontWeight: FontWeight.w600,
                    color: Theme.of(context).colorScheme.onSurface,
                    fontSize: 14,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 2),
                Row(
                  children: [
                    Text(
                      incident.severity.toUpperCase(),
                      style: TextStyle(
                        color: incident.severityColor,
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(width: 6),
                    Text('•', style: TextStyle(color: AppTokens.mutedOf(context))),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        incident.createdAt.toLocal().toString().split(".")[0],
                        style: TextStyle(
                          color: AppTokens.mutedOf(context),
                          fontSize: 11,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(width: AppTokens.spaceSm),
          AppBadge(
            label: incident.status.toUpperCase(),
            color: incident.statusColor,
          ),
          const SizedBox(width: 4),
          Icon(
            Icons.chevron_right_rounded,
            color: AppTokens.mutedOf(context),
            size: 18,
          ),
        ],
      ),
    );
  }
}

/// Form sheet allowing officers/admins to report a new incident with input validation.
class _CreateIncidentFormSheet extends ConsumerStatefulWidget {
  const _CreateIncidentFormSheet({required this.onIncidentCreated});

  final VoidCallback onIncidentCreated;

  @override
  ConsumerState<_CreateIncidentFormSheet> createState() =>
      _CreateIncidentFormSheetState();
}

class _CreateIncidentFormSheetState
    extends ConsumerState<_CreateIncidentFormSheet> {
  final _formKey = GlobalKey<FormState>();
  final _titleController = TextEditingController();
  final _descriptionController = TextEditingController();

  String _severity = 'medium';
  int? _selectedIntersectionId;
  List<Junction> _junctions = [];
  bool _isLoadingJunctions = true;
  bool _isSubmitting = false;
  String? _submitError;

  @override
  void initState() {
    super.initState();
    _loadJunctions();
  }

  @override
  void dispose() {
    _titleController.dispose();
    _descriptionController.dispose();
    super.dispose();
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
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _isSubmitting = true;
      _submitError = null;
    });

    try {
      final service = ref.read(incidentServiceProvider);
      await service.createIncident(
        title: _titleController.text.trim(),
        description: _descriptionController.text.trim(),
        severity: _severity,
        intersectionId: _selectedIntersectionId,
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            backgroundColor: AppTokens.success,
            content: Text('Incident reported successfully'),
          ),
        );
        widget.onIncidentCreated();
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isSubmitting = false;
          _submitError = e is ApiException ? e.message : 'Error creating incident: $e';
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
                    const Icon(Icons.report_problem_rounded, color: AppTokens.amber),
                    const SizedBox(width: AppTokens.spaceSm),
                    Text(
                      'Report Traffic Incident',
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
                      style: const TextStyle(color: AppTokens.danger, fontSize: 12),
                    ),
                  ),
                  const SizedBox(height: AppTokens.spaceMd),
                ],
                TextFormField(
                  controller: _titleController,
                  decoration: const InputDecoration(
                    labelText: 'Title / Headline',
                    hintText: 'e.g. Multi-vehicle collision on 5th Ave',
                    filled: true,
                    fillColor: AppTokens.surface,
                  ),
                  validator: (val) {
                    if (val == null || val.trim().isEmpty) {
                      return 'Please provide a brief title';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: AppTokens.spaceSm),
                TextFormField(
                  controller: _descriptionController,
                  maxLines: 3,
                  decoration: const InputDecoration(
                    labelText: 'Detailed Description',
                    hintText: 'Vehicle count, lane obstruction, safety status...',
                    filled: true,
                    fillColor: AppTokens.surface,
                  ),
                  validator: (val) {
                    if (val == null || val.trim().isEmpty) {
                      return 'Please provide incident details';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: AppTokens.spaceMd),
                Text(
                  'Severity Level',
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: Theme.of(context).colorScheme.onSurface,
                  ),
                ),
                const SizedBox(height: 6),
                Wrap(
                  spacing: AppTokens.spaceSm,
                  children: ['low', 'medium', 'high', 'critical'].map((sev) {
                    final isSel = _severity == sev;
                    return ChoiceChip(
                      label: Text(sev.toUpperCase()),
                      selected: isSel,
                      onSelected: (val) {
                        if (val) setState(() => _severity = sev);
                      },
                      selectedColor: AppTokens.teal.withAlpha(40),
                      backgroundColor: AppTokens.surfaceOf(context),
                      labelPadding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 6),
                      labelStyle: TextStyle(
                        color:
                            isSel ? AppTokens.teal : AppTokens.mutedOf(context),
                        fontWeight: isSel ? FontWeight.w700 : FontWeight.w500,
                        fontSize: 11,
                      ),
                    );
                  }).toList(),
                ),
                const SizedBox(height: AppTokens.spaceMd),
                Text(
                  'Associated Intersection (Optional)',
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
                        isExpanded: true,
                        initialValue: _selectedIntersectionId,
                        decoration: InputDecoration(
                          filled: true,
                          fillColor: Theme.of(context).colorScheme.surfaceContainerHighest,
                        ),
                        dropdownColor: Theme.of(context).colorScheme.surface,
                        hint: const Text('Select affected junction'),
                        items: [
                          const DropdownMenuItem<int?>(
                            value: null,
                            child: Text(
                              'None / Mid-block segment',
                              overflow: TextOverflow.ellipsis,
                              maxLines: 1,
                            ),
                          ),
                          ..._junctions.map((j) => DropdownMenuItem<int?>(
                                value: j.id,
                                child: Text(
                                  '${j.name} (${j.code})',
                                  overflow: TextOverflow.ellipsis,
                                  maxLines: 1,
                                ),
                              )),
                        ],
                        onChanged: (val) {
                          setState(() => _selectedIntersectionId = val);
                        },
                      ),
                const SizedBox(height: AppTokens.spaceLg),
                SizedBox(
                  width: double.infinity,
                  height: 48,
                  child: ElevatedButton(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppTokens.teal,
                      foregroundColor: Theme.of(context).brightness == Brightness.dark
                          ? AppTokens.ink
                          : Colors.white,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                    ),
                    onPressed: _isSubmitting ? null : _submit,
                    child: _isSubmitting
                        ? SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              valueColor: AlwaysStoppedAnimation(
                                Theme.of(context).brightness == Brightness.dark
                                    ? AppTokens.ink
                                    : Colors.white,
                              ),
                            ),
                          )
                        : const Text(
                            'Submit Incident Alert',
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
