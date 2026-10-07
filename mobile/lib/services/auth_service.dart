import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../core/app_config.dart';
import '../models/user.dart';
import 'api_client.dart';

/// Sealed representation of authentication state across AI TrafficOS.
sealed class AuthState {
  const AuthState();

  const factory AuthState.unauthenticated({String? errorMessage}) =
      AuthUnauthenticated;
  const factory AuthState.authenticating({String? message}) =
      AuthAuthenticating;
  const factory AuthState.authenticated(User user) =
      AuthAuthenticated;

  bool get isAuthenticated => this is AuthAuthenticated;
  bool get isAuthenticating => this is AuthAuthenticating;
  bool get isUnauthenticated => this is AuthUnauthenticated;

  User? get user => switch (this) {
        AuthAuthenticated(user: final u) => u,
        _ => null,
      };

  String? get errorMessage => switch (this) {
        AuthUnauthenticated(errorMessage: final err) => err,
        _ => null,
      };
}

class AuthUnauthenticated extends AuthState {
  const AuthUnauthenticated({this.errorMessage});
  @override
  final String? errorMessage;
}

class AuthAuthenticating extends AuthState {
  const AuthAuthenticating({this.message});
  final String? message;
}

class AuthAuthenticated extends AuthState {
  const AuthAuthenticated(this.user);
  @override
  final User user;
}

/// Authentication service managing JWT storage, sessions, and profile caches.
///
/// Security policy:
/// - Stores access and refresh tokens strictly in [FlutterSecureStorage].
/// - NEVER logs access or refresh tokens to any console, logfile, or telemetry.
class AuthService {
  AuthService({
    required this.apiClient,
    this.storage = const FlutterSecureStorage(),
  });

  final ApiClient apiClient;
  final FlutterSecureStorage storage;
  User? _cachedUser;

  User? get cachedUser => _cachedUser;

  /// Authenticates credentials against POST `/auth/login`, persists JWTs,
  /// fetches the authenticated profile, and returns the [User].
  Future<User> login(String email, String password) async {
    final response = await apiClient.post(
      '/auth/login',
      body: {
        'email': email.trim().toLowerCase(),
        'password': password,
      },
      requiresAuth: false,
    );

    if (response is! Map<String, dynamic>) {
      throw const ApiException(
        message: 'Invalid response format received from authentication server',
      );
    }

    final accessToken = response['access_token'] as String?;
    final refreshToken = response['refresh_token'] as String?;

    if (accessToken == null || refreshToken == null) {
      throw const ApiException(
        message: 'Authentication tokens were missing in backend response',
      );
    }

    // Securely write JWT credentials (NEVER log tokens)
    await storage.write(key: AppConfig.accessTokenKey, value: accessToken);
    await storage.write(key: AppConfig.refreshTokenKey, value: refreshToken);

    // Fetch and cache the authenticated user's profile
    final user = await getCurrentUser();
    if (user == null) {
      throw const ApiException(
        message: 'Could not load user profile following successful login',
      );
    }
    return user;
  }

  /// Registers a new analyst account via POST `/auth/register` and establishes session.
  Future<User> register(String email, String password, String fullName) async {
    final regResponse = await apiClient.post(
      '/auth/register',
      body: {
        'email': email.trim().toLowerCase(),
        'password': password,
        'full_name': fullName.trim(),
      },
      requiresAuth: false,
    );

    if (regResponse is! Map<String, dynamic>) {
      throw const ApiException(
        message: 'Invalid registration response format from backend',
      );
    }

    // Automatically log in with new credentials to acquire access+refresh JWTs
    return await login(email, password);
  }

  /// Clears stored JWTs and user cache from device secure storage.
  Future<void> logout() async {
    await storage.delete(key: AppConfig.accessTokenKey);
    await storage.delete(key: AppConfig.refreshTokenKey);
    await storage.delete(key: AppConfig.userCacheKey);
    _cachedUser = null;
  }

  /// Validates the refresh token and exchanges it for fresh JWT credentials.
  Future<User?> refreshSession() async {
    final refreshToken = await storage.read(key: AppConfig.refreshTokenKey);
    if (refreshToken == null || refreshToken.trim().isEmpty) {
      await logout();
      return null;
    }

    try {
      final response = await apiClient.post(
        '/auth/refresh',
        body: {'refresh_token': refreshToken.trim()},
        requiresAuth: false,
      );

      if (response is Map<String, dynamic>) {
        final accessToken = response['access_token'] as String?;
        final newRefreshToken = response['refresh_token'] as String?;

        if (accessToken != null && newRefreshToken != null) {
          await storage.write(
            key: AppConfig.accessTokenKey,
            value: accessToken,
          );
          await storage.write(
            key: AppConfig.refreshTokenKey,
            value: newRefreshToken,
          );
          return await getCurrentUser();
        }
      }
      await logout();
      return null;
    } catch (_) {
      await logout();
      return null;
    }
  }

  /// Fetches the current user profile from GET `/auth/me` and updates cache.
  Future<User?> getCurrentUser() async {
    final accessToken = await storage.read(key: AppConfig.accessTokenKey);
    if (accessToken == null || accessToken.trim().isEmpty) {
      return null;
    }

    try {
      final response = await apiClient.get('/auth/me', requiresAuth: true);
      if (response is Map<String, dynamic>) {
        final user = User.fromJson(response);
        _cachedUser = user;
        await storage.write(
          key: AppConfig.userCacheKey,
          value: jsonEncode(user.toJson()),
        );
        return user;
      }
      return null;
    } on ApiException catch (e) {
      if (e.isUnauthorized) {
        return await refreshSession();
      }
      return _readCachedUser();
    } catch (_) {
      return _readCachedUser();
    }
  }

  /// Reads cached user profile if device is offline.
  Future<User?> _readCachedUser() async {
    if (_cachedUser != null) return _cachedUser;
    try {
      final cachedJsonStr = await storage.read(key: AppConfig.userCacheKey);
      if (cachedJsonStr != null) {
        final dynamic decoded = jsonDecode(cachedJsonStr);
        if (decoded is Map<String, dynamic>) {
          _cachedUser = User.fromJson(decoded);
          return _cachedUser;
        }
      }
    } catch (_) {}
    return null;
  }
}

/// State notifier exposing reactive [AuthState] to the UI.
class AuthNotifier extends StateNotifier<AuthState> {
  AuthNotifier(this.authService)
      : super(const AuthState.authenticating(message: 'Initializing session...'));

  final AuthService authService;

  /// Updates state to authenticated with the given [user].
  void setAuthenticated(User user) {
    state = AuthState.authenticated(user);
  }

  /// Updates state to unauthenticated with optional [errorMessage].
  void setUnauthenticated({String? errorMessage}) {
    state = AuthState.unauthenticated(errorMessage: errorMessage);
  }

  /// Updates state to authenticating with optional progress [message].
  void setAuthenticating({String? message}) {
    state = AuthState.authenticating(message: message);
  }

  /// Restores session by validating stored credentials.
  Future<void> restoreSession() async {
    setAuthenticating(message: 'Restoring secure session...');
    try {
      final user = await authService.getCurrentUser();
      if (user != null) {
        setAuthenticated(user);
      } else {
        setUnauthenticated();
      }
    } catch (e) {
      setUnauthenticated(
        errorMessage: e is ApiException ? e.message : 'Session validation failed',
      );
    }
  }

  /// Authenticates user credentials and emits authenticated state.
  Future<User> login(String email, String password) async {
    setAuthenticating(message: 'Authenticating credentials...');
    try {
      final user = await authService.login(email, password);
      setAuthenticated(user);
      return user;
    } catch (e) {
      final message = e is ApiException ? e.message : 'Sign in failed: $e';
      setUnauthenticated(errorMessage: message);
      rethrow;
    }
  }

  /// Creates a new user account, logs in, and emits authenticated state.
  Future<User> register(String email, String password, String fullName) async {
    setAuthenticating(message: 'Creating analyst account...');
    try {
      final user = await authService.register(email, password, fullName);
      setAuthenticated(user);
      return user;
    } catch (e) {
      final message = e is ApiException ? e.message : 'Registration failed: $e';
      setUnauthenticated(errorMessage: message);
      rethrow;
    }
  }

  /// Clears session and transitions state to unauthenticated.
  Future<void> logout() async {
    setAuthenticating(message: 'Signing out...');
    try {
      await authService.logout();
    } finally {
      setUnauthenticated();
    }
  }
}

// State Management Choice:
// Flutter Riverpod was selected because it provides compile-time safe dependency
// injection, enables decoupled business logic without BuildContext coupling, offers
// granular widget rebuilds, and integrates seamlessly with mockable unit tests.

final Provider<ApiClient> apiClientProvider = Provider<ApiClient>((ref) {
  final client = ApiClient(
    onSessionExpired: () {
      ref.read(authStateProvider.notifier).logout();
    },
  );
  ref.onDispose(client.close);
  return client;
});

final Provider<AuthService> authServiceProvider = Provider<AuthService>((ref) {
  final apiClient = ref.watch(apiClientProvider);
  return AuthService(apiClient: apiClient);
});

final StateNotifierProvider<AuthNotifier, AuthState> authStateProvider =
    StateNotifierProvider<AuthNotifier, AuthState>((ref) {
  final authService = ref.watch(authServiceProvider);
  return AuthNotifier(authService);
});

final Provider<User?> currentUserProvider = Provider<User?>((ref) {
  final authState = ref.watch(authStateProvider);
  return authState.user;
});
