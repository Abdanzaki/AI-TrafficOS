import 'package:flutter/material.dart';

import '../theme/app_tokens.dart';

/// User profile representation for AI TrafficOS authentication.
class User {
  const User({
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

  /// Role identifiers.
  static const String roleAdmin = 'admin';
  static const String roleTrafficOfficer = 'traffic_officer';
  static const String roleAnalyst = 'analyst';

  /// Whether user has full administrator permissions.
  bool get isAdmin => role == roleAdmin;

  /// Whether user has active traffic control officer permissions.
  bool get isTrafficOfficer => role == roleTrafficOfficer;

  /// Whether user has analyst permissions (read-only system wide).
  bool get isAnalyst => role == roleAnalyst;

  /// Analyst is read-only everywhere across the system.
  bool get isReadOnly => isAnalyst;

  /// Whether user has operational write permissions (officer or admin).
  bool get canWrite => (isAdmin || isTrafficOfficer) && !isAnalyst;

  /// User-friendly display title for the role.
  String get roleDisplay {
    switch (role) {
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

  /// Semantic badge color for the role in dark mode.
  Color get roleBadgeColor {
    switch (role) {
      case roleAdmin:
        return const Color(0xFFA855F7); // Purple accent for Admin
      case roleTrafficOfficer:
        return AppTokens.teal; // Teal accent for Traffic Officer
      case roleAnalyst:
        return AppTokens.amber; // Amber accent for Read-Only Analyst
      default:
        return AppTokens.muted;
    }
  }

  factory User.fromJson(Map<String, dynamic> json) {
    return User(
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

  User copyWith({
    int? id,
    String? email,
    String? fullName,
    String? role,
    bool? isActive,
    DateTime? createdAt,
  }) {
    return User(
      id: id ?? this.id,
      email: email ?? this.email,
      fullName: fullName ?? this.fullName,
      role: role ?? this.role,
      isActive: isActive ?? this.isActive,
      createdAt: createdAt ?? this.createdAt,
    );
  }

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is User &&
          runtimeType == other.runtimeType &&
          id == other.id &&
          email == other.email &&
          role == other.role;

  @override
  int get hashCode => id.hashCode ^ email.hashCode ^ role.hashCode;
}
