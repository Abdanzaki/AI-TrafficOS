import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

import '../core/app_config.dart';
import '../models/health_status.dart';

/// Sealed result type for legacy and direct API operations.
sealed class ApiResult<T> {
  const ApiResult();

  bool get isSuccess => this is ApiSuccess<T>;
  bool get isFailure => this is ApiFailure<T>;

  T? get dataOrNull => switch (this) {
        ApiSuccess<T>(data: final d) => d,
        ApiFailure<T>() => null,
      };

  String? get errorOrNull => switch (this) {
        ApiSuccess<T>() => null,
        ApiFailure<T>(error: final err) => err,
      };
}

/// Represents a successful API response holding [data].
final class ApiSuccess<T> extends ApiResult<T> {
  const ApiSuccess(this.data);
  final T data;
}

/// Represents a failed API response holding an [error] description
/// and optional [statusCode].
final class ApiFailure<T> extends ApiResult<T> {
  const ApiFailure(this.error, {this.statusCode});
  final String error;
  final int? statusCode;
}

/// Strongly typed exception thrown on API or network failures.
class ApiException implements Exception {
  const ApiException({
    required this.message,
    this.statusCode,
    this.details,
    this.isNetworkError = false,
  });

  final String message;
  final int? statusCode;
  final dynamic details;
  final bool isNetworkError;

  bool get isUnauthorized => statusCode == 401;
  bool get isForbidden => statusCode == 403;
  bool get isNotFound => statusCode == 404;

  @override
  String toString() {
    if (statusCode != null) {
      return 'ApiException(HTTP $statusCode): $message';
    }
    return 'ApiException: $message';
  }
}

/// Robust HTTP API client for AI TrafficOS backend communications.
///
/// Features:
/// - Configurable base URL defaulting to [AppConfig.apiBaseUrl]
/// - Automatic injection of Bearer access tokens on authenticated endpoints
/// - Single-flight thread-safe token refresh on HTTP 401 responses
/// - Automatic retry of original request after successful token refresh
/// - Structured [ApiException] translation with FastAPI validation details
/// - Standard pagination helpers (`page`, `per_page`)
/// - Strict security: NEVER logs tokens to console or storage
class ApiClient {
  ApiClient({
    String? baseUrl,
    http.Client? client,
    FlutterSecureStorage? storage,
    this.onSessionExpired,
  })  : _rawBaseUrl = baseUrl ?? AppConfig.apiBaseUrl,
        _client = client ?? http.Client(),
        _ownsClient = client == null,
        _storage = storage ?? const FlutterSecureStorage();

  final String _rawBaseUrl;
  final http.Client _client;
  final bool _ownsClient;
  final FlutterSecureStorage _storage;

  /// Optional callback invoked when a refresh token expires or is rejected.
  final VoidCallback? onSessionExpired;

  /// Default backend URL from application configuration.
  static const String defaultBaseUrl = AppConfig.apiBaseUrl;

  /// Request timeout duration.
  static const Duration requestTimeout = AppConfig.requestTimeout;

  /// Single-flight lock preventing redundant simultaneous token refresh calls.
  Completer<bool>? _refreshCompleter;

  /// Normalized base URL ensuring `/api/v1` prefix is standard.
  String get baseUrl => _normalizeBaseUrl(_rawBaseUrl);

  static String _normalizeBaseUrl(String url) {
    var trimmed = url.trim();
    while (trimmed.endsWith('/')) {
      trimmed = trimmed.substring(0, trimmed.length - 1);
    }
    if (!trimmed.endsWith('/api/v1')) {
      trimmed = '$trimmed/api/v1';
    }
    return trimmed;
  }

  /// Builds a fully-qualified [Uri] handling the `/api/v1` prefix and query parameters.
  Uri _buildUri(String path, [Map<String, dynamic>? queryParameters]) {
    var cleanPath = path.trim();
    if (!cleanPath.startsWith('/')) {
      cleanPath = '/$cleanPath';
    }

    // Deduplicate /api/v1 if both baseUrl and path contain it
    if (baseUrl.endsWith('/api/v1') && cleanPath.startsWith('/api/v1/')) {
      cleanPath = cleanPath.substring('/api/v1'.length);
    }

    final baseUri = Uri.parse(baseUrl);
    final fullPath = '${baseUri.path}$cleanPath'.replaceAll('//', '/');

    final queryMap = <String, String>{};
    if (baseUri.queryParameters.isNotEmpty) {
      queryMap.addAll(baseUri.queryParameters);
    }
    if (queryParameters != null) {
      queryParameters.forEach((key, value) {
        if (value != null) {
          queryMap[key] = value.toString();
        }
      });
    }

    return baseUri.replace(
      path: fullPath,
      queryParameters: queryMap.isEmpty ? null : queryMap,
    );
  }

  /// Refreshes the access token using a stored refresh token in a single-flight operation.
  ///
  /// Multiple parallel requests failing with 401 will await the single active refresh
  /// rather than triggering duplicate refresh requests.
  Future<bool> _refreshTokenSingleFlight() async {
    if (_refreshCompleter != null) {
      return _refreshCompleter!.future;
    }

    final completer = Completer<bool>();
    _refreshCompleter = completer;

    try {
      final refreshToken = await _storage.read(key: AppConfig.refreshTokenKey);
      if (refreshToken == null || refreshToken.trim().isEmpty) {
        completer.complete(false);
        return false;
      }

      final refreshUri = _buildUri('/auth/refresh');
      final response = await _client.post(
        refreshUri,
        headers: const {
          'Accept': 'application/json',
          'Content-Type': 'application/json',
          'User-Agent': 'AI-TrafficOS-Mobile/Phase8',
        },
        body: jsonEncode({'refresh_token': refreshToken.trim()}),
      ).timeout(requestTimeout);

      if (response.statusCode >= 200 && response.statusCode < 300) {
        final dynamic decoded = jsonDecode(response.body);
        if (decoded is Map<String, dynamic>) {
          final newAccessToken = decoded['access_token'] as String?;
          final newRefreshToken = decoded['refresh_token'] as String?;

          if (newAccessToken != null && newRefreshToken != null) {
            await _storage.write(
              key: AppConfig.accessTokenKey,
              value: newAccessToken,
            );
            await _storage.write(
              key: AppConfig.refreshTokenKey,
              value: newRefreshToken,
            );
            completer.complete(true);
            return true;
          }
        }
      }

      // Refresh failed or unauthorized: wipe stored tokens and fire callback
      await _storage.delete(key: AppConfig.accessTokenKey);
      await _storage.delete(key: AppConfig.refreshTokenKey);
      await _storage.delete(key: AppConfig.userCacheKey);
      onSessionExpired?.call();
      completer.complete(false);
      return false;
    } catch (_) {
      completer.complete(false);
      return false;
    } finally {
      _refreshCompleter = null;
    }
  }

  /// Executes an HTTP request with error parsing and automatic 401 retry.
  Future<http.Response> _sendRequest(
    String method,
    String path, {
    Object? body,
    Map<String, dynamic>? queryParameters,
    int? page,
    int? perPage,
    bool requiresAuth = true,
    bool isRetry = false,
  }) async {
    final queryParams = <String, dynamic>{};
    if (queryParameters != null) {
      queryParams.addAll(queryParameters);
    }
    if (page != null) {
      queryParams['page'] = page;
    }
    if (perPage != null) {
      queryParams['per_page'] = perPage;
    }

    final uri = _buildUri(path, queryParams);

    Future<http.Response> execute(String? token) async {
      final headers = <String, String>{
        'Accept': 'application/json',
        'User-Agent': 'AI-TrafficOS-Mobile/Phase8',
      };
      if (body != null) {
        headers['Content-Type'] = 'application/json';
      }
      if (requiresAuth && token != null && token.isNotEmpty) {
        headers['Authorization'] = 'Bearer $token';
      }

      final encodedBody = body != null ? jsonEncode(body) : null;

      switch (method.toUpperCase()) {
        case 'GET':
          return _client.get(uri, headers: headers);
        case 'POST':
          return _client.post(uri, headers: headers, body: encodedBody);
        case 'PUT':
          return _client.put(uri, headers: headers, body: encodedBody);
        case 'PATCH':
          return _client.patch(uri, headers: headers, body: encodedBody);
        case 'DELETE':
          return _client.delete(uri, headers: headers, body: encodedBody);
        default:
          throw ApiException(message: 'Unsupported HTTP method: $method');
      }
    }

    String? accessToken;
    if (requiresAuth) {
      accessToken = await _storage.read(key: AppConfig.accessTokenKey);
    }

    http.Response response;
    try {
      response = await execute(accessToken).timeout(requestTimeout);
    } on TimeoutException {
      throw ApiException(
        statusCode: 408,
        message:
            'Connection timed out after ${requestTimeout.inSeconds}s while reaching ${uri.host}',
        isNetworkError: true,
      );
    } on SocketException catch (e) {
      throw ApiException(
        message: 'Network unreachable or host offline: ${e.message}',
        isNetworkError: true,
      );
    } on http.ClientException catch (e) {
      throw ApiException(
        message: 'Connection error: ${e.message}',
        isNetworkError: true,
      );
    } on HandshakeException catch (e) {
      throw ApiException(
        message: 'TLS handshake failed: ${e.message}',
        isNetworkError: true,
      );
    } catch (e) {
      if (e is ApiException) rethrow;
      throw ApiException(
        message: 'Unexpected network error: $e',
        isNetworkError: true,
      );
    }

    // Auto-refresh token on 401 if requiresAuth and this isn't already a retry
    if (response.statusCode == 401 && requiresAuth && !isRetry) {
      final refreshed = await _refreshTokenSingleFlight();
      if (refreshed) {
        final newAccessToken =
            await _storage.read(key: AppConfig.accessTokenKey);
        try {
          response = await execute(newAccessToken).timeout(requestTimeout);
        } on TimeoutException {
          throw const ApiException(
            statusCode: 408,
            message: 'Connection timed out on retry',
            isNetworkError: true,
          );
        } catch (e) {
          if (e is ApiException) rethrow;
          throw ApiException(
            message: 'Retry connection failed: $e',
            isNetworkError: true,
          );
        }
      } else {
        throw const ApiException(
          statusCode: 401,
          message: 'Session expired. Please log in again.',
        );
      }
    }

    return response;
  }

  /// Parses JSON response bodies or raises typed [ApiException].
  dynamic _handleResponse(http.Response response) {
    final code = response.statusCode;
    if (code >= 200 && code < 300) {
      if (response.body.isEmpty) {
        return null;
      }
      try {
        return jsonDecode(response.body);
      } on FormatException catch (e) {
        throw ApiException(
          statusCode: code,
          message: 'Invalid JSON response from server: ${e.message}',
        );
      }
    }

    // Parse FastAPI or Starlette error payload
    String errorMessage = 'Request failed with status $code';
    dynamic errorDetails;

    if (response.body.isNotEmpty) {
      try {
        final dynamic decoded = jsonDecode(response.body);
        if (decoded is Map<String, dynamic>) {
          errorDetails = decoded;
          if (decoded.containsKey('detail')) {
            final detail = decoded['detail'];
            if (detail is String) {
              errorMessage = detail;
            } else if (detail is List) {
              errorMessage = detail
                  .map((item) => item is Map
                      ? (item['msg'] ?? item.toString())
                      : item.toString())
                  .join('; ');
            }
          } else if (decoded.containsKey('message')) {
            errorMessage = decoded['message'].toString();
          }
        }
      } catch (_) {
        if (response.body.length < 200) {
          errorMessage = response.body;
        }
      }
    }

    throw ApiException(
      statusCode: code,
      message: errorMessage,
      details: errorDetails,
    );
  }

  /// Sends a GET request and returns decoded JSON.
  Future<dynamic> get(
    String path, {
    Map<String, dynamic>? queryParameters,
    int? page,
    int? perPage,
    bool requiresAuth = true,
  }) async {
    final response = await _sendRequest(
      'GET',
      path,
      queryParameters: queryParameters,
      page: page,
      perPage: perPage,
      requiresAuth: requiresAuth,
    );
    return _handleResponse(response);
  }

  /// Sends a POST request and returns decoded JSON.
  Future<dynamic> post(
    String path, {
    Object? body,
    Map<String, dynamic>? queryParameters,
    bool requiresAuth = true,
  }) async {
    final response = await _sendRequest(
      'POST',
      path,
      body: body,
      queryParameters: queryParameters,
      requiresAuth: requiresAuth,
    );
    return _handleResponse(response);
  }

  /// Sends a PUT request and returns decoded JSON.
  Future<dynamic> put(
    String path, {
    Object? body,
    Map<String, dynamic>? queryParameters,
    bool requiresAuth = true,
  }) async {
    final response = await _sendRequest(
      'PUT',
      path,
      body: body,
      queryParameters: queryParameters,
      requiresAuth: requiresAuth,
    );
    return _handleResponse(response);
  }

  /// Sends a PATCH request and returns decoded JSON.
  Future<dynamic> patch(
    String path, {
    Object? body,
    Map<String, dynamic>? queryParameters,
    bool requiresAuth = true,
  }) async {
    final response = await _sendRequest(
      'PATCH',
      path,
      body: body,
      queryParameters: queryParameters,
      requiresAuth: requiresAuth,
    );
    return _handleResponse(response);
  }

  /// Sends a DELETE request and returns decoded JSON.
  Future<dynamic> delete(
    String path, {
    Map<String, dynamic>? queryParameters,
    bool requiresAuth = true,
  }) async {
    final response = await _sendRequest(
      'DELETE',
      path,
      queryParameters: queryParameters,
      requiresAuth: requiresAuth,
    );
    return _handleResponse(response);
  }

  /// Hits `GET /health` with timeout handling and returns legacy [ApiResult].
  ///
  /// Never throws an unhandled exception to the caller.
  Future<ApiResult<HealthStatus>> getHealth() async {
    final uri = _buildUri('/health');
    debugPrint('ApiClient: Querying health check at $uri');

    try {
      final response = await _client.get(
        uri,
        headers: const {
          'Accept': 'application/json',
          'User-Agent': 'AI-TrafficOS-Mobile/Phase8',
        },
      ).timeout(requestTimeout);

      if (response.statusCode >= 200 && response.statusCode < 300) {
        try {
          final dynamic decoded = jsonDecode(response.body);
          if (decoded is Map<String, dynamic>) {
            final health = HealthStatus.fromJson(decoded);
            return ApiSuccess(health);
          } else {
            return const ApiFailure('Invalid response: Expected JSON object');
          }
        } on FormatException catch (e) {
          return ApiFailure('Invalid JSON response: ${e.message}');
        }
      } else {
        return ApiFailure(
          'Backend returned HTTP ${response.statusCode}: ${response.reasonPhrase ?? "Error"}',
          statusCode: response.statusCode,
        );
      }
    } on TimeoutException {
      return ApiFailure(
        'Connection timed out after ${requestTimeout.inSeconds}s while reaching $baseUrl',
      );
    } on SocketException catch (e) {
      return ApiFailure(
        'Network unreachable or host offline: ${e.message}',
      );
    } on http.ClientException catch (e) {
      return ApiFailure(
        'Client connection error: ${e.message}',
      );
    } on HandshakeException catch (e) {
      return ApiFailure(
        'TLS handshake failed: ${e.message}',
      );
    } catch (e) {
      return ApiFailure(
        'Unexpected error connecting to backend: $e',
      );
    }
  }

  /// Closes client resources if this instance owns the underlying http.Client.
  void close() {
    if (_ownsClient) {
      _client.close();
    }
  }
}
