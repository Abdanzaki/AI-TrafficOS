import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/user.dart';
import '../services/auth_service.dart';
import '../theme/app_tokens.dart';
import 'app_badge.dart';
import 'app_card.dart';

/// Role-based access guard widget.
///
/// Ensures the currently authenticated user possesses one of [allowedRoles].
/// If the user possesses the read-only 'analyst' role or lacks sufficient
/// permissions, blocks write screens and displays a clear explanation.
class RequireRole extends ConsumerWidget {
  const RequireRole({
    super.key,
    required this.allowedRoles,
    required this.child,
    this.fallback,
    this.screenTitle,
    this.readOnlyMessage,
  });

  /// The list of role strings allowed to access [child] (e.g. `['admin', 'traffic_officer']`).
  final List<String> allowedRoles;

  /// The protected write screen or widget to render when authorized.
  final Widget child;

  /// Optional custom fallback widget when access is denied.
  final Widget? fallback;

  /// Optional name of the protected screen or feature (e.g. 'Manual Signal Control').
  final String? screenTitle;

  /// Custom explanation message for read-only roles.
  final String? readOnlyMessage;

  /// Helper utility to test if a given user has one of [allowedRoles].
  static bool hasRole(User? user, List<String> allowedRoles) {
    if (user == null) return false;
    return allowedRoles.contains(user.role);
  }

  /// Helper utility checking if the user is in write-permitted roles.
  static bool canWrite(User? user) {
    if (user == null) return false;
    return user.isAdmin || user.isTrafficOfficer;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(currentUserProvider);

    if (user != null && allowedRoles.contains(user.role)) {
      return child;
    }

    if (fallback != null) {
      return fallback!;
    }

    return _buildAccessDeniedView(context, user);
  }

  Widget _buildAccessDeniedView(BuildContext context, User? user) {
    final theme = Theme.of(context);
    final isAnalyst = user?.isAnalyst ?? false;

    final defaultMessage = isAnalyst
        ? "Your account is assigned the 'Analyst' role, which has read-only access throughout the platform. Manual signal controls, algorithm overrides, and emergency preemptions are strictly restricted to authorized Traffic Officers and Administrators."
        : 'You do not have sufficient permissions to access this screen. Please contact your system administrator for elevated privileges.';

    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(AppTokens.spaceLg),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: AppCard(
            padding: const EdgeInsets.all(AppTokens.spaceXl),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Container(
                  width: 68,
                  height: 68,
                  decoration: BoxDecoration(
                    color: AppTokens.amber.withAlpha(30),
                    shape: BoxShape.circle,
                    border: Border.all(
                      color: AppTokens.amber.withAlpha(120),
                      width: 2,
                    ),
                    boxShadow: const [
                      BoxShadow(
                        color: Color(0x33FFB800),
                        blurRadius: 18,
                        spreadRadius: 2,
                      ),
                    ],
                  ),
                  child: const Center(
                    child: Icon(
                      Icons.lock_outline_rounded,
                      color: AppTokens.amber,
                      size: 34,
                    ),
                  ),
                ),
                const SizedBox(height: AppTokens.spaceLg),
                Text(
                  isAnalyst ? 'Read-Only Role Restricted' : 'Access Restricted',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.headlineSmall?.copyWith(
                    color: theme.colorScheme.onSurface,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                if (screenTitle != null) ...[
                  const SizedBox(height: AppTokens.spaceXs),
                  Text(
                    screenTitle!,
                    textAlign: TextAlign.center,
                    style: theme.textTheme.titleSmall?.copyWith(
                      color: AppTokens.teal,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
                const SizedBox(height: AppTokens.spaceMd),
                Text(
                  readOnlyMessage ?? defaultMessage,
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: AppTokens.mutedOf(context),
                    height: 1.5,
                  ),
                ),
                const SizedBox(height: AppTokens.spaceLg),
                Divider(color: theme.colorScheme.outline),
                const SizedBox(height: AppTokens.spaceMd),
                Wrap(
                  spacing: AppTokens.spaceSm,
                  runSpacing: AppTokens.spaceSm,
                  alignment: WrapAlignment.center,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    AppBadge(
                      label: 'Your Role: ${user?.roleDisplay ?? "Unknown"}',
                      color: user?.roleBadgeColor ?? AppTokens.mutedOf(context),
                    ),
                    AppBadge(
                      label: 'Required: ${allowedRoles.join(" or ")}',
                      color: AppTokens.teal,
                    ),
                  ],
                ),
                const SizedBox(height: AppTokens.spaceLg),
                if (Navigator.of(context).canPop())
                  OutlinedButton.icon(
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.arrow_back_rounded, size: 18),
                    label: const Text('Go Back'),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: theme.colorScheme.onSurface,
                      side: BorderSide(color: theme.colorScheme.outline),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
