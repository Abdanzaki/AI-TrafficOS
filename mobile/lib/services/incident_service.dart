import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/incident.dart';
import 'api_client.dart';
import 'auth_service.dart';

/// Service managing incident queries, creation, and lifecycle status transitions.
class IncidentService {
  IncidentService({required this.apiClient});

  final ApiClient apiClient;

  /// Retrieves paginated incidents from GET `/incidents`.
  Future<PaginatedIncidents> getIncidents({
    int page = 1,
    int perPage = 20,
    String? status,
    String? severity,
    int? intersectionId,
    DateTime? from,
    DateTime? to,
  }) async {
    final queryParams = <String, dynamic>{};
    if (status != null && status.isNotEmpty) {
      queryParams['status'] = status;
    }
    if (severity != null && severity.isNotEmpty) {
      queryParams['severity'] = severity;
    }
    if (intersectionId != null) {
      queryParams['intersection_id'] = intersectionId;
    }
    if (from != null) {
      queryParams['from'] = from.toIso8601String();
      queryParams['created_from'] = from.toIso8601String();
    }
    if (to != null) {
      queryParams['to'] = to.toIso8601String();
    }

    final dynamic res = await apiClient.get(
      '/incidents',
      queryParameters: queryParams.isEmpty ? null : queryParams,
      page: page,
      perPage: perPage,
    );

    if (res is Map<String, dynamic>) {
      return PaginatedIncidents.fromJson(res);
    }
    return const PaginatedIncidents(
      items: [],
      total: 0,
      page: 1,
      perPage: 20,
      pages: 1,
    );
  }

  /// Retrieves single incident details from GET `/incidents/{id}`.
  Future<Incident> getIncident(int id) async {
    final dynamic res = await apiClient.get('/incidents/$id');
    if (res is Map<String, dynamic>) {
      return Incident.fromJson(res);
    }
    throw ApiException(
      message: 'Incident $id could not be found',
      statusCode: 404,
    );
  }

  /// Reports a new traffic incident or hazard via POST `/incidents`.
  Future<Incident> createIncident({
    required String severity,
    String status = 'reported',
    String? description,
    String? title,
    int? intersectionId,
    double? latitude,
    double? longitude,
  }) async {
    // Form composite description if both title and description provided
    String? finalDesc = description;
    if (title != null && title.trim().isNotEmpty) {
      if (description != null && description.trim().isNotEmpty) {
        finalDesc = '${title.trim()}: ${description.trim()}';
      } else {
        finalDesc = title.trim();
      }
    }

    final body = <String, dynamic>{
      'severity': severity.toLowerCase(),
      'status': status.toLowerCase(),
    };
    if (finalDesc != null) body['description'] = finalDesc;
    if (title != null) body['title'] = title;
    if (intersectionId != null) body['intersection_id'] = intersectionId;
    if (latitude != null) body['lat'] = latitude;
    if (longitude != null) body['lon'] = longitude;

    final dynamic res = await apiClient.post(
      '/incidents',
      body: body,
    );

    if (res is Map<String, dynamic>) {
      return Incident.fromJson(res);
    }

    throw ApiException(
      message: 'Failed to parse created incident response',
      statusCode: 500,
    );
  }

  /// Updates incident lifecycle status via PATCH `/incidents/{id}`.
  ///
  /// Enforces client-side transition validation matching backend contract:
  /// - Cannot transition an incident from `resolved` to `reported`.
  Future<Incident> updateIncidentStatus({
    required int id,
    required String status,
    String? currentStatus,
  }) async {
    final target = status.toLowerCase();

    // Client-side transition validation
    if (currentStatus != null) {
      final current = currentStatus.toLowerCase();
      if (!Incident.isValidTransition(current, target)) {
        throw ApiException(
          message:
              'Invalid status transition: cannot transition incident from $current to $target',
          statusCode: 400,
        );
      }
    }

    final dynamic res = await apiClient.patch(
      '/incidents/$id',
      body: {'status': target},
    );

    if (res is Map<String, dynamic>) {
      return Incident.fromJson(res);
    }

    throw ApiException(
      message: 'Failed to parse updated incident response',
      statusCode: 500,
    );
  }
}

/// Provider supplying the [IncidentService] instance.
final Provider<IncidentService> incidentServiceProvider =
    Provider<IncidentService>((ref) {
  final client = ref.watch(apiClientProvider);
  return IncidentService(apiClient: client);
});
