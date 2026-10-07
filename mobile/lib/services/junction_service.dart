import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/junction.dart';
import 'api_client.dart';
import 'auth_service.dart';

/// Service managing physical junction and intersection data.
class JunctionService {
  JunctionService({required this.apiClient});

  final ApiClient apiClient;

  /// Retrieves paginated intersections from GET `/junctions`.
  Future<PaginatedJunctions> getJunctions({
    int page = 1,
    int perPage = 20,
    String? status,
    String? search,
    String? city,
    String? zone,
  }) async {
    final queryParams = <String, dynamic>{};
    if (status != null && status.isNotEmpty) {
      queryParams['status'] = status;
    }
    if (search != null && search.isNotEmpty) {
      queryParams['search'] = search;
    }
    if (city != null && city.isNotEmpty) {
      queryParams['city'] = city;
    }
    if (zone != null && zone.isNotEmpty) {
      queryParams['zone'] = zone;
    }

    final dynamic res = await apiClient.get(
      '/junctions',
      queryParameters: queryParams.isEmpty ? null : queryParams,
      page: page,
      perPage: perPage,
    );

    if (res is Map<String, dynamic>) {
      return PaginatedJunctions.fromJson(res);
    }
    return const PaginatedJunctions(
      items: [],
      total: 0,
      page: 1,
      perPage: 20,
      pages: 1,
    );
  }

  /// Retrieves a single junction with eager loaded signals and lanes from GET `/junctions/{id}`.
  Future<Junction> getJunction(int id) async {
    final dynamic res = await apiClient.get('/junctions/$id');
    if (res is Map<String, dynamic>) {
      return Junction.fromJson(res);
    }
    throw ApiException(
      message: 'Junction $id was not returned or could not be decoded',
      statusCode: 404,
    );
  }
}

/// Provider supplying the [JunctionService] instance.
final Provider<JunctionService> junctionServiceProvider =
    Provider<JunctionService>((ref) {
  final client = ref.watch(apiClientProvider);
  return JunctionService(apiClient: client);
});
