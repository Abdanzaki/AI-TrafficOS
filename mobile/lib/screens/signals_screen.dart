import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/junction.dart';
import '../models/signal.dart';
import '../providers/realtime_providers.dart';
import '../services/junction_service.dart';
import '../services/realtime_protocol.dart';
import '../services/signal_service.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_card.dart';
import '../widgets/empty_state.dart';
import '../widgets/error_state.dart';
import '../widgets/loading_state.dart';
import 'signal_detail_screen.dart';

/// Screen listing municipal traffic signals with pagination and junction filtering.
class SignalsScreen extends ConsumerStatefulWidget {
  const SignalsScreen({super.key, this.initialIntersectionId});

  final int? initialIntersectionId;

  @override
  ConsumerState<SignalsScreen> createState() => _SignalsScreenState();
}

class _SignalsScreenState extends ConsumerState<SignalsScreen> {
  int? _selectedIntersectionId;
  int _currentPage = 1;
  static const int _pageSize = 20;

  bool _isLoading = true;
  String? _errorMessage;
  PaginatedSignals? _paginatedSignals;

  List<Junction> _junctions = [];

  @override
  void initState() {
    super.initState();
    _selectedIntersectionId = widget.initialIntersectionId;
    _fetchJunctions();
    _loadSignals();
  }

  Future<void> _fetchJunctions() async {
    try {
      final junctionService = ref.read(junctionServiceProvider);
      final res = await junctionService.getJunctions(perPage: 50);
      if (mounted) {
        setState(() {
          _junctions = res.items;
        });
      }
    } catch (_) {}
  }

  Future<void> _loadSignals({bool isBackgroundRefresh = false}) async {
    if (!isBackgroundRefresh) {
      setState(() {
        _isLoading = true;
        _errorMessage = null;
      });
    }

    try {
      final signalService = ref.read(signalServiceProvider);
      final res = await signalService.getSignals(
        intersectionId: _selectedIntersectionId,
        page: _currentPage,
        perPage: _pageSize,
      );
      if (mounted) {
        setState(() {
          _paginatedSignals = res;
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
    // Real-time WebSocket invalidation: refresh signals list on signal phase/state change
    ref.listen(
      realtimeTopicEventProvider(RealtimeTopics.signalChange),
      (_, next) {
        if (next.hasValue) {
          _loadSignals(isBackgroundRefresh: true);
        }
      },
    );

    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Traffic Signals'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Refresh Signals',
            onPressed: _loadSignals,
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            _buildJunctionFilterBar(),
            Expanded(
              child: RefreshIndicator(
                color: AppTokens.teal,
                backgroundColor: AppTokens.card,
                onRefresh: _loadSignals,
                child: _buildBody(theme),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildJunctionFilterBar() {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppTokens.spaceMd,
        vertical: AppTokens.spaceSm,
      ),
      decoration: const BoxDecoration(
        color: AppTokens.surface,
        border: Border(
          bottom: BorderSide(color: AppTokens.borderDark),
        ),
      ),
      child: Row(
        children: [
          const Icon(
            Icons.filter_list_rounded,
            color: AppTokens.teal,
            size: 20,
          ),
          const SizedBox(width: AppTokens.spaceSm),
          Expanded(
            child: DropdownButtonHideUnderline(
              child: DropdownButton<int?>(
                value: _selectedIntersectionId,
                isExpanded: true,
                dropdownColor: AppTokens.card,
                hint: const Text(
                  'All Junctions',
                  style: TextStyle(color: AppTokens.textPrimary, fontSize: 13),
                ),
                icon: const Icon(
                  Icons.arrow_drop_down_rounded,
                  color: AppTokens.muted,
                ),
                items: [
                  const DropdownMenuItem<int?>(
                    value: null,
                    child: Text(
                      'All Junctions',
                      style: TextStyle(
                        color: AppTokens.textPrimary,
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  ..._junctions.map(
                    (j) => DropdownMenuItem<int?>(
                      value: j.id,
                      child: Text(
                        '#${j.id} — ${j.name}',
                        style: const TextStyle(
                          color: AppTokens.textPrimary,
                          fontSize: 13,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ),
                ],
                onChanged: (val) {
                  setState(() {
                    _selectedIntersectionId = val;
                    _currentPage = 1;
                  });
                  _loadSignals();
                },
              ),
            ),
          ),
          if (_selectedIntersectionId != null)
            IconButton(
              icon: const Icon(Icons.close_rounded, size: 18, color: AppTokens.muted),
              tooltip: 'Clear filter',
              onPressed: () {
                setState(() {
                  _selectedIntersectionId = null;
                  _currentPage = 1;
                });
                _loadSignals();
              },
            ),
        ],
      ),
    );
  }

  Widget _buildBody(ThemeData theme) {
    if (_isLoading) {
      return const LoadingState(message: 'Loading signals...');
    }

    if (_errorMessage != null) {
      return ErrorState(
        message: _errorMessage!,
        title: 'Unable to Load Signals',
        onRetry: _loadSignals,
      );
    }

    final signals = _paginatedSignals?.items ?? [];
    if (signals.isEmpty) {
      return const EmptyState(
        icon: Icons.traffic_rounded,
        title: 'No Signals Found',
        message: 'No traffic signal controllers matched the selected junction criteria.',
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      itemCount: signals.length + 1,
      itemBuilder: (context, index) {
        if (index == signals.length) {
          return _buildPaginationControls();
        }

        final signal = signals[index];
        return Padding(
          padding: const EdgeInsets.only(bottom: AppTokens.spaceSm),
          child: AppCard(
            padding: const EdgeInsets.symmetric(
              horizontal: AppTokens.spaceMd,
              vertical: AppTokens.spaceSm,
            ),
            child: ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: signal.stateColor.withAlpha(25),
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: signal.stateColor.withAlpha(120),
                    width: 2,
                  ),
                ),
                child: Center(
                  child: Container(
                    width: 16,
                    height: 16,
                    decoration: BoxDecoration(
                      color: signal.stateColor,
                      shape: BoxShape.circle,
                      boxShadow: [
                        BoxShadow(
                          color: signal.stateColor.withAlpha(150),
                          blurRadius: 6,
                          spreadRadius: 1,
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              title: Row(
                children: [
                  Expanded(
                    child: Text(
                      signal.name,
                      style: theme.textTheme.titleSmall?.copyWith(
                        color: AppTokens.textPrimary,
                        fontWeight: FontWeight.w700,
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  AppBadge(
                    label: signal.status.toUpperCase(),
                    color: signal.statusColor,
                  ),
                ],
              ),
              subtitle: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 6,
                          vertical: 2,
                        ),
                        decoration: BoxDecoration(
                          color: AppTokens.surface,
                          borderRadius: BorderRadius.circular(4),
                          border: Border.all(color: AppTokens.borderDark),
                        ),
                        child: Text(
                          'Junction #${signal.intersectionId}',
                          style: const TextStyle(
                            color: AppTokens.muted,
                            fontSize: 11,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                      ),
                      const SizedBox(width: AppTokens.spaceSm),
                      Expanded(
                        child: Row(
                          children: [
                            Text(
                              'Phase: ',
                              style: theme.textTheme.bodySmall?.copyWith(
                                color: AppTokens.muted,
                                fontSize: 12,
                              ),
                            ),
                            Flexible(
                              child: Text(
                                signal.currentPhase ?? signal.state.label,
                                style: theme.textTheme.bodySmall?.copyWith(
                                  color: signal.stateColor,
                                  fontWeight: FontWeight.w600,
                                  fontSize: 12,
                                ),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ],
              ),
              trailing: const Icon(
                Icons.chevron_right_rounded,
                color: AppTokens.muted,
              ),
              onTap: () {
                Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => SignalDetailScreen(signalId: signal.id),
                  ),
                ).then((_) => _loadSignals());
              },
            ),
          ),
        );
      },
    );
  }

  Widget _buildPaginationControls() {
    final paginated = _paginatedSignals;
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
                    setState(() => _currentPage--);
                    _loadSignals();
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
                    setState(() => _currentPage++);
                    _loadSignals();
                  }
                : null,
          ),
        ],
      ),
    );
  }
}
