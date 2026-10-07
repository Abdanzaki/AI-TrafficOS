import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/control_recommendation.dart';
import '../models/prediction.dart';
import 'api_client.dart';
import 'auth_service.dart';

/// Helper to map 422 unprocessable entity responses into typed [InsufficientDataException].
void _checkAndMapInsufficientData(ApiException e, [int? intersectionId]) {
  if (e.statusCode == 422) {
    dynamic payload = e.details;
    if (payload is Map && payload['detail'] is Map) {
      payload = payload['detail'];
    }

    String finalMessage = e.message;
    final msg = e.message.toLowerCase();
    bool isInsufficient =
        msg.contains('insufficient') || msg.contains('stale');
    int? rowsFound;
    int? rowsRequired;

    if (payload is Map) {
      final err = payload['error']?.toString().toLowerCase();
      if (err == 'insufficient_data' ||
          payload.toString().contains('insufficient_data') ||
          payload.toString().contains('insufficient')) {
        isInsufficient = true;
      }
      rowsFound = (payload['rows_found'] as num?)?.toInt();
      rowsRequired = (payload['rows_required'] as num?)?.toInt();
      if (payload['message'] != null) {
        finalMessage = payload['message'].toString();
      }
    } else if (payload is List) {
      if (payload.toString().contains('insufficient_data')) {
        isInsufficient = true;
      }
    }

    if (isInsufficient) {
      throw InsufficientDataException(
        message: finalMessage,
        rowsFound: rowsFound,
        rowsRequired: rowsRequired,
        intersectionId: intersectionId,
        details: e.details,
      );
    }
  }
}

/// Service managing intelligent traffic control recommendations, timing optimizations,
/// macroscopic simulations, and supervisory decisions.
class ControlService {
  ControlService({required this.apiClient});

  final ApiClient apiClient;

  /// Retrieves supervisory recommendation for an intersection via POST-only
  /// `/control/recommendations`.
  ///
  /// Maps 422 insufficient/stale telemetry to [InsufficientDataException].
  Future<ControlRecommendation> getRecommendations(int intersectionId) async {
    try {
      final dynamic res = await apiClient.post(
        '/control/recommendations',
        body: {'intersection_id': intersectionId},
      );

      if (res is Map<String, dynamic>) {
        return ControlRecommendation.fromJson(res);
      }
      throw ApiException(
        statusCode: 500,
        message: 'Invalid response format for control recommendations',
      );
    } on ApiException catch (e) {
      _checkAndMapInsufficientData(e, intersectionId);
      rethrow;
    }
  }

  /// Calculates Webster-inspired green splits via POST `/control/optimize-signals`.
  ///
  /// Requires officer or admin role. Throws [ApiException] on 403 or network failure.
  Future<OptimizationResult> optimizeSignals(
    int intersectionId, {
    List<Map<String, dynamic>>? phaseDemands,
    Map<String, dynamic>? cycleConfig,
  }) async {
    final defaultDemands = [
      {
        'phase_id': 1,
        'queue_length': 12.0,
        'density': 28.5,
        'flow_veh_per_min': 24.0,
        'lane_count': 2,
        'is_emergency_route': false,
      },
      {
        'phase_id': 2,
        'queue_length': 8.0,
        'density': 18.0,
        'flow_veh_per_min': 16.0,
        'lane_count': 2,
        'is_emergency_route': false,
      },
    ];

    final payload = <String, dynamic>{
      'intersection_id': intersectionId,
      'phase_demands': phaseDemands ?? defaultDemands,
      'cycle_config': ?cycleConfig,
    };

    try {
      final dynamic res = await apiClient.post(
        '/control/optimize-signals',
        body: payload,
      );

      if (res is Map<String, dynamic>) {
        return OptimizationResult.fromJson(res);
      }
      throw ApiException(
        statusCode: 500,
        message: 'Invalid response format for signal optimization',
      );
    } on ApiException catch (e) {
      _checkAndMapInsufficientData(e, intersectionId);
      rethrow;
    }
  }

  /// Runs deterministic macroscopic what-if point-queue traffic simulation comparing
  /// baseline vs proposed signal timing plans via POST `/control/simulate`.
  Future<SimulationComparison> simulate({
    required int intersectionId,
    required Map<String, dynamic> proposedPlan,
    List<Map<String, dynamic>>? approaches,
    Map<String, dynamic>? currentPlan,
    double horizonMinutes = 15.0,
  }) async {
    final defaultApproaches = [
      {
        'approach_id': 'northbound',
        'queue_veh': 14.0,
        'arrival_rate_veh_per_min': 18.0,
        'saturation_flow_veh_per_min': 30.0,
        'lane_count': 2,
        'name': 'Northbound Approach',
      },
      {
        'approach_id': 'eastbound',
        'queue_veh': 9.0,
        'arrival_rate_veh_per_min': 12.0,
        'saturation_flow_veh_per_min': 30.0,
        'lane_count': 2,
        'name': 'Eastbound Approach',
      },
    ];

    final defaultCurrentPlan = {
      'phases': {'phase_1': 30.0, 'phase_2': 30.0},
      'phase_to_approaches': {
        'phase_1': ['northbound'],
        'phase_2': ['eastbound'],
      },
      'yellow_s': 3.0,
      'all_red_s': 2.0,
    };

    final payload = <String, dynamic>{
      'intersection_id': intersectionId,
      'approaches': approaches ?? defaultApproaches,
      'current_plan': currentPlan ?? defaultCurrentPlan,
      'proposed_plan': proposedPlan,
      'horizon_minutes': horizonMinutes,
      'dt_seconds': 5.0,
    };

    try {
      final dynamic res = await apiClient.post(
        '/control/simulate',
        body: payload,
      );

      if (res is Map<String, dynamic>) {
        return SimulationComparison.fromJson(res);
      }
      throw ApiException(
        statusCode: 500,
        message: 'Invalid response format for simulation comparison',
      );
    } on ApiException catch (e) {
      _checkAndMapInsufficientData(e, intersectionId);
      rethrow;
    }
  }

  /// Retrieves paginated advisory control decisions from GET `/control/decisions`.
  Future<PaginatedControlDecisions> getDecisions({
    int? intersectionId,
    int page = 1,
    int perPage = 20,
  }) async {
    final queryParams = <String, dynamic>{};
    if (intersectionId != null) {
      queryParams['intersection_id'] = intersectionId;
    }

    final dynamic res = await apiClient.get(
      '/control/decisions',
      queryParameters: queryParams.isEmpty ? null : queryParams,
      page: page,
      perPage: perPage,
    );

    if (res is Map<String, dynamic>) {
      return PaginatedControlDecisions.fromJson(res);
    }
    return const PaginatedControlDecisions(
      items: [],
      total: 0,
      page: 1,
      perPage: 20,
      pages: 1,
    );
  }
}

/// Provider supplying the [ControlService] instance.
final Provider<ControlService> controlServiceProvider =
    Provider<ControlService>((ref) {
  final client = ref.watch(apiClientProvider);
  return ControlService(apiClient: client);
});
