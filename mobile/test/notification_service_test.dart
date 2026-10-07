import 'dart:convert';
import 'package:ai_trafficos/services/api_client.dart';
import 'package:ai_trafficos/services/notification_service.dart';
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
  group('NotificationService REST Client Tests', () {
    test('getMyNotifications queries GET /notifications/me and parses items correctly', () async {
      final mockClient = MockClient((request) async {
        expect(request.method, 'GET');
        expect(request.url.path, '/api/v1/notifications/me');
        expect(request.url.queryParameters['is_read'], 'false');

        return http.Response(
          jsonEncode({
            'items': [
              {
                'id': 101,
                'title': 'Emergency Corridor Active',
                'message': 'Ambulance green wave initiated on Corridor 4',
                'severity': 'critical',
                'is_read': false,
                'created_at': '2026-10-07T12:00:00Z',
                'entity_type': 'corridor',
                'entity_id': 4,
              },
              {
                'id': 102,
                'title': 'Traffic Flow Warning',
                'body': 'Heavy congestion detected near Market & 4th',
                'type': 'warning',
                'is_read': false,
                'created_at': '2026-10-07T12:05:00Z',
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
      final service = NotificationService(apiClient: apiClient);

      final result = await service.getMyNotifications(isRead: false);

      expect(result.total, 2);
      expect(result.items.length, 2);

      final first = result.items[0];
      expect(first.id, 101);
      expect(first.title, 'Emergency Corridor Active');
      expect(first.body, 'Ambulance green wave initiated on Corridor 4');
      expect(first.type, 'critical');
      expect(first.isRead, isFalse);
      expect(first.entityType, 'corridor');
      expect(first.entityId, 4);

      final second = result.items[1];
      expect(second.id, 102);
      expect(second.title, 'Traffic Flow Warning');
      expect(second.body, 'Heavy congestion detected near Market & 4th');
      expect(second.type, 'warning');
      expect(second.isRead, isFalse);
    });

    test('markAsRead performs PATCH /notifications/{id}/read and parses updated response', () async {
      final mockClient = MockClient((request) async {
        expect(request.method, 'PATCH');
        expect(request.url.path, '/api/v1/notifications/101/read');

        return http.Response(
          jsonEncode({
            'id': 101,
            'title': 'Emergency Corridor Active',
            'message': 'Ambulance green wave initiated on Corridor 4',
            'severity': 'critical',
            'is_read': true,
            'created_at': '2026-10-07T12:00:00Z',
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);
      final service = NotificationService(apiClient: apiClient);

      final updated = await service.markAsRead(101);

      expect(updated.id, 101);
      expect(updated.isRead, isTrue);
    });

    test('unreadCount queries GET /notifications/me?is_read=false and returns count', () async {
      final mockClient = MockClient((request) async {
        expect(request.method, 'GET');
        expect(request.url.path, '/api/v1/notifications/me');
        expect(request.url.queryParameters['is_read'], 'false');

        return http.Response(
          jsonEncode({
            'items': [],
            'total': 5,
            'page': 1,
            'per_page': 1,
            'pages': 5,
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);
      final service = NotificationService(apiClient: apiClient);

      final count = await service.unreadCount();

      expect(count, 5);
    });
  });
}
