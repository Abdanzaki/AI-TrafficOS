import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/emergency_event.dart';
import 'api_client.dart';
import 'auth_service.dart';

/// Service managing emergency transit events, priority green corridor preemption, and restoration.
class EmergencyService {
  EmergencyService({required this.apiClient});

  final ApiClient apiClient;

  /// Retrieves paginated emergency events from GET `/emergency-events`.
  Future<PaginatedEmergencyEvents> getEmergencyEvents({
    int page = 1,
    int perPage = 20,
    String? status,
    int? priority,
    DateTime? from,
    DateTime? to,
  }) async {
    final queryParams = <String, dynamic>{};
    if (status != null && status.isNotEmpty) {
      queryParams['status'] = status;
    }
    if (priority != null) {
      queryParams['priority'] = priority;
    }
    if (from != null) {
      queryParams['from'] = from.toIso8601String();
      queryParams['detected_from'] = from.toIso8601String();
    }
    if (to != null) {
      queryParams['to'] = to.toIso8601String();
    }

    final dynamic res = await apiClient.get(
      '/emergency-events',
      queryParameters: queryParams.isEmpty ? null : queryParams,
      page: page,
      perPage: perPage,
    );

    if (res is Map<String, dynamic>) {
      return PaginatedEmergencyEvents.fromJson(res);
    }
    return const PaginatedEmergencyEvents(
      items: [],
      total: 0,
      page: 1,
      perPage: 20,
      pages: 1,
    );
  }

  /// Retrieves details for a specific emergency event from GET `/emergency-events/{id}`.
  Future<EmergencyEvent> getEmergencyEvent(int id) async {
    final dynamic res = await apiClient.get('/emergency-events/$id');
    if (res is Map<String, dynamic>) {
      return EmergencyEvent.fromJson(res);
    }
    throw ApiException(
      message: 'Emergency event $id not found',
      statusCode: 404,
    );
  }

  /// Dispatches or logs a new emergency event via POST `/emergency-events`.
  Future<EmergencyEvent> createEmergencyEvent({
    required String vehicleType,
    int priority = 1,
    int? intersectionId,
    int? incidentId,
    String status = 'active',
  }) async {
    final body = <String, dynamic>{
      'vehicle_type': vehicleType,
      'priority': priority,
      'status': status,
    };
    if (intersectionId != null) body['intersection_id'] = intersectionId;
    if (incidentId != null) body['incident_id'] = incidentId;

    final dynamic res = await apiClient.post(
      '/emergency-events',
      body: body,
    );

    if (res is Map<String, dynamic>) {
      return EmergencyEvent.fromJson(res);
    }

    throw ApiException(
      message: 'Failed to create emergency event',
      statusCode: 500,
    );
  }

  /// Activates advisory green wave corridor preemption via POST `/control/emergency/prioritize`.
  Future<EmergencyPrioritizeResult> prioritize({
    required int emergencyEventId,
    int? destinationIntersectionId,
  }) async {
    final body = <String, dynamic>{
      'emergency_event_id': emergencyEventId,
    };
    if (destinationIntersectionId != null) {
      body['destination_intersection_id'] = destinationIntersectionId;
    }

    final dynamic res = await apiClient.post(
      '/control/emergency/prioritize',
      body: body,
    );

    if (res is Map<String, dynamic>) {
      return EmergencyPrioritizeResult.fromJson(res);
    }

    throw ApiException(
      message: 'Invalid response from emergency prioritize endpoint',
      statusCode: 500,
    );
  }

  /// Concludes emergency preemption and restores normal cyclic signal plans via POST `/control/emergency/restore`.
  Future<EmergencyRestoreResult> restore({
    required int emergencyEventId,
  }) async {
    final body = <String, dynamic>{
      'emergency_event_id': emergencyEventId,
    };

    final dynamic res = await apiClient.post(
      '/control/emergency/restore',
      body: body,
    );

    if (res is Map<String, dynamic>) {
      return EmergencyRestoreResult.fromJson(res);
    }

    throw ApiException(
      message: 'Invalid response from emergency restore endpoint',
      statusCode: 500,
    );
  }

  /// Calculates advisory green wave corridor recommendation without physical signal actuation via POST `/control/green-corridor/recommend`.
  Future<GreenCorridorRecommendResult> greenCorridorRecommend({
    int? emergencyEventId,
    int? fromIntersectionId,
    int? toIntersectionId,
    double emergencySpeedKmh = 60.0,
  }) async {
    final body = <String, dynamic>{
      'emergency_speed_kmh': emergencySpeedKmh,
    };
    if (emergencyEventId != null) {
      body['emergency_event_id'] = emergencyEventId;
    }
    if (fromIntersectionId != null) {
      body['from_intersection_id'] = fromIntersectionId;
    }
    if (toIntersectionId != null) {
      body['to_intersection_id'] = toIntersectionId;
    }

    final dynamic res = await apiClient.post(
      '/control/green-corridor/recommend',
      body: body,
    );

    if (res is Map<String, dynamic>) {
      return GreenCorridorRecommendResult.fromJson(res);
    }

    throw ApiException(
      message: 'Invalid response from green corridor recommend endpoint',
      statusCode: 500,
    );
  }
}

/// Provider supplying the [EmergencyService] instance.
final Provider<EmergencyService> emergencyServiceProvider =
    Provider<EmergencyService>((ref) {
  final client = ref.watch(apiClientProvider);
  return EmergencyService(apiClient: client);
});
