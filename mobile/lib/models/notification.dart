import 'package:flutter/material.dart';

import '../theme/app_tokens.dart';

/// Notification model representing operator advisories, alerts, and system broadcasts.
class AppNotification {
  const AppNotification({
    required this.id,
    required this.title,
    required this.body,
    required this.type,
    required this.isRead,
    required this.createdAt,
    this.userId,
    this.entityType,
    this.entityId,
    this.updatedAt,
  });

  final int id;
  final String title;
  final String body;
  final String type;
  final bool isRead;
  final DateTime createdAt;
  final int? userId;
  final String? entityType;
  final int? entityId;
  final DateTime? updatedAt;

  /// Semantic alias for message body.
  String get message => body;

  /// Semantic alias for notification severity level.
  String get severity => type;

  /// Semantic badge and accent color corresponding to notification urgency.
  Color get statusColor {
    switch (type.toLowerCase()) {
      case 'critical':
      case 'error':
        return AppTokens.danger;
      case 'warning':
        return AppTokens.amber;
      case 'success':
        return AppTokens.success;
      case 'info':
      default:
        return AppTokens.teal;
    }
  }

  /// Icon representing notification severity / type.
  IconData get icon {
    switch (type.toLowerCase()) {
      case 'critical':
      case 'error':
        return Icons.error_outline_rounded;
      case 'warning':
        return Icons.warning_amber_rounded;
      case 'success':
        return Icons.check_circle_outline_rounded;
      case 'info':
      default:
        return Icons.info_outline_rounded;
    }
  }

  /// Null-safe factory parsing backend JSON responses.
  factory AppNotification.fromJson(Map<String, dynamic> json) {
    DateTime parsedCreatedAt;
    if (json['created_at'] != null) {
      parsedCreatedAt =
          DateTime.tryParse(json['created_at'].toString()) ?? DateTime.now();
    } else {
      parsedCreatedAt = DateTime.now();
    }

    DateTime? parsedUpdatedAt;
    if (json['updated_at'] != null) {
      parsedUpdatedAt = DateTime.tryParse(json['updated_at'].toString());
    }

    return AppNotification(
      id: json['id'] as int? ?? 0,
      title: json['title'] as String? ?? 'Notification',
      body: (json['body'] ?? json['message'] ?? '') as String,
      type: (json['type'] ?? json['severity'] ?? 'info') as String,
      isRead: json['is_read'] as bool? ?? false,
      createdAt: parsedCreatedAt,
      userId: json['user_id'] as int?,
      entityType: json['entity_type'] as String?,
      entityId: json['entity_id'] as int?,
      updatedAt: parsedUpdatedAt,
    );
  }

  /// Serializes instance to a JSON map.
  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'title': title,
      'body': body,
      'message': body,
      'type': type,
      'severity': type,
      'is_read': isRead,
      'created_at': createdAt.toIso8601String(),
      if (userId != null) 'user_id': userId,
      if (entityType != null) 'entity_type': entityType,
      if (entityId != null) 'entity_id': entityId,
      if (updatedAt != null) 'updated_at': updatedAt!.toIso8601String(),
    };
  }

  AppNotification copyWith({
    int? id,
    String? title,
    String? body,
    String? type,
    bool? isRead,
    DateTime? createdAt,
    int? userId,
    String? entityType,
    int? entityId,
    DateTime? updatedAt,
  }) {
    return AppNotification(
      id: id ?? this.id,
      title: title ?? this.title,
      body: body ?? this.body,
      type: type ?? this.type,
      isRead: isRead ?? this.isRead,
      createdAt: createdAt ?? this.createdAt,
      userId: userId ?? this.userId,
      entityType: entityType ?? this.entityType,
      entityId: entityId ?? this.entityId,
      updatedAt: updatedAt ?? this.updatedAt,
    );
  }
}

/// Paginated collection of notifications returned by `/notifications/me`.
class PaginatedNotifications {
  const PaginatedNotifications({
    required this.items,
    required this.total,
    required this.page,
    required this.perPage,
    required this.pages,
  });

  final List<AppNotification> items;
  final int total;
  final int page;
  final int perPage;
  final int pages;

  bool get hasNextPage => page < pages;

  factory PaginatedNotifications.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'];
    final items = <AppNotification>[];
    if (rawItems is List) {
      for (final item in rawItems) {
        if (item is Map<String, dynamic>) {
          items.add(AppNotification.fromJson(item));
        }
      }
    }

    return PaginatedNotifications(
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
