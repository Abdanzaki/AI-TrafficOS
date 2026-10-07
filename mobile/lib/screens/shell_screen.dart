import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/user.dart';
import '../services/auth_service.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_card.dart';
import '../widgets/empty_state.dart';
import '../widgets/offline_banner.dart';
import '../widgets/require_role.dart';
import '../services/notification_service.dart';
import 'analytics_screen.dart';
import 'audit_screen.dart';
import 'control_screen.dart';
import 'dashboard_screen.dart';
import 'decisions_screen.dart';
import 'emergency_screen.dart';
import 'health_screen.dart';
import 'incidents_screen.dart';
import 'map_screen.dart';
import 'notifications_screen.dart';
import 'predictions_screen.dart';
import 'routing_screen.dart';
import 'signals_screen.dart';
import 'traffic_screen.dart';
import 'users_screen.dart';

/// Navigation item definition for overflow subsystems.
class SubsystemItem {
  const SubsystemItem({
    required this.id,
    required this.title,
    required this.description,
    required this.icon,
    this.adminOnly = false,
    this.requiresWriteRole = false,
  });

  final String id;
  final String title;
  final String description;
  final IconData icon;
  final bool adminOnly;
  final bool requiresWriteRole;
}

/// Main Application Shell for AI TrafficOS.
///
/// Features:
/// - Material 3 [NavigationBar] with 5 primary destinations (Dashboard, Traffic, Map, Incidents, More)
/// - Role-aware filtering: Admin-only modules (Users) and Write actions (Control, Emergency)
/// - Top App Bar featuring active operator status, role badge, and session controls
/// - Seamless integration with [OfflineBanner] and backend connectivity
class ShellScreen extends ConsumerStatefulWidget {
  const ShellScreen({super.key});

  @override
  ConsumerState<ShellScreen> createState() => _ShellScreenState();
}

class _ShellScreenState extends ConsumerState<ShellScreen> {
  int _currentIndex = 0;
  bool _isOffline = false;

  final List<SubsystemItem> _allSubsystems = const [
    SubsystemItem(
      id: 'signals',
      title: 'Signals',
      description: 'Traffic light state machine & optical phase detection',
      icon: Icons.traffic_rounded,
    ),
    SubsystemItem(
      id: 'control',
      title: 'Control',
      description: 'Adaptive timing configuration & manual signal overrides',
      icon: Icons.tune_rounded,
    ),
    SubsystemItem(
      id: 'predictions',
      title: 'Predictions',
      description: 'Deep learning congestion forecasting & flow trends',
      icon: Icons.timeline_rounded,
    ),
    SubsystemItem(
      id: 'decisions',
      title: 'Decisions',
      description: 'AI coordination engine policy decisions and explanations',
      icon: Icons.psychology_rounded,
    ),
    SubsystemItem(
      id: 'emergency',
      title: 'Emergency',
      description: 'Audio-visual siren detection and green wave corridors',
      icon: Icons.emergency_rounded,
      requiresWriteRole: true,
    ),
    SubsystemItem(
      id: 'routing',
      title: 'Routing',
      description: 'Multi-criteria dynamic municipal vehicle routing',
      icon: Icons.alt_route_rounded,
    ),
    SubsystemItem(
      id: 'analytics',
      title: 'Analytics',
      description: 'Corridor throughput, average vehicle delay, and density KPIs',
      icon: Icons.insights_rounded,
    ),
    SubsystemItem(
      id: 'notifications',
      title: 'Notifications',
      description: 'High-priority dispatch advisories and system alerts',
      icon: Icons.notifications_active_rounded,
    ),
    SubsystemItem(
      id: 'audit',
      title: 'Audit Log',
      description: 'Immutable operational audit events and security logs',
      icon: Icons.fact_check_rounded,
      adminOnly: true,
    ),
    SubsystemItem(
      id: 'health',
      title: 'System Health',
      description: 'API services, database pools, and ML worker heartbeat',
      icon: Icons.favorite_rounded,
    ),
    SubsystemItem(
      id: 'users',
      title: 'Users & Roles',
      description: 'Operator accounts, RBAC policies, and permissions',
      icon: Icons.people_rounded,
      adminOnly: true,
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(currentUserProvider);
    final theme = Theme.of(context);

    return Scaffold(
      appBar: _buildAppBar(context, user, theme),
      body: Column(
        children: [
          if (_isOffline)
            OfflineBanner(
              onRetry: () async {
                final client = ref.read(apiClientProvider);
                final res = await client.getHealth();
                setState(() {
                  _isOffline = res.isFailure;
                });
              },
            ),
          Expanded(
            child: IndexedStack(
              index: _currentIndex,
              children: [
                _buildDashboardTab(context),
                _buildTrafficTab(context),
                _buildMapTab(context),
                _buildIncidentsTab(context),
                _buildMoreTab(context, user),
              ],
            ),
          ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex,
        onDestinationSelected: (index) {
          setState(() {
            _currentIndex = index;
          });
        },
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.dashboard_outlined),
            selectedIcon: Icon(Icons.dashboard_rounded),
            label: 'Dashboard',
          ),
          NavigationDestination(
            icon: Icon(Icons.speed_outlined),
            selectedIcon: Icon(Icons.speed_rounded),
            label: 'Traffic',
          ),
          NavigationDestination(
            icon: Icon(Icons.map_outlined),
            selectedIcon: Icon(Icons.map_rounded),
            label: 'Map',
          ),
          NavigationDestination(
            icon: Icon(Icons.warning_amber_outlined),
            selectedIcon: Icon(Icons.warning_amber_rounded),
            label: 'Incidents',
          ),
          NavigationDestination(
            icon: Icon(Icons.more_horiz_outlined),
            selectedIcon: Icon(Icons.more_horiz_rounded),
            label: 'More',
          ),
        ],
      ),
    );
  }

  PreferredSizeWidget _buildAppBar(
    BuildContext context,
    User? user,
    ThemeData theme,
  ) {
    return AppBar(
      titleSpacing: AppTokens.spaceMd,
      title: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(6),
            decoration: BoxDecoration(
              color: AppTokens.teal.withAlpha(30),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(
                color: AppTokens.teal.withAlpha(80),
              ),
            ),
            child: const Icon(
              Icons.traffic_rounded,
              color: AppTokens.teal,
              size: 20,
            ),
          ),
          const SizedBox(width: AppTokens.spaceSm),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                'AI TrafficOS',
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w800,
                  color: AppTokens.textPrimary,
                ),
              ),
              Text(
                _getTabTitle(_currentIndex),
                style: theme.textTheme.bodySmall?.copyWith(
                  color: AppTokens.muted,
                  fontSize: 11,
                ),
              ),
            ],
          ),
        ],
      ),
      actions: [
        if (user != null) ...[
          Consumer(
            builder: (context, ref, _) {
              final unreadAsync = ref.watch(unreadNotificationCountProvider);
              final unreadCount = unreadAsync.asData?.value ?? 0;
              return IconButton(
                tooltip: 'Notifications',
                icon: Badge(
                  isLabelVisible: unreadCount > 0,
                  label: Text('$unreadCount'),
                  child: const Icon(Icons.notifications_outlined),
                ),
                onPressed: () {
                  Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => const NotificationsScreen(),
                    ),
                  );
                },
              );
            },
          ),
          PopupMenuButton<String>(
            tooltip: 'Operator Profile',
            offset: const Offset(0, 48),
            color: AppTokens.card,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
              side: const BorderSide(color: AppTokens.borderDark),
            ),
            child: Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: AppTokens.spaceSm,
                vertical: AppTokens.spaceXs,
              ),
              child: Row(
                children: [
                  AppBadge(
                    label: user.role.toUpperCase(),
                    color: user.roleBadgeColor,
                  ),
                  const SizedBox(width: AppTokens.spaceXs),
                  CircleAvatar(
                    radius: 15,
                    backgroundColor: AppTokens.surface,
                    child: Text(
                      user.fullName.isNotEmpty
                          ? user.fullName.substring(0, 1).toUpperCase()
                          : 'U',
                      style: const TextStyle(
                        color: AppTokens.textPrimary,
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            itemBuilder: (context) => [
              PopupMenuItem(
                enabled: false,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      user.fullName,
                      style: const TextStyle(
                        color: AppTokens.textPrimary,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    Text(
                      user.email,
                      style: const TextStyle(
                        color: AppTokens.muted,
                        fontSize: 11,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      user.roleDisplay,
                      style: TextStyle(
                        color: user.roleBadgeColor,
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              ),
              const PopupMenuDivider(),
              PopupMenuItem(
                value: 'logout',
                child: const Row(
                  children: [
                    Icon(
                      Icons.logout_rounded,
                      color: AppTokens.danger,
                      size: 18,
                    ),
                    SizedBox(width: AppTokens.spaceSm),
                    Text(
                      'Sign Out',
                      style: TextStyle(
                        color: AppTokens.danger,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              ),
            ],
            onSelected: (value) {
              if (value == 'logout') {
                _confirmSignOut(context);
              }
            },
          ),
        ],
        const SizedBox(width: AppTokens.spaceSm),
      ],
    );
  }

  void _confirmSignOut(BuildContext context) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTokens.card,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: AppTokens.borderDark),
        ),
        title: const Text('Sign Out Confirmation'),
        content: const Text(
          'Are you sure you want to end your current municipal session?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('Cancel', style: TextStyle(color: AppTokens.muted)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: AppTokens.danger,
              foregroundColor: Colors.white,
            ),
            onPressed: () {
              Navigator.of(ctx).pop();
              ref.read(authStateProvider.notifier).logout();
            },
            child: const Text('Sign Out'),
          ),
        ],
      ),
    );
  }

  String _getTabTitle(int index) {
    switch (index) {
      case 0:
        return 'System Overview';
      case 1:
        return 'Corridor Flow';
      case 2:
        return 'Spatial Network';
      case 3:
        return 'Incidents & Alerts';
      case 4:
        return 'System Modules';
      default:
        return '';
    }
  }

  Widget _buildDashboardTab(BuildContext context) {
    return DashboardScreen(
      onNavigateTab: (tabIndex) {
        setState(() {
          _currentIndex = tabIndex.clamp(0, 4);
        });
      },
    );
  }

  Widget _buildTrafficTab(BuildContext context) {
    return const TrafficScreen();
  }

  Widget _buildMapTab(BuildContext context) {
    return const MapScreen();
  }

  Widget _buildIncidentsTab(BuildContext context) {
    return const IncidentsScreen();
  }

  Widget _buildMoreTab(BuildContext context, User? user) {
    final theme = Theme.of(context);

    // Filter subsystems:
    // - Admin only items (Users) visible only for admins
    final visibleSubsystems = _allSubsystems.where((item) {
      if (item.adminOnly && !(user?.isAdmin ?? false)) {
        return false;
      }
      return true;
    }).toList();

    return ListView(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      children: [
        AppCard(
          padding: const EdgeInsets.all(AppTokens.spaceLg),
          child: Row(
            children: [
              CircleAvatar(
                radius: 24,
                backgroundColor: (user?.roleBadgeColor ?? AppTokens.teal).withAlpha(40),
                child: Icon(
                  Icons.shield_outlined,
                  color: user?.roleBadgeColor ?? AppTokens.teal,
                  size: 24,
                ),
              ),
              const SizedBox(width: AppTokens.spaceMd),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      user?.fullName ?? 'Operator',
                      style: theme.textTheme.titleMedium?.copyWith(
                        color: AppTokens.textPrimary,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    Text(
                      user?.roleDisplay ?? 'Operator Session',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: user?.roleBadgeColor ?? AppTokens.muted,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    Text(
                      user?.email ?? '',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: AppTokens.muted,
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              ),
              if (user?.isAnalyst ?? false)
                const AppBadge(
                  label: 'Read-Only',
                  color: AppTokens.amber,
                ),
            ],
          ),
        ),
        const SizedBox(height: AppTokens.spaceLg),
        Text(
          'Operational Subsystems',
          style: theme.textTheme.titleMedium?.copyWith(
            color: AppTokens.textPrimary,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: AppTokens.spaceSm),
        ...visibleSubsystems.map((item) {
          final isRestrictedForAnalyst =
              item.requiresWriteRole && (user?.isAnalyst ?? false);

          return Padding(
            padding: const EdgeInsets.only(bottom: AppTokens.spaceSm),
            child: AppCard(
              padding: const EdgeInsets.symmetric(
                horizontal: AppTokens.spaceMd,
                vertical: AppTokens.spaceMd,
              ),
              child: ListTile(
                contentPadding: EdgeInsets.zero,
                leading: Container(
                  width: 42,
                  height: 42,
                  decoration: BoxDecoration(
                    color: isRestrictedForAnalyst
                        ? AppTokens.amber.withAlpha(25)
                        : AppTokens.teal.withAlpha(25),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                      color: isRestrictedForAnalyst
                          ? AppTokens.amber.withAlpha(70)
                          : AppTokens.teal.withAlpha(60),
                    ),
                  ),
                  child: Icon(
                    item.icon,
                    color: isRestrictedForAnalyst
                        ? AppTokens.amber
                        : AppTokens.teal,
                    size: 22,
                  ),
                ),
                title: Row(
                  children: [
                    Text(
                      item.title,
                      style: theme.textTheme.titleSmall?.copyWith(
                        color: AppTokens.textPrimary,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    if (item.adminOnly) ...[
                      const SizedBox(width: AppTokens.spaceSm),
                      const AppBadge(
                        label: 'Admin',
                        color: Color(0xFFA855F7),
                      ),
                    ],
                    if (isRestrictedForAnalyst) ...[
                      const SizedBox(width: AppTokens.spaceSm),
                      const AppBadge(
                        label: 'Read-Only',
                        color: AppTokens.amber,
                      ),
                    ],
                  ],
                ),
                subtitle: Text(
                  item.description,
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: AppTokens.muted,
                    fontSize: 12,
                  ),
                ),
                trailing: const Icon(
                  Icons.chevron_right_rounded,
                  color: AppTokens.muted,
                ),
                onTap: () {
                  _openSubsystemDetail(context, item);
                },
              ),
            ),
          );
        }),
      ],
    );
  }

  void _openSubsystemDetail(BuildContext context, SubsystemItem item) {
    Widget? targetScreen;
    switch (item.id) {
      case 'signals':
        targetScreen = const SignalsScreen();
        break;
      case 'control':
        targetScreen = const ControlScreen();
        break;
      case 'predictions':
        targetScreen = const PredictionsScreen();
        break;
      case 'decisions':
        targetScreen = const DecisionsScreen();
        break;
      case 'emergency':
        targetScreen = const EmergencyScreen();
        break;
      case 'routing':
        targetScreen = const RoutingScreen();
        break;
      case 'analytics':
        targetScreen = const AnalyticsScreen();
        break;
      case 'incidents':
        targetScreen = const IncidentsScreen();
        break;
      case 'notifications':
        targetScreen = const NotificationsScreen();
        break;
      case 'audit':
        targetScreen = const AuditScreen();
        break;
      case 'health':
        targetScreen = const HealthScreen();
        break;
      case 'users':
        targetScreen = const UsersScreen();
        break;
    }

    if (targetScreen != null) {
      Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => targetScreen!),
      );
      return;
    }

    Widget content = Scaffold(
      appBar: AppBar(
        title: Text(item.title),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(AppTokens.spaceLg),
          children: [
            AppCard(
              padding: const EdgeInsets.all(AppTokens.spaceLg),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(item.icon, color: AppTokens.teal, size: 28),
                      const SizedBox(width: AppTokens.spaceSm),
                      Text(
                        item.title,
                        style: const TextStyle(
                          color: AppTokens.textPrimary,
                          fontSize: 18,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: AppTokens.spaceSm),
                  Text(
                    item.description,
                    style: const TextStyle(color: AppTokens.muted),
                  ),
                ],
              ),
            ),
            const SizedBox(height: AppTokens.spaceXl),
            EmptyState(
              icon: item.icon,
              title: '${item.title} Module Ready',
              message:
                  'Integrated with AI TrafficOS API prefix /api/v1. Live operational controls available.',
            ),
          ],
        ),
      ),
    );

    // Apply role guard if write action or admin only
    if (item.adminOnly) {
      content = RequireRole(
        allowedRoles: const [User.roleAdmin],
        screenTitle: item.title,
        child: content,
      );
    } else if (item.requiresWriteRole) {
      content = RequireRole(
        allowedRoles: const [User.roleAdmin, User.roleTrafficOfficer],
        screenTitle: item.title,
        child: content,
      );
    }

    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => content),
    );
  }
}
