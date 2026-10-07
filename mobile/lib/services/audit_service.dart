import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/audit_entry.dart';
import 'api_client.dart';
import 'auth_service.dart';

/// Service managing administrative immutable audit log queries.
class AuditService {
  AuditService({required this.apiClient});

  final ApiClient apiClient;

  /// Retrieves paginated audit logs from GET `/audit-logs` (admin restricted).
  Future<PaginatedAuditEntries> getAuditLogs({
    String? action,
    String? entityType,
    int? actorUserId,
    DateTime? from,
    DateTime? to,
    int page = 1,
    int perPage = 20,
  }) async {
    final queryParams = <String, dynamic>{};
    if (action != null && action.isNotEmpty) {
      queryParams['action'] = action;
    }
    if (entityType != null && entityType.isNotEmpty) {
      queryParams['entity_type'] = entityType;
    }
    if (actorUserId != null) {
      queryParams['actor_user_id'] = actorUserId;
    }
    if (from != null) {
      queryParams['from'] = from.toIso8601String();
    }
    if (to != null) {
      queryParams['to'] = to.toIso8601String();
    }

    try {
      final dynamic res = await apiClient.get(
        '/audit-logs',
        queryParameters: queryParams.isEmpty ? null : queryParams,
        page: page,
        perPage: perPage,
      );

      if (res is Map<String, dynamic>) {
        return PaginatedAuditEntries.fromJson(res);
      }

      return const PaginatedAuditEntries(
        items: [],
        total: 0,
        page: 1,
        perPage: 20,
        pages: 1,
      );
    } on ApiException catch (e) {
      if (e.isForbidden || e.statusCode == 403) {
        throw ApiException(
          message:
              'Access denied: Only system administrators may view the operational audit log.',
          statusCode: 403,
          details: e.details,
        );
      }
      rethrow;
    }
  }
}

/// Riverpod provider exposing [AuditService].
final auditServiceProvider = Provider<AuditService>((ref) {
  final client = ref.watch(apiClientProvider);
  return AuditService(apiClient: client);
});
