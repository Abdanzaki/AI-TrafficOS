import 'dart:convert';
import 'package:ai_trafficos/services/api_client.dart';
import 'package:ai_trafficos/services/audit_service.dart';
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
  group('AuditService REST Client & RBAC Tests', () {
    test('getAuditLogs queries GET /audit-logs and parses fields correctly', () async {
      final mockClient = MockClient((request) async {
        expect(request.method, 'GET');
        expect(request.url.path, '/api/v1/audit-logs');
        expect(request.url.queryParameters['action'], 'user.created');

        return http.Response(
          jsonEncode({
            'items': [
              {
                'id': 501,
                'action': 'user.created',
                'actor_email': 'admin@trafficos.city',
                'entity': 'user',
                'created_at': '2026-10-07T14:30:00Z',
                'details': {
                  'email': 'officer@trafficos.city',
                  'role': 'traffic_officer',
                },
                'ip_address': '127.0.0.1',
              },
            ],
            'total': 1,
            'page': 1,
            'per_page': 20,
            'pages': 1,
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);
      final service = AuditService(apiClient: apiClient);

      final paged = await service.getAuditLogs(action: 'user.created');

      expect(paged.total, 1);
      expect(paged.items.length, 1);

      final entry = paged.items.first;
      expect(entry.id, 501);
      expect(entry.action, 'user.created');
      expect(entry.actorEmail, 'admin@trafficos.city');
      expect(entry.entity, 'user');
      expect(entry.ipAddress, '127.0.0.1');
      expect(entry.details['role'], 'traffic_officer');
    });

    test('getAuditLogs maps 403 Forbidden to typed admin restriction ApiException', () async {
      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'detail': 'Forbidden: Insufficient privileges to view audit trail',
          }),
          403,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);
      final service = AuditService(apiClient: apiClient);

      expect(
        () => service.getAuditLogs(),
        throwsA(
          isA<ApiException>()
              .having((e) => e.statusCode, 'statusCode', 403)
              .having(
                (e) => e.message,
                'message',
                contains('Only system administrators may view the operational audit log'),
              ),
        ),
      );
    });

    test('getAuditLogs correctly forwards date filters to query parameters', () async {
      final fromDate = DateTime.utc(2026, 10, 1);
      final toDate = DateTime.utc(2026, 10, 7);

      final mockClient = MockClient((request) async {
        expect(request.url.queryParameters['from'], fromDate.toIso8601String());
        expect(request.url.queryParameters['to'], toDate.toIso8601String());

        return http.Response(
          jsonEncode({'items': [], 'total': 0, 'page': 1, 'per_page': 20, 'pages': 1}),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);
      final service = AuditService(apiClient: apiClient);

      final res = await service.getAuditLogs(from: fromDate, to: toDate);
      expect(res.total, 0);
    });
  });
}
