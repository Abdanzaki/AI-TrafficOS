import 'package:flutter/material.dart';
import '../theme/app_tokens.dart';

/// Emergency vehicle detection, transit, and priority preemption lifecycle model.
class EmergencyEvent {
  const EmergencyEvent({
    required this.id,
    this.incidentId,
    this.intersectionId,
    required this.vehicleType,
    required this.priority,
    required this.status,
    required this.detectedAt,
    this.clearedAt,
    required this.createdAt,
    required this.updatedAt,
  });

  final int id;
  final int? incidentId;
  final int? intersectionId;
  final String vehicleType;
  final int priority;
  final String status;
  final DateTime detectedAt;
  final DateTime? clearedAt;
  final DateTime createdAt;
  final DateTime updatedAt;

  bool get isResolved => status.toLowerCase() == 'resolved';
  bool get isActive => !isResolved;

  String get vehicleTypeDisplay {
    final lower = vehicleType.toLowerCase().replaceAll('_', ' ');
    if (lower.isEmpty) return 'Emergency Vehicle';
    return lower[0].toUpperCase() + lower.substring(1);
  }

  IconData get vehicleIcon {
    final v = vehicleType.toLowerCase();
    if (v.contains('fire')) {
      return Icons.local_fire_department_rounded;
    }
    if (v.contains('police')) {
      return Icons.local_police_rounded;
    }
    if (v.contains('ambulance') || v.contains('medic')) {
      return Icons.medical_services_rounded;
    }
    return Icons.emergency_rounded;
  }

  Color get priorityColor {
    switch (priority) {
      case 1:
        return AppTokens.danger;
      case 2:
        return const Color(0xFFFF7A00);
      case 3:
        return AppTokens.amber;
      case 4:
        return AppTokens.teal;
      default:
        return AppTokens.muted;
    }
  }

  String get priorityLabel {
    switch (priority) {
      case 1:
        return 'P1 - Critical';
      case 2:
        return 'P2 - High';
      case 3:
        return 'P3 - Medium';
      case 4:
        return 'P4 - Low';
      default:
        return 'P$priority - Standard';
    }
  }

  Color get statusColor {
    switch (status.toLowerCase()) {
      case 'active':
        return AppTokens.danger;
      case 'dispatched':
        return AppTokens.amber;
      case 'on_scene':
        return AppTokens.teal;
      case 'resolved':
        return AppTokens.success;
      default:
        return AppTokens.muted;
    }
  }

  factory EmergencyEvent.fromJson(Map<String, dynamic> json) {
    DateTime parseDate(dynamic v) {
      if (v == null) return DateTime.now();
      return DateTime.tryParse(v.toString()) ?? DateTime.now();
    }

    return EmergencyEvent(
      id: (json['id'] as num?)?.toInt() ?? 0,
      incidentId: (json['incident_id'] as num?)?.toInt(),
      intersectionId: (json['intersection_id'] as num?)?.toInt(),
      vehicleType: (json['vehicle_type'] as String?) ?? 'emergency_vehicle',
      priority: (json['priority'] as num?)?.toInt() ?? 1,
      status: (json['status'] as String?) ?? 'active',
      detectedAt: parseDate(json['detected_at']),
      clearedAt: json['cleared_at'] != null
          ? DateTime.tryParse(json['cleared_at'].toString())
          : null,
      createdAt: parseDate(json['created_at']),
      updatedAt: parseDate(json['updated_at']),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'incident_id': incidentId,
      'intersection_id': intersectionId,
      'vehicle_type': vehicleType,
      'priority': priority,
      'status': status,
      'detected_at': detectedAt.toIso8601String(),
      'cleared_at': clearedAt?.toIso8601String(),
      'created_at': createdAt.toIso8601String(),
      'updated_at': updatedAt.toIso8601String(),
    };
  }
}

/// Paginated emergency events listing response schema.
class PaginatedEmergencyEvents {
  const PaginatedEmergencyEvents({
    required this.items,
    required this.total,
    required this.page,
    required this.perPage,
    required this.pages,
  });

  final List<EmergencyEvent> items;
  final int total;
  final int page;
  final int perPage;
  final int pages;

  factory PaginatedEmergencyEvents.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'];
    List<EmergencyEvent> itemList = [];
    if (rawItems is List) {
      itemList = rawItems
          .whereType<Map<String, dynamic>>()
          .map(EmergencyEvent.fromJson)
          .toList();
    }

    return PaginatedEmergencyEvents(
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

/// Preemption or extension directive for a signal controller along the green corridor.
class CorridorSignalAction {
  const CorridorSignalAction({
    required this.intersectionId,
    this.signalId,
    required this.action,
    required this.durationSeconds,
    required this.reason,
  });

  final int intersectionId;
  final int? signalId;
  final String action;
  final double durationSeconds;
  final String reason;

  factory CorridorSignalAction.fromJson(Map<String, dynamic> json) {
    return CorridorSignalAction(
      intersectionId: (json['intersection_id'] as num?)?.toInt() ?? 0,
      signalId: (json['signal_id'] as num?)?.toInt(),
      action: (json['action'] as String?) ?? 'monitor',
      durationSeconds: (json['duration_seconds'] as num?)?.toDouble() ?? 0.0,
      reason: (json['reason'] as String?) ?? '',
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'intersection_id': intersectionId,
      'signal_id': signalId,
      'action': action,
      'duration_seconds': durationSeconds,
      'reason': reason,
    };
  }
}

/// Coordinated green wave emergency preemption corridor route and signal timing.
class CorridorPlan {
  const CorridorPlan({
    required this.corridorId,
    required this.path,
    required this.signalActions,
    required this.estimatedMinutes,
    required this.fromIntersectionId,
    required this.toIntersectionId,
  });

  final String corridorId;
  final List<int> path;
  final List<CorridorSignalAction> signalActions;
  final double estimatedMinutes;
  final int fromIntersectionId;
  final int toIntersectionId;

  factory CorridorPlan.fromJson(Map<String, dynamic> json) {
    List<int> parsePath(dynamic raw) {
      if (raw is List) {
        return raw.map((e) => (e as num).toInt()).toList();
      }
      return [];
    }

    List<CorridorSignalAction> parseActions(dynamic raw) {
      if (raw is List) {
        return raw
            .whereType<Map<String, dynamic>>()
            .map(CorridorSignalAction.fromJson)
            .toList();
      }
      return [];
    }

    return CorridorPlan(
      corridorId: (json['corridor_id'] as String?) ?? '',
      path: parsePath(json['path']),
      signalActions: parseActions(json['signal_actions']),
      estimatedMinutes: (json['estimated_minutes'] as num?)?.toDouble() ?? 0.0,
      fromIntersectionId: (json['from_intersection_id'] as num?)?.toInt() ?? 0,
      toIntersectionId: (json['to_intersection_id'] as num?)?.toInt() ?? 0,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'corridor_id': corridorId,
      'path': path,
      'signal_actions': signalActions.map((a) => a.toJson()).toList(),
      'estimated_minutes': estimatedMinutes,
      'from_intersection_id': fromIntersectionId,
      'to_intersection_id': toIntersectionId,
    };
  }
}

/// Response payload from POST `/control/emergency/prioritize`.
class EmergencyPrioritizeResult {
  const EmergencyPrioritizeResult({
    required this.decisionId,
    required this.corridorPlan,
    required this.affectedIntersectionIds,
    this.isRecommendation = true,
  });

  final int decisionId;
  final CorridorPlan corridorPlan;
  final List<int> affectedIntersectionIds;
  final bool isRecommendation;

  factory EmergencyPrioritizeResult.fromJson(Map<String, dynamic> json) {
    List<int> parseAffected(dynamic raw) {
      if (raw is List) {
        return raw.map((e) => (e as num).toInt()).toList();
      }
      return [];
    }

    final planRaw = json['corridor_plan'] as Map<String, dynamic>? ?? {};

    return EmergencyPrioritizeResult(
      decisionId: (json['decision_id'] as num?)?.toInt() ?? 0,
      corridorPlan: CorridorPlan.fromJson(planRaw),
      affectedIntersectionIds: parseAffected(json['affected_intersection_ids']),
      isRecommendation: (json['is_recommendation'] as bool?) ?? true,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'decision_id': decisionId,
      'corridor_plan': corridorPlan.toJson(),
      'affected_intersection_ids': affectedIntersectionIds,
      'is_recommendation': isRecommendation,
    };
  }
}

/// Response payload from POST `/control/emergency/restore`.
class EmergencyRestoreResult {
  const EmergencyRestoreResult({
    required this.decisionId,
    required this.emergencyEventId,
    required this.action,
    required this.reason,
    required this.affectedSignalIds,
    this.isRecommendation = true,
  });

  final int decisionId;
  final int emergencyEventId;
  final String action;
  final String reason;
  final List<int> affectedSignalIds;
  final bool isRecommendation;

  factory EmergencyRestoreResult.fromJson(Map<String, dynamic> json) {
    List<int> parseSignals(dynamic raw) {
      if (raw is List) {
        return raw.map((e) => (e as num).toInt()).toList();
      }
      return [];
    }

    return EmergencyRestoreResult(
      decisionId: (json['decision_id'] as num?)?.toInt() ?? 0,
      emergencyEventId: (json['emergency_event_id'] as num?)?.toInt() ?? 0,
      action: (json['action'] as String?) ?? 'NO_ACTION',
      reason: (json['reason'] as String?) ?? '',
      affectedSignalIds: parseSignals(json['affected_signal_ids']),
      isRecommendation: (json['is_recommendation'] as bool?) ?? true,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'decision_id': decisionId,
      'emergency_event_id': emergencyEventId,
      'action': action,
      'reason': reason,
      'affected_signal_ids': affectedSignalIds,
      'is_recommendation': isRecommendation,
    };
  }
}

/// Response payload from POST `/control/green-corridor/recommend`.
class GreenCorridorRecommendResult {
  const GreenCorridorRecommendResult({
    required this.corridorPlan,
    this.isRecommendation = true,
    this.note = '',
  });

  final CorridorPlan corridorPlan;
  final bool isRecommendation;
  final String note;

  factory GreenCorridorRecommendResult.fromJson(Map<String, dynamic> json) {
    final planRaw = json['corridor_plan'] as Map<String, dynamic>? ?? {};

    return GreenCorridorRecommendResult(
      corridorPlan: CorridorPlan.fromJson(planRaw),
      isRecommendation: (json['is_recommendation'] as bool?) ?? true,
      note: (json['note'] as String?) ??
          'Advisory recommendation only; no database changes or signal actuations executed.',
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'corridor_plan': corridorPlan.toJson(),
      'is_recommendation': isRecommendation,
      'note': note,
    };
  }
}
