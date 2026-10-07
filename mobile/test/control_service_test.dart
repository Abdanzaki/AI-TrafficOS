import 'dart:convert';
import 'package:ai_trafficos/models/prediction.dart';
import 'package:ai_trafficos/services/api_client.dart';
import 'package:ai_trafficos/services/control_service.dart';
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

ApiClient createTestClient(http.Client client) {
  return ApiClient(
    baseUrl: 'http://test',
    client: client,
    storage: FakeSecureStorage(),
  );
}

void main() {
  group('ControlService Tests', () {
    test('getRecommendations parses recommendation, traffic state, and predictive snapshot', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/control/recommendations');
        expect(request.method, 'POST');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['intersection_id'], 42);

        final payload = {
          'id': 501,
          'intersection_id': 42,
          'action': 'EXTEND_GREEN',
          'reason': 'Heavy platoon approaching from eastbound corridor',
          'expected_impact': 'Reduces stop-bar delay by 28%',
          'confidence': 0.92,
          'is_recommendation': true,
          'created_at': '2026-10-07T14:30:00Z',
          'current': {
            'intersection_id': 42,
            'vehicle_count': 185,
            'density': 34.2,
            'queue_length': 14.5,
            'occupancy': 0.68,
            'avg_speed_kmh': 41.5,
            'incident_count': 1,
            'active_emergency': false,
            'observed_signal_state': 'green',
            'current_phase_name': 'Eastbound Main',
            'current_green_elapsed_s': 22.0,
            'telemetry_age_s': 8.5,
            'source': 'sensor',
          },
          'predicted': {
            'congestion': 68.0,
            'volume': 210.0,
            'queue_growth': 3.5,
            'horizon_minutes': 30,
            'model_version': 'traffic_forecaster_v2',
            'confidence': 0.88,
          },
        };

        return http.Response(
          jsonEncode(payload),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = ControlService(apiClient: createTestClient(mockClient));
      final rec = await service.getRecommendations(42);

      expect(rec.id, 501);
      expect(rec.intersectionId, 42);
      expect(rec.action, 'EXTEND_GREEN');
      expect(rec.reason, contains('Heavy platoon'));
      expect(rec.expectedImpact, contains('Reduces stop-bar delay'));
      expect(rec.confidence, 0.92);
      expect(rec.isRecommendation, isTrue);

      expect(rec.current, isNotNull);
      expect(rec.current!.vehicleCount, 185);
      expect(rec.current!.queueLength, 14.5);
      expect(rec.current!.density, 34.2);

      expect(rec.predicted, isNotNull);
      expect(rec.predicted!.congestion, 68.0);
      expect(rec.predicted!.volume, 210.0);
      expect(rec.predicted!.horizonMinutes, 30);
    });

    test('simulate correctly parses measured simulation deltas and verdict', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/control/simulate');
        expect(request.method, 'POST');

        final payload = {
          'current_result': {
            'total_wait_veh_min': 145.2,
            'avg_queue_veh': 18.4,
            'max_queue_veh': 32.0,
            'throughput_veh': 240.0,
            'residual_queue_veh': 8.0,
          },
          'proposed_result': {
            'total_wait_veh_min': 112.6,
            'avg_queue_veh': 13.9,
            'max_queue_veh': 24.0,
            'throughput_veh': 265.0,
            'residual_queue_veh': 4.0,
          },
          'delta_wait': -32.6,
          'delta_avg_queue': -4.5,
          'delta_throughput': 25.0,
          'verdict': 'proposed_better',
        };

        return http.Response(
          jsonEncode(payload),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = ControlService(apiClient: createTestClient(mockClient));
      final comp = await service.simulate(
        intersectionId: 42,
        proposedPlan: {
          'phases': {'phase_1': 45.0, 'phase_2': 35.0},
          'phase_to_approaches': {
            'phase_1': ['northbound'],
            'phase_2': ['eastbound'],
          },
        },
      );

      expect(comp.deltaWait, -32.6);
      expect(comp.deltaAvgQueue, -4.5);
      expect(comp.deltaThroughput, 25.0);
      expect(comp.verdict, 'proposed_better');
      expect(comp.isProposedBetter, isTrue);
      expect(comp.currentResult.totalWaitVehMin, 145.2);
      expect(comp.proposedResult.totalWaitVehMin, 112.6);
    });

    test('getRecommendations maps 422 insufficient_data to typed InsufficientDataException', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/control/recommendations');
        expect(request.method, 'POST');

        return http.Response(
          jsonEncode({
            'detail': {
              'error': 'insufficient_data',
              'rows_found': 6,
              'rows_required': 20,
              'message': 'Telemetry records insufficient to formulate reliable recommendations',
            },
          }),
          422,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = ControlService(apiClient: createTestClient(mockClient));

      expect(
        () => service.getRecommendations(42),
        throwsA(
          isA<InsufficientDataException>()
              .having((e) => e.rowsFound, 'rowsFound', 6)
              .having((e) => e.rowsRequired, 'rowsRequired', 20)
              .having((e) => e.message, 'message', contains('Telemetry records insufficient')),
        ),
      );
    });

    test('optimizeSignals parses Webster green split allocations and safety pass', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/control/optimize-signals');
        expect(request.method, 'POST');

        final payload = {
          'intersection_id': 42,
          'recommended_green_s': {
            '1': 42.5,
            '2': 27.5,
          },
          'total_cycle_s': 80.0,
          'method': 'Webster queue-proportional',
          'computed_at': '2026-10-07T14:35:00Z',
          'validated': true,
        };

        return http.Response(
          jsonEncode(payload),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = ControlService(apiClient: createTestClient(mockClient));
      final opt = await service.optimizeSignals(42);

      expect(opt.intersectionId, 42);
      expect(opt.totalCycleS, 80.0);
      expect(opt.method, contains('Webster'));
      expect(opt.recommendedGreenS['1'], 42.5);
      expect(opt.recommendedGreenS['2'], 27.5);
      expect(opt.validated, isTrue);
    });
  });
}
