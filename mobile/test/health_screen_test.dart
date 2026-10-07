import 'dart:convert';
import 'package:ai_trafficos/models/user.dart';
import 'package:ai_trafficos/screens/health_screen.dart';
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
  group('HealthScreen Diagnostics & Status Mapping Widget Tests', () {
    testWidgets('renders backend status, measured latency, and active AI subsystem status', (tester) async {
      final mockClient = MockClient((request) async {
        if (request.url.path.endsWith('/health')) {
          return http.Response(
            jsonEncode({
              'status': 'ok',
              'service': 'ai-trafficos',
              'version': '0.1.0',
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        if (request.url.path.endsWith('/forecasting/models/latest')) {
          return http.Response(
            jsonEncode({
              'id': 1,
              'name': 'traffic_forecaster',
              'version': '0.1.0',
              'in_database': true,
              'in_filesystem': true,
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        if (request.url.path.endsWith('/control/decisions')) {
          return http.Response(
            jsonEncode({
              'items': [],
              'total': 42,
              'page': 1,
              'per_page': 1,
              'pages': 42,
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        return http.Response('{}', 200, headers: {'content-type': 'application/json'});
      });

      final apiClient = createTestClient(mockClient);

      const user = User(
        id: 1,
        email: 'admin@trafficos.city',
        fullName: 'Operator Jane',
        role: User.roleAdmin,
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(apiClient),
            currentUserProvider.overrideWith((ref) => user),
          ],
          child: const MaterialApp(
            home: HealthScreen(),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('System Health'), findsOneWidget);
      expect(find.text('FastAPI Core Backend'), findsOneWidget);
      expect(find.text('0.1.0'), findsWidgets);
      expect(find.text('OK'), findsOneWidget);
      expect(find.text('ONLINE'), findsOneWidget);
      expect(find.textContaining('ms'), findsWidgets);
      expect(find.text('Traffic Forecasting ML'), findsOneWidget);
      expect(find.text('Supervisory Control Engine'), findsOneWidget);
      expect(find.text('42 policy decisions logged'), findsOneWidget);
    });

    testWidgets('honestly maps unregistered and unknown AI subsystem statuses', (tester) async {
      final mockClient = MockClient((request) async {
        if (request.url.path.endsWith('/health')) {
          return http.Response(
            jsonEncode({
              'status': 'ok',
              'service': 'ai-trafficos',
              'version': '0.1.0',
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        if (request.url.path.endsWith('/forecasting/models/latest')) {
          return http.Response(
            jsonEncode({'detail': 'No forecasting models registered in system.'}),
            404,
            headers: {'content-type': 'application/json'},
          );
        }

        if (request.url.path.endsWith('/control/decisions')) {
          return http.Response('Internal error', 500);
        }

        return http.Response('{}', 200);
      });

      final apiClient = createTestClient(mockClient);

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(apiClient),
          ],
          child: const MaterialApp(
            home: HealthScreen(),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('UNREGISTERED'), findsOneWidget);
      expect(find.text('No model trained'), findsOneWidget);
      expect(find.text('UNKNOWN'), findsOneWidget);
    });
  });
}
