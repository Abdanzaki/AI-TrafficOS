import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/notification.dart';
import '../services/api_client.dart';
import '../services/notification_service.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_card.dart';
import '../widgets/empty_state.dart';
import '../widgets/error_state.dart';
import '../widgets/loading_state.dart';

/// Notifications screen displaying targeted operational alerts and broadcasts.
class NotificationsScreen extends ConsumerStatefulWidget {
  const NotificationsScreen({super.key});

  @override
  ConsumerState<NotificationsScreen> createState() =>
      _NotificationsScreenState();
}

class _NotificationsScreenState extends ConsumerState<NotificationsScreen> {
  final ScrollController _scrollController = ScrollController();
  final List<AppNotification> _notifications = [];
  bool _isLoading = true;
  bool _isLoadingMore = false;
  String? _errorMessage;
  int _page = 1;
  int _totalPages = 1;
  bool? _filterUnread;

  @override
  void initState() {
    super.initState();
    _loadInitialNotifications();
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
      _loadMoreNotifications();
    }
  }

  Future<void> _loadInitialNotifications() async {
    setState(() {
      _page = 1;
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final service = ref.read(notificationServiceProvider);
      final paged = await service.getMyNotifications(
        isRead: _filterUnread,
        page: 1,
        perPage: 20,
      );

      if (mounted) {
        setState(() {
          _notifications.clear();
          _notifications.addAll(paged.items);
          _totalPages = paged.pages;
          _isLoading = false;
        });
        ref.invalidate(unreadNotificationCountProvider);
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
          _errorMessage = 'Failed to load notifications: $e';
          _isLoading = false;
        });
      }
    }
  }

  Future<void> _loadMoreNotifications() async {
    if (_isLoadingMore) return;
    setState(() {
      _isLoadingMore = true;
    });

    try {
      final nextPage = _page + 1;
      final service = ref.read(notificationServiceProvider);
      final paged = await service.getMyNotifications(
        isRead: _filterUnread,
        page: nextPage,
        perPage: 20,
      );

      if (mounted) {
        setState(() {
          _page = nextPage;
          _notifications.addAll(paged.items);
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

  Future<void> _onNotificationTapped(AppNotification item) async {
    // Optimistically mark as read and notify backend
    if (!item.isRead) {
      final index = _notifications.indexWhere((n) => n.id == item.id);
      if (index != -1) {
        setState(() {
          _notifications[index] = item.copyWith(isRead: true);
        });
      }
      try {
        await ref.read(notificationServiceProvider).markAsRead(item.id);
        ref.invalidate(unreadNotificationCountProvider);
      } catch (_) {
        // Backend failure will be re-synced on next refresh
      }
    }

    if (!mounted) return;
    _showDetailSheet(item);
  }

  void _showDetailSheet(AppNotification item) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppTokens.card,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        side: BorderSide(color: AppTokens.borderDark),
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
                      color: AppTokens.muted.withAlpha(80),
                      borderRadius: BorderRadius.circular(2),
                    ),
                  ),
                ),
                const SizedBox(height: AppTokens.spaceMd),
                Row(
                  children: [
                    AppBadge(
                      label: item.type.toUpperCase(),
                      color: item.statusColor,
                    ),
                    const Spacer(),
                    Text(
                      _formatDate(item.createdAt),
                      style: const TextStyle(
                        color: AppTokens.muted,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: AppTokens.spaceMd),
                Text(
                  item.title,
                  style: const TextStyle(
                    color: AppTokens.textPrimary,
                    fontSize: 18,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: AppTokens.spaceSm),
                Text(
                  item.body.isNotEmpty ? item.body : 'No additional details provided.',
                  style: const TextStyle(
                    color: AppTokens.muted,
                    fontSize: 14,
                    height: 1.5,
                  ),
                ),
                if (item.entityType != null) ...[
                  const SizedBox(height: AppTokens.spaceMd),
                  Container(
                    padding: const EdgeInsets.all(AppTokens.spaceSm),
                    decoration: BoxDecoration(
                      color: AppTokens.surface,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: AppTokens.borderDark),
                    ),
                    child: Row(
                      children: [
                        const Icon(
                          Icons.link_rounded,
                          size: 16,
                          color: AppTokens.teal,
                        ),
                        const SizedBox(width: AppTokens.spaceXs),
                        Text(
                          'Entity: ${item.entityType}${item.entityId != null ? " #${item.entityId}" : ""}',
                          style: const TextStyle(
                            color: AppTokens.muted,
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
                const SizedBox(height: AppTokens.spaceLg),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppTokens.surface,
                      foregroundColor: AppTokens.textPrimary,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                        side: const BorderSide(color: AppTokens.borderDark),
                      ),
                    ),
                    onPressed: () => Navigator.of(ctx).pop(),
                    child: const Text('Dismiss'),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  String _formatDate(DateTime dt) {
    final hour = dt.hour.toString().padLeft(2, '0');
    final minute = dt.minute.toString().padLeft(2, '0');
    return '${dt.year}-${dt.month.toString().padLeft(2, '0')}-${dt.day.toString().padLeft(2, '0')} $hour:$minute';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Notifications'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Refresh Notifications',
            onPressed: _loadInitialNotifications,
          ),
        ],
      ),
      body: Column(
        children: [
          _buildFilterBar(),
          Expanded(child: _buildBody()),
        ],
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
        children: [
          ChoiceChip(
            label: const Text('All'),
            selected: _filterUnread == null,
            onSelected: (selected) {
              if (selected && _filterUnread != null) {
                setState(() => _filterUnread = null);
                _loadInitialNotifications();
              }
            },
          ),
          const SizedBox(width: AppTokens.spaceSm),
          ChoiceChip(
            label: const Text('Unread Only'),
            selected: _filterUnread == false,
            onSelected: (selected) {
              final next = selected ? false : null;
              if (next != _filterUnread) {
                setState(() => _filterUnread = next);
                _loadInitialNotifications();
              }
            },
          ),
          const SizedBox(width: AppTokens.spaceSm),
          ChoiceChip(
            label: const Text('Read'),
            selected: _filterUnread == true,
            onSelected: (selected) {
              final next = selected ? true : null;
              if (next != _filterUnread) {
                setState(() => _filterUnread = next);
                _loadInitialNotifications();
              }
            },
          ),
        ],
      ),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const LoadingState(message: 'Loading notifications...');
    }

    if (_errorMessage != null) {
      return ErrorState(
        message: _errorMessage!,
        onRetry: _loadInitialNotifications,
      );
    }

    if (_notifications.isEmpty) {
      return RefreshIndicator(
        onRefresh: _loadInitialNotifications,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          children: [
            SizedBox(
              height: MediaQuery.of(context).size.height * 0.6,
              child: const EmptyState(
                icon: Icons.check_circle_outline_rounded,
                title: "You're all caught up",
                message:
                    'There are no pending alerts or advisories for your session.',
              ),
            ),
          ],
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: _loadInitialNotifications,
      child: ListView.separated(
        controller: _scrollController,
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(AppTokens.spaceMd),
        itemCount: _notifications.length + (_isLoadingMore ? 1 : 0),
        separatorBuilder: (context, index) =>
            const SizedBox(height: AppTokens.spaceSm),
        itemBuilder: (context, index) {
          if (index == _notifications.length) {
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

          final notif = _notifications[index];
          return _buildNotificationCard(notif);
        },
      ),
    );
  }

  Widget _buildNotificationCard(AppNotification item) {
    return AppCard(
      onTap: () => _onNotificationTapped(item),
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              color: item.statusColor.withAlpha(25),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: item.statusColor.withAlpha(60),
              ),
            ),
            child: Icon(
              item.icon,
              color: item.statusColor,
              size: 20,
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
                        item.title,
                        style: TextStyle(
                          color: AppTokens.textPrimary,
                          fontWeight:
                              item.isRead ? FontWeight.w500 : FontWeight.w700,
                          fontSize: 14,
                        ),
                      ),
                    ),
                    if (!item.isRead) ...[
                      const SizedBox(width: AppTokens.spaceXs),
                      Container(
                        width: 8,
                        height: 8,
                        decoration: const BoxDecoration(
                          color: AppTokens.teal,
                          shape: BoxShape.circle,
                        ),
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  item.body,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: AppTokens.muted,
                    fontSize: 12,
                    height: 1.3,
                  ),
                ),
                const SizedBox(height: 6),
                Row(
                  children: [
                    AppBadge(
                      label: item.type.toUpperCase(),
                      color: item.statusColor,
                    ),
                    const SizedBox(width: AppTokens.spaceSm),
                    Text(
                      _formatDate(item.createdAt),
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
          const SizedBox(width: AppTokens.spaceSm),
          const Icon(
            Icons.chevron_right_rounded,
            color: AppTokens.muted,
            size: 20,
          ),
        ],
      ),
    );
  }
}
