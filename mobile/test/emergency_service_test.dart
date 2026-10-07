import 'dart:convert';
import 'package:ai_trafficos/services/api_client.dart';
import 'package:ai_trafficos/services/emergency_service.dart';
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
  group('EmergencyService REST Client Tests', () {
    test('getEmergencyEvents queries GET /emergency-events and parses items correctly', () async {
      final mockClient = MockClient((request) async {
        expect(request.method, 'GET');
        expect(request.url.path, '/api/v1/emergency-events');
        expect(request.url.queryParameters['status'], 'active');
        expect(request.url.queryParameters['priority'], '1');

        return http.Response(
          jsonEncode({
            'items': [
              {
                'id': 201,
                'vehicle_type': 'ambulance',
                'priority': 1,
                'status': 'active',
                'intersection_id': 3,
                'detected_at': '2026-10-07T14:00:00Z',
                'created_at': '2026-10-07T14:00:00Z',
                'updated_at': '2026-10-07T14:00:00Z',
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

      final service = EmergencyService(apiClient: createTestClient(mockClient));
      final paged = await service.getEmergencyEvents(status: 'active', priority: 1);

      expect(paged.total, 1);
      expect(paged.items.length, 1);
      final ev = paged.items.first;
      expect(ev.id, 201);
      expect(ev.vehicleType, 'ambulance');
      expect(ev.priority, 1);
      expect(ev.status, 'active');
      expect(ev.isActive, isTrue);
    });

    test('createEmergencyEvent posts payload and returns EmergencyEvent', () async {
      final mockClient = MockClient((request) async {
        expect(request.method, 'POST');
        expect(request.url.path, '/api/v1/emergency-events');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['vehicle_type'], 'fire_engine');
        expect(body['priority'], 1);
        expect(body['intersection_id'], 4);
        expect(body['status'], 'active');

        return http.Response(
          jsonEncode({
            'id': 202,
            'vehicle_type': 'fire_engine',
            'priority': 1,
            'status': 'active',
            'intersection_id': 4,
            'detected_at': '2026-10-07T14:10:00Z',
            'created_at': '2026-10-07T14:10:00Z',
            'updated_at': '2026-10-07T14:10:00Z',
          }),
          201,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = EmergencyService(apiClient: createTestClient(mockClient));
      final ev = await service.createEmergencyEvent(
        vehicleType: 'fire_engine',
        priority: 1,
        intersectionId: 4,
      );

      expect(ev.id, 202);
      expect(ev.vehicleType, 'fire_engine');
    });

    test('prioritize sends emergency_event_id and destination_intersection_id payload to /control/emergency/prioritize', () async {
      final mockClient = MockClient((request) async {
        expect(request.method, 'POST');
        expect(request.url.path, '/api/v1/control/emergency/prioritize');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['emergency_event_id'], 201);
        expect(body['destination_intersection_id'], 8);

        return http.Response(
          jsonEncode({
            'decision_id': 901,
            'corridor_plan': {
              'corridor_id': 'CORR-EM-01',
              'path': [3, 4, 8],
              'signal_actions': [
                {
                  'intersection_id': 3,
                  'signal_id': 10,
                  'action': 'preempt',
                  'duration_seconds': 45.0,
                  'reason': 'Clear leading intersection',
                },
                {
                  'intersection_id': 4,
                  'signal_id': 11,
                  'action': 'extend_green',
                  'duration_seconds': 60.0,
                  'reason': 'Green wave propagation',
                }
              ],
              'estimated_minutes': 3.2,
              'from_intersection_id': 3,
              'to_intersection_id': 8,
            },
            'affected_intersection_ids': [3, 4, 8],
            'is_recommendation': true,
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = EmergencyService(apiClient: createTestClient(mockClient));
      final res = await service.prioritize(
        emergencyEventId: 201,
        destinationIntersectionId: 8,
      );

      expect(res.decisionId, 901);
      expect(res.isRecommendation, isTrue);
      expect(res.corridorPlan.corridorId, 'CORR-EM-01');
      expect(res.corridorPlan.path, [3, 4, 8]);
      expect(res.corridorPlan.signalActions.length, 2);
      expect(res.corridorPlan.signalActions.first.action, 'preempt');
      expect(res.affectedIntersectionIds, [3, 4, 8]);
    });

    test('restore sends emergency_event_id payload to /control/emergency/restore', () async {
      final mockClient = MockClient((request) async {
        expect(request.method, 'POST');
        expect(request.url.path, '/api/v1/control/emergency/restore');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['emergency_event_id'], 201);

        return http.Response(
          jsonEncode({
            'decision_id': 902,
            'emergency_event_id': 201,
            'action': 'NO_ACTION',
            'reason': 'Emergency transit cleared; resuming cyclic coordination',
            'affected_signal_ids': [10, 11],
            'is_recommendation': true,
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = EmergencyService(apiClient: createTestClient(mockClient));
      final res = await service.restore(emergencyEventId: 201);

      expect(res.decisionId, 902);
      expect(res.emergencyEventId, 201);
      expect(res.action, 'NO_ACTION');
      expect(res.affectedSignalIds, [10, 11]);
      expect(res.isRecommendation, isTrue);
    });

    test('greenCorridorRecommend constructs request body and parses advisory recommendation', () async {
      final mockClient = MockClient((request) async {
        expect(request.method, 'POST');
        expect(request.url.path, '/api/v1/control/green-corridor/recommend');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['from_intersection_id'], 1);
        expect(body['to_intersection_id'], 5);
        expect(body['emergency_speed_kmh'], 60.0);

        return http.Response(
          jsonEncode({
            'corridor_plan': {
              'corridor_id': 'PLAN-ADV-01',
              'path': [1, 2, 5],
              'signal_actions': [],
              'estimated_minutes': 2.1,
              'from_intersection_id': 1,
              'to_intersection_id': 5,
            },
            'is_recommendation': true,
            'note': 'Advisory proposal only',
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = EmergencyService(apiClient: createTestClient(mockClient));
      final res = await service.greenCorridorRecommend(
        fromIntersectionId: 1,
        toIntersectionId: 5,
      );

      expect(res.isRecommendation, isTrue);
      expect(res.corridorPlan.corridorId, 'PLAN-ADV-01');
    });

    test('maps 403 Forbidden when unauthorized analyst attempts prioritization', () async {
      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode({'detail': 'Forbidden: Insufficient role permissions'}),
          403,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = EmergencyService(apiClient: createTestClient(mockClient));

      expect(
        () => service.prioritize(
          emergencyEventId: 201,
          destinationIntersectionId: 8,
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
