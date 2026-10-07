import 'package:flutter/foundation.dart';

/// Application configuration and environment constants for AI TrafficOS.
class AppConfig {
  AppConfig._();

  /// Secure storage key for the JWT Bearer access token.
  static const String accessTokenKey = 'aitrafficos_access_token';

  /// Secure storage key for the JWT refresh token.
  static const String refreshTokenKey = 'aitrafficos_refresh_token';

  /// Secure storage key for the locally cached user profile JSON.
  static const String userCacheKey = 'aitrafficos_cached_user';

  /// Base URL for backend communications.
  ///
  /// Network routing note:
  /// - Android emulator routes the host loopback through `http://10.0.2.2:8000/api/v1`.
  /// - Web, Desktop, and iOS simulator connect directly to `http://localhost:8000/api/v1`.
  ///
  /// You can override this at build or run time using:
  /// `--dart-define=API_URL=https://your-traffic-api.domain.com/api/v1`
  static const String apiBaseUrl = String.fromEnvironment(
    'API_URL',
    defaultValue: kIsWeb
        ? 'http://localhost:8000/api/v1'
        : 'http://10.0.2.2:8000/api/v1',
  );

  /// API request timeout duration.
  static const Duration requestTimeout = Duration(seconds: 10);
}
