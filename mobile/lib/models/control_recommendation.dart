import 'package:flutter/material.dart';

import '../theme/app_tokens.dart';

/// Observed physical traffic conditions snapshot at an intersection.
class TrafficStateSnapshot {
  const TrafficStateSnapshot({
    required this.intersectionId,
    required this.vehicleCount,
    required this.density,
    required this.queueLength,
    required this.occupancy,
    this.avgSpeedKmh,
    this.incidentCount = 0,
    this.activeEmergency = false,
    this.observedSignalState,
    this.currentPhaseName,
    this.currentGreenElapsedS,
    this.telemetryAgeS = 0.0,
    this.source = 'sensor',
  });

  final int intersectionId;
  final int vehicleCount;
  final double density;
  final double queueLength;
  final double occupancy;
  final double? avgSpeedKmh;
  final int incidentCount;
  final bool activeEmergency;
  final String? observedSignalState;
  final String? currentPhaseName;
  final double? currentGreenElapsedS;
  final double telemetryAgeS;
  final String source;

  factory TrafficStateSnapshot.fromJson(Map<String, dynamic> json) {
    return TrafficStateSnapshot(
      intersectionId: (json['intersection_id'] as num?)?.toInt() ?? 0,
      vehicleCount: (json['vehicle_count'] as num?)?.toInt() ?? 0,
      density: (json['density'] as num?)?.toDouble() ?? 0.0,
      queueLength: (json['queue_length'] as num?)?.toDouble() ?? 0.0,
      occupancy: (json['occupancy'] as num?)?.toDouble() ?? 0.0,
      avgSpeedKmh: (json['avg_speed_kmh'] as num?)?.toDouble(),
      incidentCount: (json['incident_count'] as num?)?.toInt() ?? 0,
      activeEmergency: (json['active_emergency'] as bool?) ?? false,
      observedSignalState: json['observed_signal_state'] as String?,
      currentPhaseName: json['current_phase_name'] as String?,
      currentGreenElapsedS:
          (json['current_green_elapsed_s'] as num?)?.toDouble(),
      telemetryAgeS: (json['telemetry_age_s'] as num?)?.toDouble() ?? 0.0,
      source: (json['source'] as String?) ?? 'sensor',
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'intersection_id': intersectionId,
      'vehicle_count': vehicleCount,
      'density': density,
      'queue_length': queueLength,
      'occupancy': occupancy,
      'avg_speed_kmh': avgSpeedKmh,
      'incident_count': incidentCount,
      'active_emergency': activeEmergency,
      'observed_signal_state': observedSignalState,
      'current_phase_name': currentPhaseName,
      'current_green_elapsed_s': currentGreenElapsedS,
      'telemetry_age_s': telemetryAgeS,
      'source': source,
    };
  }
}

/// Predictive forecast context produced by ML pipeline for control decisions.
class PredictedStateSnapshot {
  const PredictedStateSnapshot({
    required this.congestion,
    required this.volume,
    required this.queueGrowth,
    this.horizonMinutes = 30,
    this.modelVersion,
    this.confidence,
  });

  final double congestion;
  final double volume;
  final double queueGrowth;
  final int horizonMinutes;
  final String? modelVersion;
  final double? confidence;

  factory PredictedStateSnapshot.fromJson(Map<String, dynamic> json) {
    return PredictedStateSnapshot(
      congestion: (json['congestion'] as num?)?.toDouble() ?? 0.0,
      volume: (json['volume'] as num?)?.toDouble() ?? 0.0,
      queueGrowth: (json['queue_growth'] as num?)?.toDouble() ?? 0.0,
      horizonMinutes: (json['horizon_minutes'] as num?)?.toInt() ?? 30,
      modelVersion: json['model_version'] as String?,
      confidence: (json['confidence'] as num?)?.toDouble(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'congestion': congestion,
      'volume': volume,
      'queue_growth': queueGrowth,
      'horizon_minutes': horizonMinutes,
      'model_version': modelVersion,
      'confidence': confidence,
    };
  }
}

/// Structured advisory control recommendation matching GET `/control/recommendations`.
class ControlRecommendation {
  const ControlRecommendation({
    this.id,
    required this.intersectionId,
    required this.action,
    this.current,
    this.predicted,
    required this.reason,
    required this.expectedImpact,
    this.confidence,
    this.affectedSignalIds = const [],
    this.affectedRoute,
    this.modelVersion,
    required this.createdAt,
    this.isRecommendation = true,
  });

  final int? id;
  final int intersectionId;
  final String action;
  final TrafficStateSnapshot? current;
  final PredictedStateSnapshot? predicted;
  final String reason;
  final String expectedImpact;
  final double? confidence;
  final List<int> affectedSignalIds;
  final Map<String, dynamic>? affectedRoute;
  final String? modelVersion;
  final DateTime createdAt;
  final bool isRecommendation;

  /// Returns UI styling color based on action type.
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

  factory ControlRecommendation.fromJson(Map<String, dynamic> json) {
    DateTime parseDate(dynamic v) {
      if (v == null) return DateTime.now();
      return DateTime.tryParse(v.toString()) ?? DateTime.now();
    }

    TrafficStateSnapshot? currentSnapshot;
    if (json['current'] is Map<String, dynamic>) {
      currentSnapshot =
          TrafficStateSnapshot.fromJson(json['current'] as Map<String, dynamic>);
    }

    PredictedStateSnapshot? predSnapshot;
    if (json['predicted'] is Map<String, dynamic>) {
      predSnapshot = PredictedStateSnapshot.fromJson(
          json['predicted'] as Map<String, dynamic>);
    }

    List<int> affectedSignals = [];
    if (json['affected_signal_ids'] is List) {
      affectedSignals = (json['affected_signal_ids'] as List)
          .whereType<num>()
          .map((n) => n.toInt())
          .toList();
    }

    return ControlRecommendation(
      id: (json['id'] as num?)?.toInt(),
      intersectionId: (json['intersection_id'] as num?)?.toInt() ?? 0,
      action: (json['action'] as String?) ?? 'NO_ACTION',
      current: currentSnapshot,
      predicted: predSnapshot,
      reason: (json['reason'] as String?) ?? 'Advisory operational assessment',
      expectedImpact:
          (json['expected_impact'] as String?) ?? 'Maintains current flow',
      confidence: (json['confidence'] as num?)?.toDouble(),
      affectedSignalIds: affectedSignals,
      affectedRoute: json['affected_route'] as Map<String, dynamic>?,
      modelVersion: json['model_version'] as String?,
      createdAt: parseDate(json['created_at']),
      isRecommendation: (json['is_recommendation'] as bool?) ?? true,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'intersection_id': intersectionId,
      'action': action,
      'current': current?.toJson(),
      'predicted': predicted?.toJson(),
      'reason': reason,
      'expected_impact': expectedImpact,
      'confidence': confidence,
      'affected_signal_ids': affectedSignalIds,
      'affected_route': affectedRoute,
      'model_version': modelVersion,
      'created_at': createdAt.toIso8601String(),
      'is_recommendation': isRecommendation,
    };
  }
}

/// Optimized signal timing plan proposal matching POST `/control/optimize-signals`.
class OptimizationResult {
  const OptimizationResult({
    required this.intersectionId,
    required this.recommendedGreenS,
    required this.totalCycleS,
    required this.method,
    this.inputsEcho = const {},
    required this.computedAt,
    this.note,
    this.validated = true,
  });

  final int intersectionId;
  final Map<String, double> recommendedGreenS;
  final double totalCycleS;
  final String method;
  final Map<String, dynamic> inputsEcho;
  final DateTime computedAt;
  final String? note;
  final bool validated;

  factory OptimizationResult.fromJson(Map<String, dynamic> json) {
    final rawGreens = json['recommended_green_s'];
    Map<String, double> greens = {};
    if (rawGreens is Map) {
      rawGreens.forEach((k, v) {
        greens[k.toString()] = (v as num?)?.toDouble() ?? 0.0;
      });
    }

    DateTime computed = DateTime.now();
    if (json['computed_at'] != null) {
      computed = DateTime.tryParse(json['computed_at'].toString()) ?? DateTime.now();
    }

    return OptimizationResult(
      intersectionId: (json['intersection_id'] as num?)?.toInt() ?? 0,
      recommendedGreenS: greens,
      totalCycleS: (json['total_cycle_s'] as num?)?.toDouble() ?? 0.0,
      method: (json['method'] as String?) ?? 'Webster proportional',
      inputsEcho: json['inputs_echo'] is Map
          ? Map<String, dynamic>.from(json['inputs_echo'] as Map)
          : {},
      computedAt: computed,
      note: json['note'] as String?,
      validated: (json['validated'] as bool?) ?? true,
    );
  }
}

/// Simulation metrics for macroscopic point-queue traffic flow comparison.
class SimulationMetrics {
  const SimulationMetrics({
    required this.totalWaitVehMin,
    required this.avgQueueVeh,
    required this.maxQueueVeh,
    required this.throughputVeh,
    required this.residualQueueVeh,
  });

  final double totalWaitVehMin;
  final double avgQueueVeh;
  final double maxQueueVeh;
  final double throughputVeh;
  final double residualQueueVeh;

  factory SimulationMetrics.fromJson(Map<String, dynamic> json) {
    return SimulationMetrics(
      totalWaitVehMin: (json['total_wait_veh_min'] as num?)?.toDouble() ?? 0.0,
      avgQueueVeh: (json['avg_queue_veh'] as num?)?.toDouble() ?? 0.0,
      maxQueueVeh: (json['max_queue_veh'] as num?)?.toDouble() ?? 0.0,
      throughputVeh: (json['throughput_veh'] as num?)?.toDouble() ?? 0.0,
      residualQueueVeh:
          (json['residual_queue_veh'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

/// Plan comparison output matching POST `/control/simulate`.
class SimulationComparison {
  const SimulationComparison({
    required this.currentResult,
    required this.proposedResult,
    required this.deltaWait,
    required this.deltaAvgQueue,
    required this.deltaThroughput,
    required this.verdict,
  });

  final SimulationMetrics currentResult;
  final SimulationMetrics proposedResult;
  final double deltaWait;
  final double deltaAvgQueue;
  final double deltaThroughput;
  final String verdict;

  bool get isProposedBetter =>
      verdict.toLowerCase().contains('proposed') || deltaWait < 0;

  factory SimulationComparison.fromJson(Map<String, dynamic> json) {
    return SimulationComparison(
      currentResult: SimulationMetrics.fromJson(
        (json['current_result'] as Map<String, dynamic>?) ?? {},
      ),
      proposedResult: SimulationMetrics.fromJson(
        (json['proposed_result'] as Map<String, dynamic>?) ?? {},
      ),
      deltaWait: (json['delta_wait'] as num?)?.toDouble() ?? 0.0,
      deltaAvgQueue: (json['delta_avg_queue'] as num?)?.toDouble() ?? 0.0,
      deltaThroughput: (json['delta_throughput'] as num?)?.toDouble() ?? 0.0,
      verdict: (json['verdict'] as String?) ?? 'equivalent',
    );
  }
}

/// Paginated control decisions matching GET `/control/decisions`.
class ControlDecisionRecord {
  const ControlDecisionRecord({
    required this.id,
    this.intersectionId,
    required this.decisionType,
    required this.payload,
    required this.status,
    this.appliedBy,
    this.appliedAt,
    this.rationale,
    required this.createdAt,
    required this.updatedAt,
  });

  final int id;
  final int? intersectionId;
  final String decisionType;
  final Map<String, dynamic> payload;
  final String status;
  final int? appliedBy;
  final DateTime? appliedAt;
  final String? rationale;
  final DateTime createdAt;
  final DateTime updatedAt;

  factory ControlDecisionRecord.fromJson(Map<String, dynamic> json) {
    DateTime parseDate(dynamic v) {
      if (v == null) return DateTime.now();
      return DateTime.tryParse(v.toString()) ?? DateTime.now();
    }

    return ControlDecisionRecord(
      id: (json['id'] as num?)?.toInt() ?? 0,
      intersectionId: (json['intersection_id'] as num?)?.toInt(),
      decisionType: (json['decision_type'] as String?) ?? '',
      payload: (json['payload'] as Map<String, dynamic>?) ?? {},
      status: (json['status'] as String?) ?? 'proposed',
      appliedBy: (json['applied_by'] as num?)?.toInt(),
      appliedAt: json['applied_at'] != null
          ? DateTime.tryParse(json['applied_at'].toString())
          : null,
      rationale: json['rationale'] as String?,
      createdAt: parseDate(json['created_at']),
      updatedAt: parseDate(json['updated_at']),
    );
  }
}

/// Paginated control decision listing response.
class PaginatedControlDecisions {
  const PaginatedControlDecisions({
    required this.items,
    required this.total,
    required this.page,
    required this.perPage,
    required this.pages,
  });

  final List<ControlDecisionRecord> items;
  final int total;
  final int page;
  final int perPage;
  final int pages;

  factory PaginatedControlDecisions.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'];
    List<ControlDecisionRecord> itemList = [];
    if (rawItems is List) {
      itemList = rawItems
          .whereType<Map<String, dynamic>>()
          .map(ControlDecisionRecord.fromJson)
          .toList();
    }

    return PaginatedControlDecisions(
      items: itemList,
      total: (json['total'] as num?)?.toInt() ?? itemList.length,
      page: (json['page'] as num?)?.toInt() ?? 1,
      perPage: (json['per_page'] as num?)?.toInt() ?? 20,
      pages: (json['pages'] as num?)?.toInt() ?? 1,
    );
  }
}
