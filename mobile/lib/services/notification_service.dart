import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/notification.dart';
import 'api_client.dart';
import 'auth_service.dart';

/// Service managing user notifications, operator alerts, and system broadcasts.
class NotificationService {
  NotificationService({required this.apiClient});

  final ApiClient apiClient;

  /// Retrieves paginated notifications targeted to the authenticated user and broadcasts.
  Future<PaginatedNotifications> getMyNotifications({
    bool? isRead,
    String? severity,
    int page = 1,
    int perPage = 20,
  }) async {
    final queryParams = <String, dynamic>{};
    if (isRead != null) {
      queryParams['is_read'] = isRead;
    }
    if (severity != null && severity.isNotEmpty) {
      queryParams['severity'] = severity;
    }

    final dynamic res = await apiClient.get(
      '/notifications/me',
      queryParameters: queryParams.isEmpty ? null : queryParams,
      page: page,
      perPage: perPage,
    );

    if (res is Map<String, dynamic>) {
      return PaginatedNotifications.fromJson(res);
    }

    return const PaginatedNotifications(
      items: [],
      total: 0,
      page: 1,
      perPage: 20,
      pages: 1,
    );
  }

  /// Marks a notification or broadcast alert as read.
  ///
  /// Supports PATCH `/notifications/{id}/read` (and POST fallback if required).
  Future<AppNotification> markAsRead(int id) async {
    try {
      final dynamic res = await apiClient.patch('/notifications/$id/read');
      if (res is Map<String, dynamic>) {
        return AppNotification.fromJson(res);
      }
    } on ApiException catch (e) {
      if (e.statusCode == 405 || e.statusCode == 404) {
        final dynamic res = await apiClient.post('/notifications/$id/read');
        if (res is Map<String, dynamic>) {
          return AppNotification.fromJson(res);
        }
      }
      rethrow;
    }

    throw const ApiException(
      message: 'Failed to parse mark notification read response',
      statusCode: 500,
    );
  }

  /// Calculates total unread notifications count via `/notifications/me?is_read=false`.
  Future<int> unreadCount() async {
    final paginated = await getMyNotifications(
      isRead: false,
      page: 1,
      perPage: 1,
    );
    return paginated.total;
  }
}

/// Riverpod provider exposing [NotificationService].
final notificationServiceProvider = Provider<NotificationService>((ref) {
  final client = ref.watch(apiClientProvider);
  return NotificationService(apiClient: client);
});

/// Riverpod provider for active unread notification badge count.
final unreadNotificationCountProvider =
    FutureProvider.autoDispose<int>((ref) async {
  final service = ref.watch(notificationServiceProvider);
  return service.unreadCount();
});
