import 'dart:convert';

import 'package:ai_trafficos/core/app_config.dart';
import 'package:ai_trafficos/models/user.dart';
import 'package:ai_trafficos/services/api_client.dart';
import 'package:ai_trafficos/services/auth_service.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class FakeSecureStorage implements FlutterSecureStorage {
  final Map<String, String> _data = {};

  @override
  Future<void> write({
    required String key,
    required String? value,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    if (value == null) {
      _data.remove(key);
    } else {
      _data[key] = value;
    }
  }

  @override
  Future<String?> read({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    return _data[key];
  }

  @override
  Future<void> delete({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    _data.remove(key);
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  group('User Model & Roles', () {
    test('admin role permissions are correctly identified', () {
      const user = User(
        id: 1,
        email: 'admin@trafficos.ai',
        fullName: 'Admin User',
        role: User.roleAdmin,
      );

      expect(user.isAdmin, isTrue);
      expect(user.isTrafficOfficer, isFalse);
      expect(user.isAnalyst, isFalse);
      expect(user.isReadOnly, isFalse);
      expect(user.roleDisplay, 'System Administrator');
    });

    test('analyst role is strictly read-only everywhere', () {
      const user = User(
        id: 2,
        email: 'analyst@trafficos.ai',
        fullName: 'Analyst User',
        role: User.roleAnalyst,
      );

      expect(user.isAdmin, isFalse);
      expect(user.isTrafficOfficer, isFalse);
      expect(user.isAnalyst, isTrue);
      expect(user.isReadOnly, isTrue);
      expect(user.roleDisplay, 'Analyst (Read-Only)');
    });

    test('traffic officer role has operational permissions', () {
      const user = User(
        id: 3,
        email: 'officer@trafficos.ai',
        fullName: 'Traffic Officer',
        role: User.roleTrafficOfficer,
      );

      expect(user.isAdmin, isFalse);
      expect(user.isTrafficOfficer, isTrue);
      expect(user.isAnalyst, isFalse);
      expect(user.isReadOnly, isFalse);
      expect(user.roleDisplay, 'Traffic Officer');
    });

    test('User serialization and deserialization works correctly', () {
      final json = {
        'id': 10,
        'email': 'test@trafficos.ai',
        'full_name': 'Test Officer',
        'role_name': 'traffic_officer',
        'is_active': true,
        'created_at': '2026-10-06T12:00:00Z',
      };

      final user = User.fromJson(json);
      expect(user.id, 10);
      expect(user.email, 'test@trafficos.ai');
      expect(user.fullName, 'Test Officer');
      expect(user.role, 'traffic_officer');
      expect(user.isTrafficOfficer, isTrue);

      final exported = user.toJson();
      expect(exported['id'], 10);
      expect(exported['role_name'], 'traffic_officer');
    });
  });

  group('AuthService', () {
    late FakeSecureStorage storage;

    setUp(() {
      storage = FakeSecureStorage();
    });

    test('login succeeds and persists tokens securely', () async {
      final mockClient = MockClient((request) async {
        if (request.url.path == '/api/v1/auth/login') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['email'], 'analyst@trafficos.ai');
          expect(body['password'], 'secretpass');

          return http.Response(
            jsonEncode({
              'access_token': 'mock-access-token',
              'refresh_token': 'mock-refresh-token',
              'token_type': 'bearer',
              'expires_in': 1800,
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        if (request.url.path == '/api/v1/auth/me') {
          expect(request.headers['authorization'], 'Bearer mock-access-token');
          return http.Response(
            jsonEncode({
              'id': 42,
              'email': 'analyst@trafficos.ai',
              'full_name': 'Sarah Connor',
              'role_name': 'analyst',
              'is_active': true,
              'created_at': '2026-10-07T00:00:00Z',
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        return http.Response('Not Found', 404);
      });

      final apiClient = ApiClient(
        baseUrl: 'http://example.com',
        client: mockClient,
        storage: storage,
      );

      final authService = AuthService(
        apiClient: apiClient,
        storage: storage,
      );

      final user = await authService.login('analyst@trafficos.ai', 'secretpass');

      expect(user.id, 42);
      expect(user.email, 'analyst@trafficos.ai');
      expect(user.fullName, 'Sarah Connor');
      expect(user.isAnalyst, isTrue);

      // Verify tokens were persisted in secure storage
      final storedAccess = await storage.read(key: AppConfig.accessTokenKey);
      final storedRefresh = await storage.read(key: AppConfig.refreshTokenKey);
      expect(storedAccess, 'mock-access-token');
      expect(storedRefresh, 'mock-refresh-token');
    });

    test('logout clears secure storage tokens and user cache', () async {
      await storage.write(key: AppConfig.accessTokenKey, value: 'token123');
      await storage.write(key: AppConfig.refreshTokenKey, value: 'refresh123');
      await storage.write(key: AppConfig.userCacheKey, value: '{}');

      final authService = AuthService(
        apiClient: ApiClient(baseUrl: 'http://example.com', storage: storage),
        storage: storage,
      );

      await authService.logout();

      expect(await storage.read(key: AppConfig.accessTokenKey), isNull);
      expect(await storage.read(key: AppConfig.refreshTokenKey), isNull);
      expect(await storage.read(key: AppConfig.userCacheKey), isNull);
    });

    test('login with invalid credentials raises typed ApiException', () async {
      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode({'detail': 'Invalid email or password'}),
          401,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = ApiClient(
        baseUrl: 'http://example.com',
        client: mockClient,
        storage: storage,
      );

      final authService = AuthService(
        apiClient: apiClient,
        storage: storage,
      );

      expect(
        () => authService.login('bad@trafficos.ai', 'wrong'),
        throwsA(
          isA<ApiException>()
              .having((e) => e.statusCode, 'statusCode', 401)
              .having((e) => e.message, 'message', 'Invalid email or password'),
        ),
      );
    });
  });

  group('ApiClient Token Refresh & Retry', () {
    test('auto-refreshes token on 401 and retries original request', () async {
      final storage = FakeSecureStorage();
      await storage.write(key: AppConfig.accessTokenKey, value: 'expired-token');
      await storage.write(key: AppConfig.refreshTokenKey, value: 'valid-refresh-token');

      var attempts = 0;
      final mockClient = MockClient((request) async {
        if (request.url.path == '/api/v1/auth/me') {
          attempts++;
          if (attempts == 1) {
            expect(request.headers['authorization'], 'Bearer expired-token');
            return http.Response(
              jsonEncode({'detail': 'Token expired'}),
              401,
              headers: {'content-type': 'application/json'},
            );
          } else {
            expect(request.headers['authorization'], 'Bearer fresh-access-token');
            return http.Response(
              jsonEncode({
                'id': 1,
                'email': 'refreshed@trafficos.ai',
                'full_name': 'Refreshed User',
                'role_name': 'traffic_officer',
                'is_active': true,
              }),
              200,
              headers: {'content-type': 'application/json'},
            );
          }
        }

        if (request.url.path == '/api/v1/auth/refresh') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['refresh_token'], 'valid-refresh-token');

          return http.Response(
            jsonEncode({
              'access_token': 'fresh-access-token',
              'refresh_token': 'fresh-refresh-token',
              'token_type': 'bearer',
              'expires_in': 1800,
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        return http.Response('Not Found', 404);
      });

      final apiClient = ApiClient(
        baseUrl: 'http://example.com',
        client: mockClient,
        storage: storage,
      );

      final dynamic data = await apiClient.get('/auth/me');
      expect(data, isA<Map<String, dynamic>>());
      expect(data['email'], 'refreshed@trafficos.ai');
      expect(attempts, 2);

      // Verify new tokens saved
      expect(await storage.read(key: AppConfig.accessTokenKey), 'fresh-access-token');
      expect(await storage.read(key: AppConfig.refreshTokenKey), 'fresh-refresh-token');
    });
  });
}
