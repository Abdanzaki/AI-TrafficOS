import 'package:flutter/material.dart';

import '../theme/app_tokens.dart';

/// User account representation for administrator user management.
class AppUser {
  const AppUser({
    required this.id,
    required this.email,
    required this.fullName,
    required this.role,
    this.isActive = true,
    this.createdAt,
  });

  final int id;
  final String email;
  final String fullName;
  final String role;
  final bool isActive;
  final DateTime? createdAt;

  /// Standard system roles.
  static const String roleAdmin = 'admin';
  static const String roleTrafficOfficer = 'traffic_officer';
  static const String roleAnalyst = 'analyst';

  bool get isAdmin => role.toLowerCase() == roleAdmin;
  bool get isTrafficOfficer => role.toLowerCase() == roleTrafficOfficer;
  bool get isAnalyst => role.toLowerCase() == roleAnalyst;
  bool get isReadOnly => isAnalyst;
  bool get canWrite => (isAdmin || isTrafficOfficer) && !isAnalyst;

  String get roleDisplay {
    switch (role.toLowerCase()) {
      case roleAdmin:
        return 'System Administrator';
      case roleTrafficOfficer:
        return 'Traffic Officer';
      case roleAnalyst:
        return 'Analyst (Read-Only)';
      default:
        return role;
    }
  }

  Color get roleBadgeColor {
    switch (role.toLowerCase()) {
      case roleAdmin:
        return const Color(0xFFA855F7);
      case roleTrafficOfficer:
        return AppTokens.teal;
      case roleAnalyst:
        return AppTokens.amber;
      default:
        return AppTokens.muted;
    }
  }

  factory AppUser.fromJson(Map<String, dynamic> json) {
    return AppUser(
      id: json['id'] as int? ?? 0,
      email: json['email'] as String? ?? '',
      fullName: (json['full_name'] ?? json['fullName'] ?? '') as String,
      role: (json['role_name'] ?? json['role'] ?? roleAnalyst) as String,
      isActive: json['is_active'] as bool? ?? true,
      createdAt: json['created_at'] != null
          ? DateTime.tryParse(json['created_at'].toString())
          : null,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'email': email,
      'full_name': fullName,
      'role_name': role,
      'is_active': isActive,
      'created_at': createdAt?.toIso8601String(),
    };
  }

  AppUser copyWith({
    int? id,
    String? email,
    String? fullName,
    String? role,
    bool? isActive,
    DateTime? createdAt,
  }) {
    return AppUser(
      id: id ?? this.id,
      email: email ?? this.email,
      fullName: fullName ?? this.fullName,
      role: role ?? this.role,
      isActive: isActive ?? this.isActive,
      createdAt: createdAt ?? this.createdAt,
    );
  }
}

/// Paginated collection of users returned by `GET /users`.
class PaginatedUsers {
  const PaginatedUsers({
    required this.items,
    required this.total,
    required this.page,
    required this.perPage,
    required this.pages,
  });

  final List<AppUser> items;
  final int total;
  final int page;
  final int perPage;
  final int pages;

  bool get hasNextPage => page < pages;

  factory PaginatedUsers.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'];
    final items = <AppUser>[];
    if (rawItems is List) {
      for (final item in rawItems) {
        if (item is Map<String, dynamic>) {
          items.add(AppUser.fromJson(item));
        }
      }
    }

    return PaginatedUsers(
      items: items,
      total: json['total'] as int? ?? items.length,
      page: json['page'] as int? ?? 1,
      perPage: json['per_page'] as int? ?? 20,
      pages: json['pages'] as int? ?? 1,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'items': items.map((e) => e.toJson()).toList(),
      'total': total,
      'page': page,
      'per_page': perPage,
      'pages': pages,
    };
  }
}
