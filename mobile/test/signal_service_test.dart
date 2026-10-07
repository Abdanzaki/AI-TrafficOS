import 'dart:convert';
import 'package:ai_trafficos/models/signal.dart';
import 'package:ai_trafficos/services/api_client.dart';
import 'package:ai_trafficos/services/signal_service.dart';
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
  group('SignalService Tests', () {
    test('getSignals parses paginated signals JSON correctly', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/signals');
        expect(request.url.queryParameters['intersection_id'], '10');
        expect(request.url.queryParameters['page'], '1');
        expect(request.url.queryParameters['per_page'], '20');

        final payload = {
          'items': [
            {
              'id': 101,
              'intersection_id': 10,
              'name': 'North-South Controller',
              'code': 'SIG-101',
              'status': 'active',
              'current_phase': 'Northbound Green',
              'state': 'green',
              'observed_state': 'green',
              'observed_confidence': 0.98,
              'phases': [
                {
                  'id': 1,
                  'signal_id': 101,
                  'intersection_id': 10,
                  'name': 'Northbound Green',
                  'phase_order': 1,
                  'duration_seconds': 45,
                  'state': 'green',
                  'is_active': true,
                },
                {
                  'id': 2,
                  'signal_id': 101,
                  'intersection_id': 10,
                  'name': 'Yellow Transition',
                  'phase_order': 2,
                  'duration_seconds': 4,
                  'state': 'yellow',
                  'is_active': false,
                },
                {
                  'id': 3,
                  'signal_id': 101,
                  'intersection_id': 10,
                  'name': 'All-Red Clearance',
                  'phase_order': 3,
                  'duration_seconds': 3,
                  'state': 'red',
                  'is_active': false,
                },
              ],
            },
          ],
          'total': 1,
          'page': 1,
          'per_page': 20,
          'pages': 1,
        };

        return http.Response(
          jsonEncode(payload),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = SignalService(apiClient: createTestClient(mockClient));
      final result = await service.getSignals(intersectionId: 10);

      expect(result.total, 1);
      expect(result.items.length, 1);

      final sig = result.items.first;
      expect(sig.id, 101);
      expect(sig.intersectionId, 10);
      expect(sig.name, 'North-South Controller');
      expect(sig.code, 'SIG-101');
      expect(sig.status, 'active');
      expect(sig.currentPhase, 'Northbound Green');
      expect(sig.state, SignalState.green);
      expect(sig.stateColor, isNotNull);
      expect(sig.phases.length, 3);
      expect(sig.phases[0].durationSeconds, 45);
      expect(sig.phases[0].isActive, isTrue);
    });

    test('getSignal parses single signal with ordered phases and optical state', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/signals/101');

        final payload = {
          'id': 101,
          'intersection_id': 10,
          'code': 'SIG-101',
          'status': 'active',
          'observed_state': 'yellow',
          'observed_confidence': 0.89,
          'observed_at': '2026-10-07T12:00:00Z',
          'phases': [
            {
              'id': 10,
              'signal_id': 101,
              'name': 'Phase 1',
              'phase_order': 1,
              'duration_seconds': 30,
              'state': 'green',
              'is_active': false,
            },
            {
              'id': 11,
              'signal_id': 101,
              'name': 'Phase 2',
              'phase_order': 2,
              'duration_seconds': 35,
              'state': 'yellow',
              'is_active': true,
            },
          ],
        };

        return http.Response(
          jsonEncode(payload),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = SignalService(apiClient: createTestClient(mockClient));
      final sig = await service.getSignal(101);

      expect(sig.id, 101);
      expect(sig.code, 'SIG-101');
      expect(sig.observedState, 'yellow');
      expect(sig.observedConfidence, 0.89);
      expect(sig.currentPhase, 'Phase 2');
      expect(sig.state, SignalState.yellow);
      expect(sig.phases.length, 2);
    });

    test('overrideSignal correctly constructs and sends override payload', () async {
      Map<String, dynamic>? capturedBody;

      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/signals/101/override');
        expect(request.method, 'POST');

        capturedBody = jsonDecode(request.body) as Map<String, dynamic>;

        final payload = {
          'id': 101,
          'intersection_id': 10,
          'code': 'SIG-101',
          'status': 'active',
          'current_phase': 'Phase 1',
          'state': 'green',
          'phases': [
            {
              'id': 10,
              'signal_id': 101,
              'name': 'Phase 1',
              'phase_order': 1,
              'duration_seconds': 60,
              'state': 'green',
              'is_active': true,
            },
          ],
        };

        return http.Response(
          jsonEncode(payload),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = SignalService(apiClient: createTestClient(mockClient));
      final res = await service.overrideSignal(
        101,
        phase: 'Phase 1',
        phaseId: 10,
        durationSeconds: 60,
        state: 'green',
        reason: 'Emergency corridor prioritization',
      );

      expect(capturedBody, isNotNull);
      expect(capturedBody!['phase'], 'Phase 1');
      expect(capturedBody!['duration_seconds'], 60);
      expect(capturedBody!['phase_id'], 10);
      expect(capturedBody!['state'], 'green');
      expect(capturedBody!['reason'], 'Emergency corridor prioritization');

      expect(res.id, 101);
      expect(res.currentPhase, 'Phase 1');
      expect(res.state, SignalState.green);
    });

    test('overrideSignal maps 403 Forbidden to typed ApiException', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/signals/101/override');

        return http.Response(
          jsonEncode({'detail': 'Forbidden: Insufficient privileges'}),
          403,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = SignalService(apiClient: createTestClient(mockClient));

      expect(
        () => service.overrideSignal(
          101,
          phase: 'Phase 1',
          durationSeconds: 45,
        ),
        throwsA(
          isA<ApiException>()
              .having((e) => e.statusCode, 'statusCode', 403)
              .having((e) => e.isForbidden, 'isForbidden', isTrue)
              .having((e) => e.message, 'message', contains('Forbidden')),
        ),
      );
    });
  });
}
