import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/app_user.dart';
import 'api_client.dart';
import 'auth_service.dart';

/// Service managing administrative user account provisioning, role adjustments, and deactivation.
class UserService {
  UserService({required this.apiClient});

  final ApiClient apiClient;

  /// Retrieves paginated system users from GET `/users` (admin restricted).
  Future<PaginatedUsers> getUsers({
    int page = 1,
    int perPage = 20,
  }) async {
    try {
      final dynamic res = await apiClient.get(
        '/users',
        page: page,
        perPage: perPage,
      );

      if (res is Map<String, dynamic>) {
        return PaginatedUsers.fromJson(res);
      }

      return const PaginatedUsers(
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
              'Access denied: Only system administrators may view user accounts.',
          statusCode: 403,
          details: e.details,
        );
      }
      rethrow;
    }
  }

  /// Provisions a new operator account via POST `/users` (admin restricted).
  Future<AppUser> createUser({
    required String email,
    required String password,
    required String fullName,
    required String role,
  }) async {
    final body = <String, dynamic>{
      'email': email.trim().toLowerCase(),
      'password': password,
      'full_name': fullName.trim(),
      'role_name': role.trim().toLowerCase(),
    };

    try {
      final dynamic res = await apiClient.post(
        '/users',
        body: body,
      );

      if (res is Map<String, dynamic>) {
        return AppUser.fromJson(res);
      }

      throw const ApiException(
        message: 'Failed to parse created user response',
        statusCode: 500,
      );
    } on ApiException catch (e) {
      if (e.isForbidden || e.statusCode == 403) {
        throw ApiException(
          message:
              'Access denied: Only system administrators may create user accounts.',
          statusCode: 403,
          details: e.details,
        );
      }
      rethrow;
    }
  }

  /// Updates operator account details and RBAC role via PATCH `/users/{id}` (admin restricted).
  Future<AppUser> updateUser(
    int id, {
    String? fullName,
    String? role,
    bool? isActive,
  }) async {
    final body = <String, dynamic>{};
    if (fullName != null) {
      body['full_name'] = fullName.trim();
    }
    if (role != null) {
      body['role_name'] = role.trim().toLowerCase();
    }
    if (isActive != null) {
      body['is_active'] = isActive;
    }

    try {
      final dynamic res = await apiClient.patch(
        '/users/$id',
        body: body,
      );

      if (res is Map<String, dynamic>) {
        return AppUser.fromJson(res);
      }

      throw const ApiException(
        message: 'Failed to parse updated user response',
        statusCode: 500,
      );
    } on ApiException catch (e) {
      if (e.isForbidden || e.statusCode == 403) {
        throw ApiException(
          message:
              'Access denied: Only system administrators may modify user accounts.',
          statusCode: 403,
          details: e.details,
        );
      }
      rethrow;
    }
  }

  /// Deactivates/soft-deletes an operator account via DELETE `/users/{id}` (admin restricted).
  Future<AppUser> deleteUser(int id) async {
    try {
      final dynamic res = await apiClient.delete('/users/$id');

      if (res is Map<String, dynamic>) {
        return AppUser.fromJson(res);
      }

      throw const ApiException(
        message: 'Failed to parse deactivated user response',
        statusCode: 500,
      );
    } on ApiException catch (e) {
      if (e.isForbidden || e.statusCode == 403) {
        throw ApiException(
          message:
              'Access denied: Only system administrators may deactivate user accounts.',
          statusCode: 403,
          details: e.details,
        );
      }
      rethrow;
    }
  }
}

/// Riverpod provider exposing [UserService].
final userServiceProvider = Provider<UserService>((ref) {
  final client = ref.watch(apiClientProvider);
  return UserService(apiClient: client);
});
