import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/ai_decision.dart';
import '../services/prediction_service.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_card.dart';
import '../widgets/empty_state.dart';
import '../widgets/error_state.dart';
import '../widgets/loading_state.dart';

/// Screen displaying paginated AI decision history with action type filtering
/// and expandable details (action, junction, explanation, confidence, impact, timestamp, model version).
class DecisionsScreen extends ConsumerStatefulWidget {
  const DecisionsScreen({super.key});

  @override
  ConsumerState<DecisionsScreen> createState() => _DecisionsScreenState();
}

class _DecisionsScreenState extends ConsumerState<DecisionsScreen> {
  String? _selectedActionFilter;
  int _currentPage = 1;
  static const int _pageSize = 20;

  bool _isLoading = true;
  String? _errorMessage;
  PaginatedAIDecisions? _paginatedDecisions;

  // Track expanded decision IDs for custom expand/collapse state
  final Set<int> _expandedIds = <int>{};

  final List<String> _actionFilters = const [
    'ALL',
    'EXTEND_GREEN',
    'SHORTEN_CYCLE',
    'ALL_RED_HOLD',
    'NO_ACTION',
    'signal_timing',
    'route_advisory',
  ];

  @override
  void initState() {
    super.initState();
    _loadDecisions();
  }

  Future<void> _loadDecisions() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final predictionService = ref.read(predictionServiceProvider);
      final filter = _selectedActionFilter == 'ALL' ? null : _selectedActionFilter;
      final res = await predictionService.getAiDecisions(
        decisionType: filter,
        page: _currentPage,
        perPage: _pageSize,
      );

      if (mounted) {
        setState(() {
          _paginatedDecisions = res;
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
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('AI Decisions History'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Refresh Decisions',
            onPressed: _loadDecisions,
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            _buildActionFilterBar(),
            Expanded(
              child: RefreshIndicator(
                color: AppTokens.teal,
                backgroundColor: AppTokens.card,
                onRefresh: _loadDecisions,
                child: _buildBody(theme),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildActionFilterBar() {
    return Container(
      height: 48,
      padding: const EdgeInsets.symmetric(horizontal: AppTokens.spaceMd),
      decoration: const BoxDecoration(
        color: AppTokens.surface,
        border: Border(
          bottom: BorderSide(color: AppTokens.borderDark),
        ),
      ),
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: _actionFilters.length,
        separatorBuilder: (_, _) => const SizedBox(width: AppTokens.spaceSm),
        itemBuilder: (context, index) {
          final filter = _actionFilters[index];
          final isSelected = (_selectedActionFilter == null && filter == 'ALL') ||
              _selectedActionFilter == filter;

          return Center(
            child: ChoiceChip(
              label: Text(
                filter,
                style: TextStyle(
                  color: isSelected ? AppTokens.ink : AppTokens.textPrimary,
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                ),
              ),
              selected: isSelected,
              selectedColor: AppTokens.teal,
              backgroundColor: AppTokens.card,
              side: BorderSide(
                color: isSelected ? AppTokens.teal : AppTokens.borderDark,
              ),
              onSelected: (selected) {
                if (selected) {
                  setState(() {
                    _selectedActionFilter = filter == 'ALL' ? null : filter;
                    _currentPage = 1;
                    _expandedIds.clear();
                  });
                  _loadDecisions();
                }
              },
            ),
          );
        },
      ),
    );
  }

  Widget _buildBody(ThemeData theme) {
    if (_isLoading) {
      return const LoadingState(message: 'Loading AI decision audit logs...');
    }

    if (_errorMessage != null) {
      return ErrorState(
        message: _errorMessage!,
        title: 'Unable to Load Decisions',
        onRetry: _loadDecisions,
      );
    }

    final items = _paginatedDecisions?.items ?? [];
    if (items.isEmpty) {
      return const EmptyState(
        icon: Icons.psychology_rounded,
        title: 'No Decisions Found',
        message: 'No autonomous or advisory decisions matched the active filters.',
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      itemCount: items.length + 1,
      itemBuilder: (context, index) {
        if (index == items.length) {
          return _buildPaginationControls();
        }

        final decision = items[index];
        final isExpanded = _expandedIds.contains(decision.id);

        return Padding(
          padding: const EdgeInsets.only(bottom: AppTokens.spaceSm),
          child: AppCard(
            padding: const EdgeInsets.all(AppTokens.spaceMd),
            child: InkWell(
              onTap: () {
                setState(() {
                  if (isExpanded) {
                    _expandedIds.remove(decision.id);
                  } else {
                    _expandedIds.add(decision.id);
                  }
                });
              },
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.center,
                    children: [
                      Container(
                        padding: const EdgeInsets.all(8),
                        decoration: BoxDecoration(
                          color: decision.actionColor.withAlpha(25),
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(
                            color: decision.actionColor.withAlpha(80),
                          ),
                        ),
                        child: Icon(
                          Icons.psychology_rounded,
                          color: decision.actionColor,
                          size: 18,
                        ),
                      ),
                      const SizedBox(width: AppTokens.spaceSm),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Text(
                                  decision.action,
                                  style: TextStyle(
                                    color: decision.actionColor,
                                    fontWeight: FontWeight.w800,
                                    fontSize: 13,
                                  ),
                                ),
                                const SizedBox(width: AppTokens.spaceSm),
                                AppBadge(
                                  label: decision.status.toUpperCase(),
                                  color: decision.statusColor,
                                ),
                              ],
                            ),
                            const SizedBox(height: 2),
                            Text(
                              decision.junction ?? 'Municipal System Corridor',
                              style: const TextStyle(
                                color: AppTokens.textPrimary,
                                fontWeight: FontWeight.w600,
                                fontSize: 12,
                              ),
                            ),
                          ],
                        ),
                      ),
                      Icon(
                        isExpanded
                            ? Icons.expand_less_rounded
                            : Icons.expand_more_rounded,
                        color: AppTokens.muted,
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(
                    decision.reason,
                    style: TextStyle(
                      color: isExpanded ? AppTokens.textPrimary : AppTokens.muted,
                      fontSize: 12,
                    ),
                    maxLines: isExpanded ? null : 2,
                    overflow: isExpanded ? null : TextOverflow.ellipsis,
                  ),
                  if (isExpanded) ...[
                    const SizedBox(height: AppTokens.spaceMd),
                    const Divider(color: AppTokens.borderDark),
                    const SizedBox(height: AppTokens.spaceSm),
                    _buildExpandedDetails(decision),
                  ],
                ],
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _buildExpandedDetails(AIDecisionItem decision) {
    final confPercent = decision.confidence != null
        ? (decision.confidence! * 100).toInt()
        : null;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (confPercent != null) ...[
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                'Engine Confidence',
                style: TextStyle(color: AppTokens.muted, fontSize: 11),
              ),
              Text(
                '$confPercent%',
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
            borderRadius: BorderRadius.circular(3),
            child: LinearProgressIndicator(
              value: decision.confidence!,
              backgroundColor: AppTokens.surface,
              valueColor: const AlwaysStoppedAnimation(AppTokens.teal),
              minHeight: 5,
            ),
          ),
          const SizedBox(height: AppTokens.spaceSm),
        ],
        _buildDetailRow(
          icon: Icons.insights_rounded,
          label: 'Expected Impact',
          value: decision.expectedImpact ?? 'Delay reduction and queue discharge',
        ),
        const SizedBox(height: AppTokens.spaceXs),
        _buildDetailRow(
          icon: Icons.memory_rounded,
          label: 'Model Version',
          value: decision.modelVersion ?? 'decision_engine_v1.0.0',
        ),
        const SizedBox(height: AppTokens.spaceXs),
        _buildDetailRow(
          icon: Icons.access_time_rounded,
          label: 'Emitted Timestamp',
          value: decision.createdAt.toUtc().toIso8601String(),
        ),
        if (decision.appliedAt != null) ...[
          const SizedBox(height: AppTokens.spaceXs),
          _buildDetailRow(
            icon: Icons.check_circle_outline_rounded,
            label: 'Applied Timestamp',
            value: decision.appliedAt!.toUtc().toIso8601String(),
          ),
        ],
      ],
    );
  }

  Widget _buildDetailRow({
    required IconData icon,
    required String label,
    required String value,
  }) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 15, color: AppTokens.teal),
        const SizedBox(width: AppTokens.spaceSm),
        Text(
          '$label: ',
          style: const TextStyle(
            color: AppTokens.muted,
            fontSize: 11,
            fontWeight: FontWeight.w600,
          ),
        ),
        Expanded(
          child: Text(
            value,
            style: const TextStyle(
              color: AppTokens.textPrimary,
              fontSize: 11,
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildPaginationControls() {
    final paginated = _paginatedDecisions;
    if (paginated == null || paginated.pages <= 1) {
      return const SizedBox(height: AppTokens.spaceMd);
    }

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppTokens.spaceMd),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          IconButton(
            icon: const Icon(Icons.arrow_back_ios_rounded, size: 16),
            color: _currentPage > 1 ? AppTokens.teal : AppTokens.muted,
            onPressed: _currentPage > 1
                ? () {
                    setState(() {
                      _currentPage--;
                      _expandedIds.clear();
                    });
                    _loadDecisions();
                  }
                : null,
          ),
          Text(
            'Page $_currentPage of ${paginated.pages}',
            style: const TextStyle(
              color: AppTokens.textPrimary,
              fontWeight: FontWeight.w600,
              fontSize: 13,
            ),
          ),
          IconButton(
            icon: const Icon(Icons.arrow_forward_ios_rounded, size: 16),
            color: _currentPage < paginated.pages
                ? AppTokens.teal
                : AppTokens.muted,
            onPressed: _currentPage < paginated.pages
                ? () {
                    setState(() {
                      _currentPage++;
                      _expandedIds.clear();
                    });
                    _loadDecisions();
                  }
                : null,
          ),
        ],
      ),
    );
  }
}
