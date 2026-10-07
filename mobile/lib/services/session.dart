import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../core/app_config.dart';
import '../models/user.dart';
import 'api_client.dart';
import 'auth_service.dart';

/// Service dedicated to lifecycle session inspection and restoration on boot.
class SessionService {
  SessionService({
    required this.authService,
    this.storage = const FlutterSecureStorage(),
  });

  final AuthService authService;
  final FlutterSecureStorage storage;

  /// Restores session on app startup by validating stored credentials.
  ///
  /// Flow:
  /// 1. Reads stored access and refresh tokens.
  /// 2. If neither exists -> returns null (unauthenticated).
  /// 3. If access token exists, verifies via GET `/auth/me`.
  /// 4. If access token is expired (401) or absent, attempts refresh via stored refresh token.
  /// 5. If refresh fails or is expired, cleans up storage via logout() and returns null.
  Future<User?> restoreSession() async {
    final accessToken = await storage.read(key: AppConfig.accessTokenKey);
    final refreshToken = await storage.read(key: AppConfig.refreshTokenKey);

    if (accessToken == null && refreshToken == null) {
      return null;
    }

    try {
      if (accessToken != null && accessToken.isNotEmpty) {
        final user = await authService.getCurrentUser();
        if (user != null) {
          return user;
        }
      }

      if (refreshToken != null && refreshToken.isNotEmpty) {
        return await authService.refreshSession();
      }
    } on ApiException catch (e) {
      if (e.isUnauthorized) {
        if (refreshToken != null) {
          return await authService.refreshSession();
        }
      }
      await authService.logout();
    } catch (_) {
      await authService.logout();
    }

    return null;
  }
}

/// Provider for SessionService.
final Provider<SessionService> sessionServiceProvider =
    Provider<SessionService>((ref) {
  final authService = ref.watch(authServiceProvider);
  return SessionService(authService: authService);
});

/// Async future provider that restores the user session on app initialization.
final FutureProvider<User?> sessionRestoreProvider =
    FutureProvider<User?>((ref) async {
  final sessionService = ref.watch(sessionServiceProvider);
  final user = await sessionService.restoreSession();
  if (user != null) {
    ref.read(authStateProvider.notifier).setAuthenticated(user);
  } else {
    ref.read(authStateProvider.notifier).setUnauthenticated();
  }
  return user;
});
