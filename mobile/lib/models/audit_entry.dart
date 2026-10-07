import 'package:flutter/material.dart';

import '../theme/app_tokens.dart';

/// Immutable system audit log entry recording administrative and operational events.
class AuditEntry {
  const AuditEntry({
    required this.id,
    required this.action,
    required this.actorEmail,
    required this.entity,
    required this.createdAt,
    this.actorUserId,
    this.entityId,
    this.details = const {},
    this.ipAddress,
  });

  final int id;
  final String action;
  final String actorEmail;
  final String entity;
  final DateTime createdAt;
  final int? actorUserId;
  final int? entityId;
  final Map<String, dynamic> details;
  final String? ipAddress;

  /// Semantic color for action chips based on operation type.
  Color get actionColor {
    final lower = action.toLowerCase();
    if (lower.contains('delete') || lower.contains('deactivate')) {
      return AppTokens.danger;
    }
    if (lower.contains('create') || lower.contains('login') || lower.contains('applied')) {
      return AppTokens.success;
    }
    if (lower.contains('update') || lower.contains('override') || lower.contains('prioritize')) {
      return AppTokens.amber;
    }
    return AppTokens.teal;
  }

  /// Parses an [AuditEntry] safely from backend JSON.
  factory AuditEntry.fromJson(Map<String, dynamic> json) {
    String actor = 'System';
    if (json['actor_email'] != null && json['actor_email'].toString().isNotEmpty) {
      actor = json['actor_email'].toString();
    } else if (json['actor'] is Map && (json['actor'] as Map)['email'] != null) {
      actor = (json['actor'] as Map)['email'].toString();
    } else if (json['actor_user_id'] != null) {
      actor = 'Operator #${json['actor_user_id']}';
    }

    final entity = (json['entity'] ?? json['entity_type'] ?? 'system').toString();

    DateTime parsedDate;
    if (json['created_at'] != null) {
      parsedDate =
          DateTime.tryParse(json['created_at'].toString()) ?? DateTime.now();
    } else {
      parsedDate = DateTime.now();
    }

    Map<String, dynamic> parsedDetails = const {};
    if (json['details'] is Map) {
      parsedDetails = Map<String, dynamic>.from(json['details'] as Map);
    }

    return AuditEntry(
      id: json['id'] as int? ?? 0,
      action: json['action'] as String? ?? 'unknown',
      actorEmail: actor,
      entity: entity,
      createdAt: parsedDate,
      actorUserId: json['actor_user_id'] as int?,
      entityId: json['entity_id'] as int?,
      details: parsedDetails,
      ipAddress: json['ip_address'] as String?,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'action': action,
      'actor_email': actorEmail,
      'entity': entity,
      'created_at': createdAt.toIso8601String(),
      if (actorUserId != null) 'actor_user_id': actorUserId,
      if (entityId != null) 'entity_id': entityId,
      'details': details,
      if (ipAddress != null) 'ip_address': ipAddress,
    };
  }
}

/// Paginated audit logs response container.
class PaginatedAuditEntries {
  const PaginatedAuditEntries({
    required this.items,
    required this.total,
    required this.page,
    required this.perPage,
    required this.pages,
  });

  final List<AuditEntry> items;
  final int total;
  final int page;
  final int perPage;
  final int pages;

  bool get hasNextPage => page < pages;

  factory PaginatedAuditEntries.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'];
    final items = <AuditEntry>[];
    if (rawItems is List) {
      for (final item in rawItems) {
        if (item is Map<String, dynamic>) {
          items.add(AuditEntry.fromJson(item));
        }
      }
    }

    return PaginatedAuditEntries(
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
