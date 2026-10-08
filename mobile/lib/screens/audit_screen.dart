import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/audit_entry.dart';
import '../models/user.dart';
import '../providers/realtime_providers.dart';
import '../services/api_client.dart';
import '../services/audit_service.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_card.dart';
import '../widgets/empty_state.dart';
import '../widgets/error_state.dart';
import '../widgets/loading_state.dart';
import '../widgets/offline_banner.dart';
import '../widgets/require_role.dart';

/// Screen displaying immutable audit logs and operational events (Administrator restricted).
class AuditScreen extends StatelessWidget {
  const AuditScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return const RequireRole(
      allowedRoles: [User.roleAdmin],
      screenTitle: 'Audit Log',
      readOnlyMessage:
          'Audit log trails contain sensitive administrative records restricted to Administrator accounts.',
      child: _AuditScreenContent(),
    );
  }
}

class _AuditScreenContent extends ConsumerStatefulWidget {
  const _AuditScreenContent();

  @override
  ConsumerState<_AuditScreenContent> createState() =>
      _AuditScreenContentState();
}

class _AuditScreenContentState extends ConsumerState<_AuditScreenContent> {
  final ScrollController _scrollController = ScrollController();
  final List<AuditEntry> _entries = [];
  final Set<int> _expandedIds = {};

  bool _isLoading = true;
  bool _isLoadingMore = false;
  String? _errorMessage;
  int _page = 1;
  int _totalPages = 1;
  String? _selectedAction;

  static const List<String> _actionFilters = [
    'All',
    'auth.login',
    'user.created',
    'user.updated',
    'user.deactivated',
    'notification.broadcast',
    'notification.read',
  ];

  @override
  void initState() {
    super.initState();
    _loadInitialAuditLogs();
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
      _loadMoreAuditLogs();
    }
  }

  Future<void> _loadInitialAuditLogs() async {
    setState(() {
      _page = 1;
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final service = ref.read(auditServiceProvider);
      final paged = await service.getAuditLogs(
        action: _selectedAction,
        page: 1,
        perPage: 20,
      );

      if (mounted) {
        setState(() {
          _entries.clear();
          _entries.addAll(paged.items);
          _totalPages = paged.pages;
          _isLoading = false;
        });
      }
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _errorMessage = e.message;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _errorMessage = 'Failed to load audit logs: $e';
          _isLoading = false;
        });
      }
    }
  }

  Future<void> _loadMoreAuditLogs() async {
    if (_isLoadingMore) return;
    setState(() {
      _isLoadingMore = true;
    });

    try {
      final nextPage = _page + 1;
      final service = ref.read(auditServiceProvider);
      final paged = await service.getAuditLogs(
        action: _selectedAction,
        page: nextPage,
        perPage: 20,
      );

      if (mounted) {
        setState(() {
          _page = nextPage;
          _entries.addAll(paged.items);
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

  void _toggleExpanded(int id) {
    setState(() {
      if (_expandedIds.contains(id)) {
        _expandedIds.remove(id);
      } else {
        _expandedIds.add(id);
      }
    });
  }

  String _formatDate(DateTime dt) {
    final hour = dt.hour.toString().padLeft(2, '0');
    final minute = dt.minute.toString().padLeft(2, '0');
    final second = dt.second.toString().padLeft(2, '0');
    return '${dt.year}-${dt.month.toString().padLeft(2, '0')}-${dt.day.toString().padLeft(2, '0')} $hour:$minute:$second';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Audit Log'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Refresh Audit Logs',
            onPressed: _loadInitialAuditLogs,
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            if (ref.watch(isOfflineProvider)) const OfflineBanner(),
            _buildFilterBar(),
            Expanded(child: _buildBody()),
          ],
        ),
      ),
    );
  }

  Widget _buildFilterBar() {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(
        horizontal: AppTokens.spaceMd,
        vertical: AppTokens.spaceSm,
      ),
      child: Row(
        children: _actionFilters.map((action) {
          final isSelected = action == 'All'
              ? _selectedAction == null
              : _selectedAction == action;

          return Padding(
            padding: const EdgeInsets.only(right: AppTokens.spaceSm),
            child: ChoiceChip(
              label: Text(action),
              selected: isSelected,
              onSelected: (selected) {
                if (selected) {
                  setState(() {
                    _selectedAction = action == 'All' ? null : action;
                  });
                  _loadInitialAuditLogs();
                }
              },
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const LoadingState(message: 'Querying audit records...');
    }

    if (_errorMessage != null) {
      return ErrorState(
        message: _errorMessage!,
        onRetry: _loadInitialAuditLogs,
      );
    }

    if (_entries.isEmpty) {
      return RefreshIndicator(
        onRefresh: _loadInitialAuditLogs,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          children: [
            SizedBox(
              height: MediaQuery.of(context).size.height * 0.6,
              child: const EmptyState(
                icon: Icons.fact_check_outlined,
                title: 'No Audit Logs Found',
                message:
                    'No recorded audit events match the specified action filter.',
              ),
            ),
          ],
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: _loadInitialAuditLogs,
      child: ListView.separated(
        controller: _scrollController,
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(AppTokens.spaceMd),
        itemCount: _entries.length + (_isLoadingMore ? 1 : 0),
        separatorBuilder: (context, index) =>
            const SizedBox(height: AppTokens.spaceSm),
        itemBuilder: (context, index) {
          if (index == _entries.length) {
            return const Padding(
              padding: EdgeInsets.all(AppTokens.spaceMd),
              child: Center(
                child: SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    valueColor: AlwaysStoppedAnimation<Color>(AppTokens.teal),
                  ),
                ),
              ),
            );
          }

          final entry = _entries[index];
          final isExpanded = _expandedIds.contains(entry.id);
          return _buildAuditCard(entry, isExpanded);
        },
      ),
    );
  }

  Widget _buildAuditCard(AuditEntry entry, bool isExpanded) {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              AppBadge(
                label: entry.action,
                color: entry.actionColor,
              ),
              const Spacer(),
              Text(
                _formatDate(entry.createdAt),
                style: TextStyle(
                  color: AppTokens.mutedOf(context),
                  fontSize: 11,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceSm),
          Row(
            children: [
              Icon(
                Icons.person_outline_rounded,
                size: 15,
                color: AppTokens.mutedOf(context),
              ),
              const SizedBox(width: AppTokens.spaceXs),
              Expanded(
                child: Text(
                  entry.actorEmail,
                  style: TextStyle(
                    color: Theme.of(context).colorScheme.onSurface,
                    fontWeight: FontWeight.w600,
                    fontSize: 13,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              const SizedBox(width: AppTokens.spaceSm),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.surface,
                  borderRadius: BorderRadius.circular(4),
                  border: Border.all(color: AppTokens.borderOf(context)),
                ),
                child: Text(
                  'Entity: ${entry.entity}${entry.entityId != null ? ' #${entry.entityId}' : ''}',
                  style: TextStyle(
                    color: AppTokens.mutedOf(context),
                    fontSize: 11,
                  ),
                ),
              ),
            ],
          ),
          if (entry.ipAddress != null && entry.ipAddress!.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              'IP: ${entry.ipAddress}',
              style: TextStyle(
                color: AppTokens.mutedOf(context),
                fontSize: 11,
              ),
            ),
          ],
          const SizedBox(height: AppTokens.spaceSm),
          InkWell(
            onTap: () => _toggleExpanded(entry.id),
            borderRadius: BorderRadius.circular(6),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(
                children: [
                  Icon(
                    isExpanded
                        ? Icons.keyboard_arrow_up_rounded
                        : Icons.keyboard_arrow_down_rounded,
                    size: 18,
                    color: AppTokens.teal,
                  ),
                  const SizedBox(width: AppTokens.spaceXs),
                  Text(
                    isExpanded ? 'Hide Details' : 'View Payload Details',
                    style: const TextStyle(
                      color: AppTokens.teal,
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
            ),
          ),
          if (isExpanded) ...[
            const SizedBox(height: AppTokens.spaceSm),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(AppTokens.spaceSm),
              decoration: BoxDecoration(
                color: Theme.of(context).colorScheme.surface,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppTokens.borderOf(context)),
              ),
              child: SelectableText(
                entry.details.isNotEmpty
                    ? const JsonEncoder.withIndent('  ').convert(entry.details)
                    : '// No additional payload metadata',
                style: TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 11,
                  color: AppTokens.mutedOf(context),
                  height: 1.4,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
