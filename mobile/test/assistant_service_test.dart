import 'dart:convert';

import 'package:ai_trafficos/services/api_client.dart';
import 'package:ai_trafficos/services/assistant_service.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class FakeSecureStorage implements FlutterSecureStorage {
  final Map<String, String> _data = {
    'aitrafficos_access_token': 'fake_jwt_token',
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

ApiClient createTestApiClient(http.Client client) {
  return ApiClient(
    baseUrl: 'https://traffic.city.gov/api/v1',
    client: client,
    storage: FakeSecureStorage(),
  );
}

void main() {
  group('AssistantService Unit Tests', () {
    test('chat success parses all fields including provenance labels and insufficient_data', () async {
      final mockHttp = MockClient((request) async {
        expect(request.method, 'POST');
        expect(request.url.path, '/api/v1/assistant/chat');
        expect(request.headers['Authorization'], 'Bearer fake_jwt_token');

        final payload = jsonDecode(request.body) as Map<String, dynamic>;
        expect(payload['message'], 'Analyze Main St corridor');
        expect(payload['conversation_id'], 'conv-prev-42');

        final cannedResponse = {
          'answer': 'Corridor speed is **24 km/h** with 78% occupancy.',
          'conversation_id': 'conv-new-99',
          'tool_calls': [
            {
              'tool': 'query_corridor_flow',
              'arguments': {'corridor_id': 12},
              'result_summary': 'Flow rate 1420 veh/hr',
            }
          ],
          'provenance': [
            {'segment': 'Flow rate 1420 veh/hr', 'label': 'observed'},
            {'segment': 'Delay expected to grow +15%', 'label': 'predicted'},
            {'segment': 'Extend green wave split +6s', 'label': 'recommended'},
            {'segment': 'Standard signal specs', 'label': 'custom_unknown'},
          ],
          'insufficient_data': true,
          'suggested_followups': [
            'What is the delay on 5th Ave?',
            'Trigger green wave now',
          ],
        };

        return http.Response(
          jsonEncode(cannedResponse),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestApiClient(mockHttp);
      final service = AssistantService(apiClient: apiClient);

      final result = await service.chat(
        message: 'Analyze Main St corridor',
        conversationId: 'conv-prev-42',
      );

      expect(result.answer, 'Corridor speed is **24 km/h** with 78% occupancy.');
      expect(result.conversationId, 'conv-new-99');
      expect(result.insufficientData, isTrue);

      // Tool calls
      expect(result.toolCalls.length, 1);
      expect(result.toolCalls.first.tool, 'query_corridor_flow');
      expect(result.toolCalls.first.arguments['corridor_id'], 12);
      expect(result.toolCalls.first.resultSummary, 'Flow rate 1420 veh/hr');

      // Provenance segments
      expect(result.provenance.length, 4);
      expect(result.provenance[0].segment, 'Flow rate 1420 veh/hr');
      expect(result.provenance[0].label, ProvenanceLabel.observed);
      expect(result.provenance[0].label.displayName, 'Observed');

      expect(result.provenance[1].segment, 'Delay expected to grow +15%');
      expect(result.provenance[1].label, ProvenanceLabel.predicted);
      expect(result.provenance[1].label.displayName, 'Predicted');

      expect(result.provenance[2].segment, 'Extend green wave split +6s');
      expect(result.provenance[2].label, ProvenanceLabel.recommended);
      expect(result.provenance[2].label.displayName, 'Recommended');

      expect(result.provenance[3].label, ProvenanceLabel.unknown);
      expect(result.provenance[3].label.displayName, 'Unknown');

      // Followups
      expect(result.suggestedFollowups, [
        'What is the delay on 5th Ave?',
        'Trigger green wave now',
      ]);
    });

    test('HTTP 401 maps to AssistantUnauthorizedException', () async {
      final mockHttp = MockClient((request) async {
        return http.Response(
          jsonEncode({'detail': 'Token expired'}),
          401,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestApiClient(mockHttp);
      final service = AssistantService(apiClient: apiClient);

      expect(
        () => service.chat(message: 'Hello assistant'),
        throwsA(isA<AssistantUnauthorizedException>()),
      );
    });

    test('HTTP 403 maps to AssistantForbiddenException with role details', () async {
      final mockHttp = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'detail': 'Role analyst not permitted to invoke AI Assistant',
            'role': 'analyst',
          }),
          403,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestApiClient(mockHttp);
      final service = AssistantService(apiClient: apiClient);

      try {
        await service.chat(message: 'Can I optimize signals?');
        fail('Should throw AssistantForbiddenException');
      } on AssistantForbiddenException catch (e) {
        expect(e.statusCode, 403);
        expect(e.role, 'analyst');
        expect(e.message, contains('Role analyst not permitted'));
      }
    });

    test('HTTP 429 maps to AssistantRateLimitedException', () async {
      final mockHttp = MockClient((request) async {
        return http.Response(
          jsonEncode({'detail': 'Too many queries per minute'}),
          429,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestApiClient(mockHttp);
      final service = AssistantService(apiClient: apiClient);

      expect(
        () => service.chat(message: 'Quick test'),
        throwsA(isA<AssistantRateLimitedException>()),
      );
    });

    test('HTTP 500 maps to AssistantServerException', () async {
      final mockHttp = MockClient((request) async {
        return http.Response(
          jsonEncode({'detail': 'Model service unavailable'}),
          500,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestApiClient(mockHttp);
      final service = AssistantService(apiClient: apiClient);

      try {
        await service.chat(message: 'System query');
        fail('Should throw AssistantServerException');
      } on AssistantServerException catch (e) {
        expect(e.statusCode, 500);
        expect(e.message, contains('Model service unavailable'));
      }
    });

    test('Network failure maps to AssistantNetworkException', () async {
      final mockHttp = MockClient((request) async {
        throw http.ClientException('Network unreachable');
      });

      final apiClient = createTestApiClient(mockHttp);
      final service = AssistantService(apiClient: apiClient);

      expect(
        () => service.chat(message: 'Offline test'),
        throwsA(isA<AssistantNetworkException>()),
      );
    });

    test('History is truncated to the last 20 messages sent to server', () async {
      late Map<String, dynamic> capturedPayload;

      final mockHttp = MockClient((request) async {
        capturedPayload = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({
            'answer': 'Acknowledged truncated history.',
            'conversation_id': 'conv-trunc',
            'tool_calls': [],
            'provenance': [],
            'insufficient_data': false,
            'suggested_followups': [],
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestApiClient(mockHttp);
      final service = AssistantService(apiClient: apiClient);

      // Create 26 past messages (msg_0 to msg_25)
      final longHistory = List.generate(
        26,
        (i) => AssistantMessage(
          role: i.isEven ? 'user' : 'assistant',
          content: 'Message turn #$i',
        ),
      );

      await service.chat(
        message: 'Latest prompt after long thread',
        history: longHistory,
      );

      final sentHistory = capturedPayload['history'] as List<dynamic>;
      expect(sentHistory.length, 20);

      // The 20 items must be msg_6 through msg_25 (the last 20)
      expect(sentHistory.first['content'], 'Message turn #6');
      expect(sentHistory.last['content'], 'Message turn #25');
    });
  });
}
