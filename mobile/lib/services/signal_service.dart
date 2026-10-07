import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/signal.dart';
import 'api_client.dart';
import 'auth_service.dart';

/// Service managing hardware traffic signal controllers and operational overrides.
class SignalService {
  SignalService({required this.apiClient});

  final ApiClient apiClient;

  /// Retrieves paginated list of traffic signals from GET `/signals`.
  Future<PaginatedSignals> getSignals({
    int? intersectionId,
    String? status,
    int page = 1,
    int perPage = 20,
  }) async {
    final queryParams = <String, dynamic>{};
    if (intersectionId != null) {
      queryParams['intersection_id'] = intersectionId;
    }
    if (status != null && status.isNotEmpty) {
      queryParams['status'] = status;
    }

    final dynamic res = await apiClient.get(
      '/signals',
      queryParameters: queryParams.isEmpty ? null : queryParams,
      page: page,
      perPage: perPage,
    );

    if (res is Map<String, dynamic>) {
      return PaginatedSignals.fromJson(res);
    }
    return const PaginatedSignals(
      items: [],
      total: 0,
      page: 1,
      perPage: 20,
      pages: 1,
    );
  }

  /// Retrieves single signal controller details and phases from GET `/signals/{id}`.
  Future<Signal> getSignal(int id) async {
    final dynamic res = await apiClient.get('/signals/$id');
    if (res is Map<String, dynamic>) {
      return Signal.fromJson(res);
    }
    throw ApiException(
      statusCode: 500,
      message: 'Failed to parse signal response for ID $id',
    );
  }

  /// Executes manual phase override for traffic officers or admins via POST `/signals/{id}/override`.
  ///
  /// Sends payload `{phase, duration_seconds}` along with optional state and operational justification.
  Future<Signal> overrideSignal(
    int id, {
    String? phase,
    int? phaseId,
    int? durationSeconds,
    String? state,
    String? reason,
  }) async {
    final payload = <String, dynamic>{};
    if (phase != null) {
      payload['phase'] = phase;
    }
    if (durationSeconds != null) {
      payload['duration_seconds'] = durationSeconds;
    }
    if (phaseId != null) {
      payload['phase_id'] = phaseId;
    }
    if (state != null) {
      payload['state'] = state;
    }
    if (reason != null && reason.isNotEmpty) {
      payload['reason'] = reason;
    }

    final dynamic res = await apiClient.post(
      '/signals/$id/override',
      body: payload,
    );

    if (res is Map<String, dynamic>) {
      return Signal.fromJson(res);
    }
    throw ApiException(
      statusCode: 500,
      message: 'Failed to parse signal override response for ID $id',
    );
  }
}

/// Provider supplying the [SignalService] instance.
final Provider<SignalService> signalServiceProvider =
    Provider<SignalService>((ref) {
  final client = ref.watch(apiClientProvider);
  return SignalService(apiClient: client);
});
