import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/hotspot.dart';
import '../models/incident.dart';
import '../models/traffic_summary.dart';
import 'traffic_service.dart';

/// Aggregation and reporting service for citywide traffic flow, hotspots, and incidents.
/// Reuses and delegates to [TrafficService] to eliminate duplication.
class AnalyticsService {
  AnalyticsService({required this.trafficService});

  final TrafficService trafficService;

  /// Retrieves bucketed traffic telemetry aggregation from GET `/analytics/traffic-summary`.
  Future<List<TrafficSummaryBucket>> getTrafficSummary({
    String bucket = 'hour',
    int? intersectionId,
    DateTime? from,
    DateTime? to,
  }) {
    return trafficService.getTrafficSummary(
      bucket: bucket,
      intersectionId: intersectionId,
      from: from,
      to: to,
    );
  }

  /// Retrieves top-k congestion hotspots from GET `/analytics/congestion-hotspots`.
  Future<List<CongestionHotspot>> getHotspots({
    int limit = 10,
    DateTime? from,
    DateTime? to,
  }) {
    return trafficService.getHotspots(
      limit: limit,
      from: from,
      to: to,
    );
  }

  /// Retrieves aggregated incident counts by severity and status from GET `/analytics/incidents-summary`.
  Future<IncidentsSummary> getIncidentsSummary({
    DateTime? from,
    DateTime? to,
  }) {
    return trafficService.getIncidentsSummary(
      from: from,
      to: to,
    );
  }
}

/// Provider supplying the [AnalyticsService] instance.
final Provider<AnalyticsService> analyticsServiceProvider =
    Provider<AnalyticsService>((ref) {
  final trafficService = ref.watch(trafficServiceProvider);
  return AnalyticsService(trafficService: trafficService);
});
