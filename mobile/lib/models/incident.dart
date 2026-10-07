import 'package:flutter/material.dart';
import '../theme/app_tokens.dart';

/// Supported lifecycle statuses for traffic incidents.
enum IncidentStatus {
  reported,
  acknowledged,
  resolved;

  String get value => name;

  String get label {
    switch (this) {
      case IncidentStatus.reported:
        return 'Reported';
      case IncidentStatus.acknowledged:
        return 'Acknowledged';
      case IncidentStatus.resolved:
        return 'Resolved';
    }
  }

  static IncidentStatus fromString(String? val) {
    switch (val?.toLowerCase().trim()) {
      case 'acknowledged':
        return IncidentStatus.acknowledged;
      case 'resolved':
        return IncidentStatus.resolved;
      case 'reported':
      default:
        return IncidentStatus.reported;
    }
  }

  /// Determines whether transitioning from this status to [next] is permissible.
  /// Backend rule: Cannot transition from resolved to reported.
  bool canTransitionTo(IncidentStatus next) {
    if (this == IncidentStatus.resolved && next == IncidentStatus.reported) {
      return false;
    }
    if (this == IncidentStatus.resolved && next == IncidentStatus.acknowledged) {
      return false;
    }
    if (this == next) {
      return true;
    }
    if (this == IncidentStatus.reported) {
      return next == IncidentStatus.acknowledged || next == IncidentStatus.resolved;
    }
    if (this == IncidentStatus.acknowledged) {
      return next == IncidentStatus.resolved;
    }
    return false;
  }

  /// List of permissible subsequent statuses.
  List<IncidentStatus> get validNextStatuses {
    switch (this) {
      case IncidentStatus.reported:
        return const [IncidentStatus.acknowledged, IncidentStatus.resolved];
      case IncidentStatus.acknowledged:
        return const [IncidentStatus.resolved];
      case IncidentStatus.resolved:
        return const [];
    }
  }
}

/// Traffic incident observation and lifecycle status model.
class Incident {
  const Incident({
    required this.id,
    this.intersectionId,
    required this.severity,
    required this.status,
    this.title,
    this.description,
    this.reportedBy,
    this.resolvedAt,
    this.latitude,
    this.longitude,
    required this.createdAt,
    required this.updatedAt,
  });

  final int id;
  final int? intersectionId;
  final String severity;
  final String status;
  final String? title;
  final String? description;
  final int? reportedBy;
  final DateTime? resolvedAt;
  final double? latitude;
  final double? longitude;
  final DateTime createdAt;
  final DateTime updatedAt;

  IncidentStatus get incidentStatus => IncidentStatus.fromString(status);

  bool get isResolved => status.toLowerCase() == 'resolved';
  bool get isActive => !isResolved;

  /// Human-readable title for presentation.
  String get displayTitle {
    if (title != null && title!.trim().isNotEmpty) {
      return title!.trim();
    }
    if (description != null && description!.trim().isNotEmpty) {
      final desc = description!.trim();
      final colonIdx = desc.indexOf(':');
      if (colonIdx > 0 && colonIdx < 40) {
        return desc.substring(0, colonIdx).trim();
      }
      if (desc.length > 50) {
        return '${desc.substring(0, 47)}...';
      }
      return desc;
    }
    return 'Incident #$id';
  }

  /// Check whether moving to [nextStatus] is allowed.
  bool canTransitionTo(String nextStatus) {
    return isValidTransition(status, nextStatus);
  }

  /// Static validator for incident status progression.
  /// Enforces: cannot transition from resolved to reported.
  static bool isValidTransition(String currentStatus, String targetStatus) {
    final cur = IncidentStatus.fromString(currentStatus);
    final tar = IncidentStatus.fromString(targetStatus);
    return cur.canTransitionTo(tar);
  }

  Color get severityColor {
    switch (severity.toLowerCase()) {
      case 'critical':
        return AppTokens.danger;
      case 'high':
        return const Color(0xFFFF7A00);
      case 'medium':
        return AppTokens.amber;
      case 'low':
        return AppTokens.teal;
      default:
        return AppTokens.muted;
    }
  }

  Color get statusColor {
    switch (status.toLowerCase()) {
      case 'resolved':
        return AppTokens.success;
      case 'acknowledged':
        return AppTokens.amber;
      case 'reported':
      default:
        return AppTokens.danger;
    }
  }

  factory Incident.fromJson(Map<String, dynamic> json) {
    DateTime parseDate(dynamic v) {
      if (v == null) return DateTime.now();
      return DateTime.tryParse(v.toString()) ?? DateTime.now();
    }

    final lat = (json['lat'] as num?)?.toDouble() ??
        (json['latitude'] as num?)?.toDouble();
    final lon = (json['lon'] as num?)?.toDouble() ??
        (json['longitude'] as num?)?.toDouble();

    return Incident(
      id: (json['id'] as num?)?.toInt() ?? 0,
      intersectionId: (json['intersection_id'] as num?)?.toInt(),
      severity: (json['severity'] as String?) ?? 'unknown',
      status: (json['status'] as String?) ?? 'reported',
      title: json['title'] as String?,
      description: json['description'] as String?,
      reportedBy: (json['reported_by'] as num?)?.toInt(),
      resolvedAt: json['resolved_at'] != null
          ? DateTime.tryParse(json['resolved_at'].toString())
          : null,
      latitude: lat,
      longitude: lon,
      createdAt: parseDate(json['created_at']),
      updatedAt: parseDate(json['updated_at']),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'intersection_id': intersectionId,
      'severity': severity,
      'status': status,
      if (title != null) 'title': title,
      'description': description,
      'reported_by': reportedBy,
      'resolved_at': resolvedAt?.toIso8601String(),
      'lat': latitude,
      'lon': longitude,
      'created_at': createdAt.toIso8601String(),
      'updated_at': updatedAt.toIso8601String(),
    };
  }
}

/// Incident aggregation statistics matching GET `/analytics/incidents-summary`.
class IncidentsSummary {
  const IncidentsSummary({
    required this.total,
    required this.bySeverity,
    required this.byStatus,
  });

  final int total;
  final Map<String, int> bySeverity;
  final Map<String, int> byStatus;

  int get activeCount {
    final reported = byStatus['reported'] ?? 0;
    final ack = byStatus['acknowledged'] ?? 0;
    return reported + ack;
  }

  factory IncidentsSummary.fromJson(Map<String, dynamic> json) {
    Map<String, int> parseCounts(dynamic raw) {
      if (raw is Map) {
        return raw.map((k, v) => MapEntry(k.toString(), (v as num?)?.toInt() ?? 0));
      }
      return {};
    }

    return IncidentsSummary(
      total: (json['total'] as num?)?.toInt() ?? 0,
      bySeverity: parseCounts(json['by_severity']),
      byStatus: parseCounts(json['by_status']),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'total': total,
      'by_severity': bySeverity,
      'by_status': byStatus,
    };
  }
}

/// Paginated incidents listing response schema.
class PaginatedIncidents {
  const PaginatedIncidents({
    required this.items,
    required this.total,
    required this.page,
    required this.perPage,
    required this.pages,
  });

  final List<Incident> items;
  final int total;
  final int page;
  final int perPage;
  final int pages;

  factory PaginatedIncidents.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'];
    List<Incident> itemList = [];
    if (rawItems is List) {
      itemList = rawItems
          .whereType<Map<String, dynamic>>()
          .map(Incident.fromJson)
          .toList();
    }

    return PaginatedIncidents(
      items: itemList,
      total: (json['total'] as num?)?.toInt() ?? itemList.length,
      page: (json['page'] as num?)?.toInt() ?? 1,
      perPage: (json['per_page'] as num?)?.toInt() ?? 20,
      pages: (json['pages'] as num?)?.toInt() ?? 1,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'items': items.map((i) => i.toJson()).toList(),
      'total': total,
      'page': page,
      'per_page': perPage,
      'pages': pages,
    };
  }
}
