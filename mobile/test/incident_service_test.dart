import 'dart:convert';
import 'package:ai_trafficos/models/incident.dart';
import 'package:ai_trafficos/services/api_client.dart';
import 'package:ai_trafficos/services/incident_service.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class FakeSecureStorage implements FlutterSecureStorage {
  final Map<String, String> _data = {
    'ai_trafficos_access_token': 'fake_token',
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
  group('Incident Model Status Transition Logic', () {
    test('IncidentStatus canTransitionTo validates standard lifecycle forward flow', () {
      expect(IncidentStatus.reported.canTransitionTo(IncidentStatus.acknowledged), isTrue);
      expect(IncidentStatus.reported.canTransitionTo(IncidentStatus.resolved), isTrue);
      expect(IncidentStatus.acknowledged.canTransitionTo(IncidentStatus.resolved), isTrue);
      expect(IncidentStatus.acknowledged.canTransitionTo(IncidentStatus.reported), isFalse);
    });

    test('IncidentStatus prevents reopening from resolved to reported', () {
      expect(IncidentStatus.resolved.canTransitionTo(IncidentStatus.reported), isFalse);
      expect(IncidentStatus.resolved.canTransitionTo(IncidentStatus.acknowledged), isFalse);
      expect(IncidentStatus.resolved.canTransitionTo(IncidentStatus.resolved), isTrue);
    });

    test('Incident.isValidTransition correctly checks string representations', () {
      expect(Incident.isValidTransition('reported', 'acknowledged'), isTrue);
      expect(Incident.isValidTransition('reported', 'resolved'), isTrue);
      expect(Incident.isValidTransition('acknowledged', 'resolved'), isTrue);
      expect(Incident.isValidTransition('resolved', 'reported'), isFalse);
    });
  });

  group('IncidentService REST Client Tests', () {
    test('getIncidents queries GET /incidents with filter parameters and parses items', () async {
      final mockClient = MockClient((request) async {
        expect(request.method, 'GET');
        expect(request.url.path, '/api/v1/incidents');
        expect(request.url.queryParameters['status'], 'reported');
        expect(request.url.queryParameters['severity'], 'high');

        return http.Response(
          jsonEncode({
            'items': [
              {
                'id': 101,
                'intersection_id': 5,
                'severity': 'high',
                'status': 'reported',
                'description': 'Vehicle collision in northbound lane',
                'created_at': '2026-10-07T12:00:00Z',
                'updated_at': '2026-10-07T12:00:00Z',
              }
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

      final service = IncidentService(apiClient: createTestClient(mockClient));
      final paged = await service.getIncidents(
        status: 'reported',
        severity: 'high',
      );

      expect(paged.total, 1);
      expect(paged.items.length, 1);
      final item = paged.items.first;
      expect(item.id, 101);
      expect(item.severity, 'high');
      expect(item.status, 'reported');
      expect(item.intersectionId, 5);
      expect(item.isActive, isTrue);
    });

    test('createIncident sends POST /incidents with full payload and parses response', () async {
      final mockClient = MockClient((request) async {
        expect(request.method, 'POST');
        expect(request.url.path, '/api/v1/incidents');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['severity'], 'critical');
        expect(body['status'], 'reported');
        expect(body['intersection_id'], 7);
        expect(body['description'], contains('Multi-car pileup'));

        return http.Response(
          jsonEncode({
            'id': 102,
            'intersection_id': 7,
            'severity': 'critical',
            'status': 'reported',
            'description': 'Multi-car pileup: Major lane blockage',
            'created_at': '2026-10-07T13:00:00Z',
            'updated_at': '2026-10-07T13:00:00Z',
          }),
          201,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = IncidentService(apiClient: createTestClient(mockClient));
      final created = await service.createIncident(
        title: 'Multi-car pileup',
        description: 'Major lane blockage',
        severity: 'critical',
        intersectionId: 7,
      );

      expect(created.id, 102);
      expect(created.severity, 'critical');
      expect(created.intersectionId, 7);
    });

    test('updateIncidentStatus performs valid transitions via PATCH /incidents/{id}', () async {
      final mockClient = MockClient((request) async {
        expect(request.method, 'PATCH');
        expect(request.url.path, '/api/v1/incidents/101');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['status'], 'acknowledged');

        return http.Response(
          jsonEncode({
            'id': 101,
            'intersection_id': 5,
            'severity': 'high',
            'status': 'acknowledged',
            'description': 'Vehicle collision in northbound lane',
            'created_at': '2026-10-07T12:00:00Z',
            'updated_at': '2026-10-07T12:30:00Z',
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = IncidentService(apiClient: createTestClient(mockClient));
      final updated = await service.updateIncidentStatus(
        id: 101,
        status: 'acknowledged',
        currentStatus: 'reported',
      );

      expect(updated.id, 101);
      expect(updated.status, 'acknowledged');
    });

    test('updateIncidentStatus blocks resolved -> reported client-side transition', () async {
      final mockClient = MockClient((request) async {
        fail('HTTP request should not have been dispatched for invalid transition');
      });

      final service = IncidentService(apiClient: createTestClient(mockClient));

      expect(
        () => service.updateIncidentStatus(
          id: 101,
          status: 'reported',
          currentStatus: 'resolved',
        ),
        throwsA(isA<ApiException>().having(
          (e) => e.statusCode,
          'statusCode',
          400,
        )),
      );
    });

    test('maps 403 Forbidden to typed ApiException when unauthorized role performs write', () async {
      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'detail': 'Forbidden: Operator lacks permission to create incidents',
          }),
          403,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = IncidentService(apiClient: createTestClient(mockClient));

      expect(
        () => service.createIncident(
          severity: 'low',
          description: 'Unauthorized write attempt',
        ),
        throwsA(isA<ApiException>().having(
          (e) => e.statusCode,
          'statusCode',
          403,
        )),
      );
    });
  });
}
