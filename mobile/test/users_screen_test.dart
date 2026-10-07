import 'dart:convert';
import 'package:ai_trafficos/models/user.dart';
import 'package:ai_trafficos/screens/users_screen.dart';
import 'package:ai_trafficos/services/api_client.dart';
import 'package:ai_trafficos/services/auth_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class FakeSecureStorage implements FlutterSecureStorage {
  final Map<String, String> _data = {
    'aitrafficos_access_token': 'fake_token',
  };

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
  }) async =>
      _data[key];

  @override
  Future<void> delete({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async =>
      _data.remove(key);

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

ApiClient createTestClient(http.Client client) {
  return ApiClient(
    baseUrl: 'http://test',
    client: client,
    storage: FakeSecureStorage(),
  );
}

void main() {
  group('UsersScreen Widget & Role Guard Tests', () {
    testWidgets('blocks non-admin users and displays role restriction fallback', (tester) async {
      final mockClient = MockClient((request) async => http.Response('[]', 200));
      final apiClient = createTestClient(mockClient);

      const nonAdminUser = User(
        id: 2,
        email: 'officer@trafficos.city',
        fullName: 'Traffic Officer',
        role: User.roleTrafficOfficer,
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(apiClient),
            currentUserProvider.overrideWith((ref) => nonAdminUser),
          ],
          child: const MaterialApp(
            home: UsersScreen(),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('Access Restricted'), findsOneWidget);
      expect(
        find.textContaining('User administration and RBAC policy management requires System Administrator credentials'),
        findsOneWidget,
      );
      expect(find.byType(FloatingActionButton), findsNothing);
    });

    testWidgets('renders user list and FAB when accessed by system administrator', (tester) async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/users');

        return http.Response(
          jsonEncode({
            'items': [
              {
                'id': 1,
                'email': 'admin@trafficos.city',
                'full_name': 'Chief Administrator',
                'role_name': 'admin',
                'is_active': true,
                'created_at': '2026-01-01T00:00:00Z',
              },
              {
                'id': 2,
                'email': 'analyst@trafficos.city',
                'full_name': 'Senior Analyst',
                'role_name': 'analyst',
                'is_active': true,
                'created_at': '2026-01-02T00:00:00Z',
              },
            ],
            'total': 2,
            'page': 1,
            'per_page': 20,
            'pages': 1,
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);

      const adminUser = User(
        id: 1,
        email: 'admin@trafficos.city',
        fullName: 'Chief Administrator',
        role: User.roleAdmin,
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(apiClient),
            currentUserProvider.overrideWith((ref) => adminUser),
          ],
          child: const MaterialApp(
            home: UsersScreen(),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('User Management'), findsOneWidget);
      expect(find.text('Chief Administrator'), findsOneWidget);
      expect(find.text('admin@trafficos.city'), findsOneWidget);
      expect(find.text('Senior Analyst'), findsOneWidget);
      expect(find.text('analyst@trafficos.city'), findsOneWidget);
      expect(find.byType(FloatingActionButton), findsOneWidget);
    });

    testWidgets('renders empty state when no operators are returned', (tester) async {
      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'items': [],
            'total': 0,
            'page': 1,
            'per_page': 20,
            'pages': 1,
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);

      const adminUser = User(
        id: 1,
        email: 'admin@trafficos.city',
        fullName: 'Chief Administrator',
        role: User.roleAdmin,
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(apiClient),
            currentUserProvider.overrideWith((ref) => adminUser),
          ],
          child: const MaterialApp(
            home: UsersScreen(),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('No User Accounts Found'), findsOneWidget);
    });
  });
}
