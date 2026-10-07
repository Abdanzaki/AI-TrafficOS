import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/route_result.dart';
import 'api_client.dart';
import 'auth_service.dart';

/// Service managing municipal pathfinding and optimal vehicle routing.
class RoutingService {
  RoutingService({required this.apiClient});

  final ApiClient apiClient;

  /// Calculates minimum impedance route between intersections via POST `/routing/optimal-route`.
  Future<RouteResult> getOptimalRoute({
    required int fromIntersectionId,
    required int toIntersectionId,
    String algorithm = 'astar',
    double timeWeight = 1.0,
    double congestionWeight = 1.0,
    double distanceWeight = 0.15,
    double conditionWeight = 0.5,
  }) async {
    final body = <String, dynamic>{
      'from_intersection_id': fromIntersectionId,
      'to_intersection_id': toIntersectionId,
      'algorithm': algorithm,
      'time_weight': timeWeight,
      'congestion_weight': congestionWeight,
      'distance_weight': distanceWeight,
      'condition_weight': conditionWeight,
    };

    final dynamic res = await apiClient.post(
      '/routing/optimal-route',
      body: body,
    );

    if (res is Map<String, dynamic>) {
      return RouteResult.fromJson(res);
    }

    throw ApiException(
      message: 'Failed to calculate optimal route',
      statusCode: 500,
    );
  }
}

/// Provider supplying the [RoutingService] instance.
final Provider<RoutingService> routingServiceProvider =
    Provider<RoutingService>((ref) {
  final client = ref.watch(apiClientProvider);
  return RoutingService(apiClient: client);
});
