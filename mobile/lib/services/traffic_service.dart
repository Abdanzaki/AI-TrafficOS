import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/congestion_ranking.dart';
import '../models/hotspot.dart';
import '../models/incident.dart';
import '../models/traffic_record.dart';
import '../models/traffic_summary.dart';
import '../models/vehicle_event.dart';
import 'api_client.dart';
import 'auth_service.dart';

/// Traffic analytics and telemetry client service.
class TrafficService {
  TrafficService({required this.apiClient});

  final ApiClient apiClient;

  /// Retrieves bucketed traffic telemetry aggregation from GET `/analytics/traffic-summary`.
  Future<List<TrafficSummaryBucket>> getTrafficSummary({
    String bucket = 'hour',
    int? intersectionId,
    DateTime? from,
    DateTime? to,
  }) async {
    final queryParams = <String, dynamic>{
      'bucket': bucket,
    };
    if (intersectionId != null) {
      queryParams['intersection_id'] = intersectionId;
    }
    if (from != null) {
      queryParams['from'] = from.toIso8601String();
    }
    if (to != null) {
      queryParams['to'] = to.toIso8601String();
    }

    final dynamic res = await apiClient.get(
      '/analytics/traffic-summary',
      queryParameters: queryParams,
    );

    if (res is List) {
      return res
          .whereType<Map<String, dynamic>>()
          .map(TrafficSummaryBucket.fromJson)
          .toList();
    }
    return [];
  }

  /// Retrieves top-k congestion hotspots from GET `/analytics/congestion-hotspots`.
  Future<List<CongestionHotspot>> getHotspots({
    int limit = 10,
    DateTime? from,
    DateTime? to,
  }) async {
    final queryParams = <String, dynamic>{
      'limit': limit,
    };
    if (from != null) {
      queryParams['from'] = from.toIso8601String();
    }
    if (to != null) {
      queryParams['to'] = to.toIso8601String();
    }

    final dynamic res = await apiClient.get(
      '/analytics/congestion-hotspots',
      queryParameters: queryParams,
    );

    if (res is List) {
      return res
          .whereType<Map<String, dynamic>>()
          .map(CongestionHotspot.fromJson)
          .toList();
    }
    return [];
  }

  /// Retrieves aggregated incident counts by severity and status from GET `/analytics/incidents-summary`.
  Future<IncidentsSummary> getIncidentsSummary({
    DateTime? from,
    DateTime? to,
  }) async {
    final queryParams = <String, dynamic>{};
    if (from != null) {
      queryParams['from'] = from.toIso8601String();
    }
    if (to != null) {
      queryParams['to'] = to.toIso8601String();
    }

    final dynamic res = await apiClient.get(
      '/analytics/incidents-summary',
      queryParameters: queryParams.isEmpty ? null : queryParams,
    );

    if (res is Map<String, dynamic>) {
      return IncidentsSummary.fromJson(res);
    }
    return const IncidentsSummary(total: 0, bySeverity: {}, byStatus: {});
  }

  /// Retrieves paginated sensor traffic records from GET `/traffic-records`.
  Future<PaginatedTrafficRecords> getTrafficRecords({
    int? intersectionId,
    int? laneId,
    DateTime? from,
    DateTime? to,
    String? source,
    int page = 1,
    int perPage = 20,
  }) async {
    final queryParams = <String, dynamic>{};
    if (intersectionId != null) {
      queryParams['intersection_id'] = intersectionId;
    }
    if (laneId != null) {
      queryParams['lane_id'] = laneId;
    }
    if (from != null) {
      queryParams['recorded_from'] = from.toIso8601String();
      queryParams['from'] = from.toIso8601String();
    }
    if (to != null) {
      queryParams['recorded_to'] = to.toIso8601String();
      queryParams['to'] = to.toIso8601String();
    }
    if (source != null && source.isNotEmpty) {
      queryParams['source'] = source;
    }

    final dynamic res = await apiClient.get(
      '/traffic-records',
      queryParameters: queryParams.isEmpty ? null : queryParams,
      page: page,
      perPage: perPage,
    );

    if (res is Map<String, dynamic>) {
      return PaginatedTrafficRecords.fromJson(res);
    }
    return const PaginatedTrafficRecords(
      items: [],
      total: 0,
      page: 1,
      perPage: 20,
      pages: 1,
    );
  }

  /// Retrieves paginated vehicle detection events from GET `/vehicle-events`.
  Future<PaginatedVehicleEvents> getVehicleEvents({
    int? intersectionId,
    int? laneId,
    String? vehicleType,
    int page = 1,
    int perPage = 20,
  }) async {
    final queryParams = <String, dynamic>{};
    if (intersectionId != null) {
      queryParams['intersection_id'] = intersectionId;
    }
    if (laneId != null) {
      queryParams['lane_id'] = laneId;
    }
    if (vehicleType != null && vehicleType.isNotEmpty) {
      queryParams['vehicle_type'] = vehicleType;
    }

    final dynamic res = await apiClient.get(
      '/vehicle-events',
      queryParameters: queryParams.isEmpty ? null : queryParams,
      page: page,
      perPage: perPage,
    );

    if (res is Map<String, dynamic>) {
      return PaginatedVehicleEvents.fromJson(res);
    }
    return const PaginatedVehicleEvents(
      items: [],
      total: 0,
      page: 1,
      perPage: 20,
      pages: 1,
    );
  }

  /// Retrieves corridor congestion rankings from GET `/routing/congestion-ranking`.
  Future<List<CongestionRankingItem>> getCongestionRanking({
    int limit = 10,
  }) async {
    final dynamic res = await apiClient.get(
      '/routing/congestion-ranking',
      queryParameters: {'limit': limit},
    );

    if (res is List) {
      return res
          .whereType<Map<String, dynamic>>()
          .map(CongestionRankingItem.fromJson)
          .toList();
    }
    return [];
  }
}

/// Provider supplying the [TrafficService] instance.
final Provider<TrafficService> trafficServiceProvider =
    Provider<TrafficService>((ref) {
  final client = ref.watch(apiClientProvider);
  return TrafficService(apiClient: client);
});
