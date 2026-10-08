import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/app_user.dart';
import '../models/user.dart';
import '../providers/realtime_providers.dart';
import '../services/api_client.dart';
import '../services/user_service.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_button.dart';
import '../widgets/app_card.dart';
import '../widgets/empty_state.dart';
import '../widgets/error_state.dart';
import '../widgets/loading_state.dart';
import '../widgets/offline_banner.dart';
import '../widgets/require_role.dart';

/// Screen managing operator user provisioning, roles, and deactivation (Admin restricted).
class UsersScreen extends StatelessWidget {
  const UsersScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return const RequireRole(
      allowedRoles: [User.roleAdmin],
      screenTitle: 'User Management',
      readOnlyMessage:
          'User administration and RBAC policy management requires System Administrator credentials.',
      child: _UsersScreenContent(),
    );
  }
}

class _UsersScreenContent extends ConsumerStatefulWidget {
  const _UsersScreenContent();

  @override
  ConsumerState<_UsersScreenContent> createState() =>
      _UsersScreenContentState();
}

class _UsersScreenContentState extends ConsumerState<_UsersScreenContent> {
  final ScrollController _scrollController = ScrollController();
  final List<AppUser> _users = [];
  bool _isLoading = true;
  bool _isLoadingMore = false;
  String? _errorMessage;
  int _page = 1;
  int _totalPages = 1;

  @override
  void initState() {
    super.initState();
    _loadInitialUsers();
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
      _loadMoreUsers();
    }
  }

  Future<void> _loadInitialUsers() async {
    setState(() {
      _page = 1;
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final service = ref.read(userServiceProvider);
      final paged = await service.getUsers(page: 1, perPage: 20);

      if (mounted) {
        setState(() {
          _users.clear();
          _users.addAll(paged.items);
          _totalPages = paged.pages;
          _isLoading = false;
        });
      }
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _errorMessage = e.isForbidden
              ? 'Access denied: Only system administrators may view operator accounts.'
              : e.message;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _errorMessage = 'Failed to load user accounts: $e';
          _isLoading = false;
        });
      }
    }
  }

  Future<void> _loadMoreUsers() async {
    if (_isLoadingMore) return;
    setState(() {
      _isLoadingMore = true;
    });

    try {
      final nextPage = _page + 1;
      final service = ref.read(userServiceProvider);
      final paged = await service.getUsers(page: nextPage, perPage: 20);

      if (mounted) {
        setState(() {
          _page = nextPage;
          _users.addAll(paged.items);
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

  void _showCreateUserSheet() {
    final formKey = GlobalKey<FormState>();
    final emailController = TextEditingController();
    final passwordController = TextEditingController();
    final nameController = TextEditingController();
    String selectedRole = AppUser.roleAnalyst;
    bool isSubmitting = false;

    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Theme.of(context).colorScheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
        side: BorderSide(color: AppTokens.borderOf(context)),
      ),
      builder: (ctx) {
        return StatefulBuilder(
          builder: (context, setSheetState) {
            return Padding(
              padding: EdgeInsets.only(
                left: AppTokens.spaceLg,
                right: AppTokens.spaceLg,
                top: AppTokens.spaceLg,
                bottom: MediaQuery.of(context).viewInsets.bottom +
                    AppTokens.spaceLg,
              ),
              child: SingleChildScrollView(
                child: Form(
                  key: formKey,
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
                      Text(
                        'Provision Operator Account',
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.onSurface,
                          fontSize: 18,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: AppTokens.spaceXs),
                      Text(
                        'Create a new municipal operator account with assigned RBAC permissions.',
                        style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 12),
                      ),
                      const SizedBox(height: AppTokens.spaceLg),
                      TextFormField(
                        controller: nameController,
                        decoration: const InputDecoration(
                          labelText: 'Full Name',
                          hintText: 'e.g. Jane Doe',
                          prefixIcon: Icon(Icons.person_outline_rounded),
                        ),
                        validator: (v) => (v == null || v.trim().isEmpty)
                            ? 'Full name is required'
                            : null,
                      ),
                      const SizedBox(height: AppTokens.spaceMd),
                      TextFormField(
                        controller: emailController,
                        keyboardType: TextInputType.emailAddress,
                        decoration: const InputDecoration(
                          labelText: 'Email Address',
                          hintText: 'operator@trafficos.city',
                          prefixIcon: Icon(Icons.email_outlined),
                        ),
                        validator: (v) {
                          if (v == null || v.trim().isEmpty) {
                            return 'Email is required';
                          }
                          if (!v.contains('@') || !v.contains('.')) {
                            return 'Enter a valid email address';
                          }
                          return null;
                        },
                      ),
                      const SizedBox(height: AppTokens.spaceMd),
                      TextFormField(
                        controller: passwordController,
                        obscureText: true,
                        decoration: const InputDecoration(
                          labelText: 'Password (min. 8 characters)',
                          prefixIcon: Icon(Icons.lock_outline_rounded),
                        ),
                        validator: (v) => (v == null || v.length < 8)
                            ? 'Password must be at least 8 characters'
                            : null,
                      ),
                      const SizedBox(height: AppTokens.spaceMd),
                      DropdownButtonFormField<String>(
                        initialValue: selectedRole,
                        decoration: const InputDecoration(
                          labelText: 'Assigned Role',
                          prefixIcon: Icon(Icons.shield_outlined),
                        ),
                        items: const [
                          DropdownMenuItem(
                            value: AppUser.roleAdmin,
                            child: Text('Administrator (Full Control)'),
                          ),
                          DropdownMenuItem(
                            value: AppUser.roleTrafficOfficer,
                            child: Text('Traffic Officer (Write Access)'),
                          ),
                          DropdownMenuItem(
                            value: AppUser.roleAnalyst,
                            child: Text('Analyst (Read-Only)'),
                          ),
                        ],
                        onChanged: (val) {
                          if (val != null) {
                            setSheetState(() => selectedRole = val);
                          }
                        },
                      ),
                      const SizedBox(height: AppTokens.spaceXl),
                      AppButton(
                        text: 'Create Account',
                        icon: Icons.person_add_rounded,
                        isLoading: isSubmitting,
                        onPressed: () async {
                          if (!formKey.currentState!.validate()) return;
                          setSheetState(() => isSubmitting = true);

                          final nav = Navigator.of(ctx);
                          final scaffold = ScaffoldMessenger.of(context);

                          try {
                            final service = ref.read(userServiceProvider);
                            final newUser = await service.createUser(
                              email: emailController.text.trim(),
                              password: passwordController.text,
                              fullName: nameController.text.trim(),
                              role: selectedRole,
                            );

                            if (mounted) {
                              nav.pop();
                              setState(() {
                                _users.insert(0, newUser);
                              });
                              scaffold.showSnackBar(
                                SnackBar(
                                  content: Text(
                                    'Operator ${newUser.fullName} created successfully',
                                  ),
                                  backgroundColor: AppTokens.success,
                                ),
                              );
                            }
                          } on ApiException catch (e) {
                            setSheetState(() => isSubmitting = false);
                            if (mounted) {
                              scaffold.showSnackBar(
                                SnackBar(
                                  content: Text(e.message),
                                  backgroundColor: AppTokens.danger,
                                ),
                              );
                            }
                          } catch (e) {
                            setSheetState(() => isSubmitting = false);
                            if (mounted) {
                              scaffold.showSnackBar(
                                SnackBar(
                                  content: Text('Failed to create user: $e'),
                                  backgroundColor: AppTokens.danger,
                                ),
                              );
                            }
                          }
                        },
                      ),
                    ],
                  ),
                ),
              ),
            );
          },
        );
      },
    );
  }

  void _showEditRoleDialog(AppUser user) {
    String selectedRole = user.role;
    final nameController = TextEditingController(text: user.fullName);
    bool isSaving = false;

    showDialog<void>(
      context: context,
      builder: (ctx) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return AlertDialog(
              backgroundColor: Theme.of(context).colorScheme.surface,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(16),
                side: BorderSide(color: AppTokens.borderOf(context)),
              ),
              title: const Text('Edit Operator Role'),
              content: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    user.email,
                    style: TextStyle(
                      color: AppTokens.mutedOf(context),
                      fontSize: 12,
                    ),
                  ),
                  const SizedBox(height: AppTokens.spaceMd),
                  TextField(
                    controller: nameController,
                    decoration: const InputDecoration(
                       labelText: 'Full Name',
                      prefixIcon: Icon(Icons.person_outline_rounded),
                    ),
                  ),
                  const SizedBox(height: AppTokens.spaceMd),
                  DropdownButtonFormField<String>(
                    initialValue: selectedRole,
                    decoration: const InputDecoration(
                      labelText: 'Assigned Role',
                      prefixIcon: Icon(Icons.shield_outlined),
                    ),
                    items: const [
                      DropdownMenuItem(
                        value: AppUser.roleAdmin,
                        child: Text('Administrator'),
                      ),
                      DropdownMenuItem(
                        value: AppUser.roleTrafficOfficer,
                        child: Text('Traffic Officer'),
                      ),
                      DropdownMenuItem(
                        value: AppUser.roleAnalyst,
                        child: Text('Analyst (Read-Only)'),
                      ),
                    ],
                    onChanged: (val) {
                      if (val != null) {
                        setDialogState(() => selectedRole = val);
                      }
                    },
                  ),
                ],
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(ctx).pop(),
                  child: Text('Cancel', style: TextStyle(color: AppTokens.mutedOf(context))),
                ),
                ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppTokens.teal,
                    foregroundColor: Theme.of(context).brightness == Brightness.dark
                        ? AppTokens.ink
                        : Colors.white,
                  ),
                  onPressed: isSaving
                      ? null
                      : () async {
                          setDialogState(() => isSaving = true);
                          final nav = Navigator.of(ctx);
                          final scaffold = ScaffoldMessenger.of(context);
                          try {
                            final service = ref.read(userServiceProvider);
                            final updated = await service.updateUser(
                              user.id,
                              fullName: nameController.text.trim(),
                              role: selectedRole,
                            );

                            if (mounted) {
                              nav.pop();
                              final index =
                                  _users.indexWhere((u) => u.id == user.id);
                              if (index != -1) {
                                setState(() {
                                  _users[index] = updated;
                                });
                              }
                              scaffold.showSnackBar(
                                SnackBar(
                                  content: Text(
                                    'Role updated for ${updated.fullName}',
                                  ),
                                  backgroundColor: AppTokens.success,
                                ),
                              );
                            }
                          } on ApiException catch (e) {
                            setDialogState(() => isSaving = false);
                            if (mounted) {
                              scaffold.showSnackBar(
                                SnackBar(
                                  content: Text(e.message),
                                  backgroundColor: AppTokens.danger,
                                ),
                              );
                            }
                          } catch (e) {
                            setDialogState(() => isSaving = false);
                            if (mounted) {
                              scaffold.showSnackBar(
                                SnackBar(
                                  content: Text('Failed to update role: $e'),
                                  backgroundColor: AppTokens.danger,
                                ),
                              );
                            }
                          }
                        },
                  child: isSaving
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Save Changes'),
                ),
              ],
            );
          },
        );
      },
    );
  }

  void _confirmDeactivateUser(AppUser user) {
    final scaffold = ScaffoldMessenger.of(context);
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: Theme.of(context).colorScheme.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: BorderSide(color: AppTokens.borderOf(context)),
        ),
        title: const Text('Deactivate Operator Account'),
        content: Text(
          'Are you sure you want to deactivate ${user.fullName} (${user.email})? They will immediately lose access to all municipal systems.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: Text('Cancel', style: TextStyle(color: AppTokens.mutedOf(context))),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: AppTokens.danger,
              foregroundColor: Colors.white,
            ),
            onPressed: () async {
              Navigator.of(ctx).pop();
              try {
                final service = ref.read(userServiceProvider);
                final deactivated = await service.deleteUser(user.id);

                if (mounted) {
                  final index = _users.indexWhere((u) => u.id == user.id);
                  if (index != -1) {
                    setState(() {
                      _users[index] = deactivated;
                    });
                  }
                  scaffold.showSnackBar(
                    SnackBar(
                      content: Text(
                        'Account ${user.fullName} has been deactivated',
                      ),
                      backgroundColor: AppTokens.danger,
                    ),
                  );
                }
              } on ApiException catch (e) {
                if (mounted) {
                  scaffold.showSnackBar(
                    SnackBar(
                      content: Text(e.message),
                      backgroundColor: AppTokens.danger,
                    ),
                  );
                }
              } catch (e) {
                if (mounted) {
                  scaffold.showSnackBar(
                    SnackBar(
                      content: Text('Failed to deactivate account: $e'),
                      backgroundColor: AppTokens.danger,
                    ),
                  );
                }
              }
            },
            child: const Text('Deactivate'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('User Management'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Refresh Users',
            onPressed: _loadInitialUsers,
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: AppTokens.teal,
        foregroundColor: Theme.of(context).brightness == Brightness.dark
            ? AppTokens.ink
            : Colors.white,
        icon: const Icon(Icons.person_add_rounded),
        label: const Text('New User'),
        onPressed: _showCreateUserSheet,
      ),
      body: SafeArea(
        child: Column(
          children: [
            if (ref.watch(isOfflineProvider)) const OfflineBanner(),
            Expanded(child: _buildBody()),
          ],
        ),
      ),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const LoadingState(message: 'Loading operator accounts...');
    }

    if (_errorMessage != null) {
      return ErrorState(
        message: _errorMessage!,
        onRetry: _loadInitialUsers,
      );
    }

    if (_users.isEmpty) {
      return RefreshIndicator(
        onRefresh: _loadInitialUsers,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          children: [
            SizedBox(
              height: MediaQuery.of(context).size.height * 0.6,
              child: const EmptyState(
                icon: Icons.people_outline_rounded,
                title: 'No User Accounts Found',
                message: 'No registered system operators are currently available.',
              ),
            ),
          ],
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: _loadInitialUsers,
      child: ListView.separated(
        controller: _scrollController,
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.only(
          left: AppTokens.spaceMd,
          right: AppTokens.spaceMd,
          top: AppTokens.spaceMd,
          bottom: 80, // Accommodate FAB
        ),
        itemCount: _users.length + (_isLoadingMore ? 1 : 0),
        separatorBuilder: (context, index) =>
            const SizedBox(height: AppTokens.spaceSm),
        itemBuilder: (context, index) {
          if (index == _users.length) {
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

          final u = _users[index];
          return _buildUserCard(u);
        },
      ),
    );
  }

  Widget _buildUserCard(AppUser user) {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      child: Row(
        children: [
          CircleAvatar(
            radius: 20,
            backgroundColor: user.roleBadgeColor.withAlpha(30),
            child: Text(
              user.fullName.isNotEmpty
                  ? user.fullName.substring(0, 1).toUpperCase()
                  : 'U',
              style: TextStyle(
                color: user.roleBadgeColor,
                fontWeight: FontWeight.w700,
                fontSize: 14,
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
                    Flexible(
                      child: Text(
                        user.fullName,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.onSurface,
                          fontWeight: FontWeight.w700,
                          fontSize: 14,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    const SizedBox(width: AppTokens.spaceXs),
                    if (!user.isActive)
                      const AppBadge(
                        label: 'INACTIVE',
                        color: AppTokens.danger,
                      ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  user.email,
                  style: TextStyle(
                    color: AppTokens.mutedOf(context),
                    fontSize: 12,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 6),
                AppBadge(
                  label: user.role.toUpperCase(),
                  color: user.roleBadgeColor,
                ),
              ],
            ),
          ),
          PopupMenuButton<String>(
            tooltip: 'Operator Actions',
            icon: Icon(Icons.more_vert_rounded, color: AppTokens.mutedOf(context)),
            color: Theme.of(context).colorScheme.surface,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
              side: BorderSide(color: AppTokens.borderOf(context)),
            ),
            itemBuilder: (ctx) => [
              const PopupMenuItem(
                value: 'edit',
                child: Row(
                  children: [
                    Icon(Icons.edit_outlined, size: 18, color: AppTokens.teal),
                    SizedBox(width: AppTokens.spaceSm),
                    Text('Edit Role / Name'),
                  ],
                ),
              ),
              if (user.isActive)
                const PopupMenuItem(
                  value: 'deactivate',
                  child: Row(
                    children: [
                      Icon(Icons.block_rounded, size: 18, color: AppTokens.danger),
                      SizedBox(width: AppTokens.spaceSm),
                      Text('Deactivate Account', style: TextStyle(color: AppTokens.danger)),
                    ],
                  ),
                ),
            ],
            onSelected: (val) {
              if (val == 'edit') {
                _showEditRoleDialog(user);
              } else if (val == 'deactivate') {
                _confirmDeactivateUser(user);
              }
            },
          ),
        ],
      ),
    );
  }
}
