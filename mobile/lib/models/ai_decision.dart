import 'package:flutter/material.dart';

import '../theme/app_tokens.dart';

/// Single AI Decision entity matching GET `/ai-decisions`.
class AIDecisionItem {
  const AIDecisionItem({
    required this.id,
    required this.action,
    required this.reason,
    this.junction,
    this.intersectionId,
    this.confidence,
    this.expectedImpact,
    this.modelVersion,
    this.status = 'proposed',
    this.appliedBy,
    this.appliedAt,
    required this.createdAt,
    this.updatedAt,
    this.payload = const {},
  });

  final int id;
  final String action;
  final String reason;
  final String? junction;
  final int? intersectionId;
  final double? confidence;
  final String? expectedImpact;
  final String? modelVersion;
  final String status;
  final int? appliedBy;
  final DateTime? appliedAt;
  final DateTime createdAt;
  final DateTime? updatedAt;
  final Map<String, dynamic> payload;

  Color get actionColor {
    switch (action.toUpperCase()) {
      case 'EXTEND_GREEN':
        return AppTokens.teal;
      case 'SHORTEN_CYCLE':
      case 'REDUCE_GREEN':
        return AppTokens.amber;
      case 'ALL_RED_HOLD':
      case 'EMERGENCY_HOLD':
      case 'EMERGENCY_PREEMPT':
        return AppTokens.danger;
      case 'NO_ACTION':
      default:
        return AppTokens.muted;
    }
  }

  Color get statusColor {
    switch (status.toLowerCase()) {
      case 'applied':
        return AppTokens.success;
      case 'reverted':
        return AppTokens.danger;
      case 'proposed':
      default:
        return AppTokens.amber;
    }
  }

  factory AIDecisionItem.fromJson(Map<String, dynamic> json) {
    DateTime parseDate(dynamic v) {
      if (v == null) return DateTime.now();
      return DateTime.tryParse(v.toString()) ?? DateTime.now();
    }

    final payloadMap = (json['payload'] as Map<String, dynamic>?) ?? {};

    // Action resolution
    final action = (json['action'] ??
            json['decision_type'] ??
            payloadMap['action'] ??
            'ADVISORY')
        .toString();

    // Reason resolution
    final reason = (json['reason'] ??
            json['rationale'] ??
            payloadMap['reason'] ??
            payloadMap['rationale'] ??
            'Operational control optimization')
        .toString();

    // Junction name resolution
    String? junctionName = json['junction'] as String?;
    final interId = (json['intersection_id'] as num?)?.toInt() ??
        (payloadMap['intersection_id'] as num?)?.toInt();
    if (junctionName == null && interId != null) {
      junctionName = 'Junction #$interId';
    }

    // Confidence resolution
    final conf = (json['confidence'] ?? payloadMap['confidence']) as num?;

    // Expected impact resolution
    final expImpact = (json['expected_impact'] ??
        payloadMap['expected_impact'] ??
        payloadMap['impact']) as String?;

    // Model version resolution
    final modVer = (json['model_version'] ??
        payloadMap['model_version'] ??
        json['modelVersion']) as String?;

    return AIDecisionItem(
      id: (json['id'] as num?)?.toInt() ?? 0,
      action: action,
      reason: reason,
      junction: junctionName,
      intersectionId: interId,
      confidence: conf?.toDouble(),
      expectedImpact: expImpact,
      modelVersion: modVer,
      status: (json['status'] as String?) ?? 'proposed',
      appliedBy: (json['applied_by'] as num?)?.toInt(),
      appliedAt: json['applied_at'] != null
          ? DateTime.tryParse(json['applied_at'].toString())
          : null,
      createdAt: parseDate(json['created_at']),
      updatedAt: json['updated_at'] != null
          ? DateTime.tryParse(json['updated_at'].toString())
          : null,
      payload: payloadMap,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'action': action,
      'decision_type': action,
      'reason': reason,
      'rationale': reason,
      'junction': junction,
      'intersection_id': intersectionId,
      'confidence': confidence,
      'expected_impact': expectedImpact,
      'model_version': modelVersion,
      'status': status,
      'applied_by': appliedBy,
      'applied_at': appliedAt?.toIso8601String(),
      'created_at': createdAt.toIso8601String(),
      'updated_at': updatedAt?.toIso8601String(),
      'payload': payload,
    };
  }
}

/// Paginated AI decisions response matching GET `/ai-decisions`.
class PaginatedAIDecisions {
  const PaginatedAIDecisions({
    required this.items,
    required this.total,
    required this.page,
    required this.perPage,
    required this.pages,
  });

  final List<AIDecisionItem> items;
  final int total;
  final int page;
  final int perPage;
  final int pages;

  factory PaginatedAIDecisions.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'];
    List<AIDecisionItem> itemList = [];
    if (rawItems is List) {
      itemList = rawItems
          .whereType<Map<String, dynamic>>()
          .map(AIDecisionItem.fromJson)
          .toList();
    }

    return PaginatedAIDecisions(
      items: itemList,
      total: (json['total'] as num?)?.toInt() ?? itemList.length,
      page: (json['page'] as num?)?.toInt() ?? 1,
      perPage: (json['per_page'] as num?)?.toInt() ?? 20,
      pages: (json['pages'] as num?)?.toInt() ?? 1,
    );
  }
}
