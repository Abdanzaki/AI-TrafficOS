import 'dart:convert';
import 'package:ai_trafficos/services/api_client.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  group('ApiClient', () {
    test('getHealth returns ApiSuccess on 200 with valid json', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/health');
        return http.Response(
          jsonEncode({
            'status': 'ok',
            'service': 'ai-trafficos-backend',
            'version': '0.1.0',
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final client = ApiClient(
        baseUrl: 'http://example.com',
        client: mockClient,
      );

      final result = await client.getHealth();

      expect(result.isSuccess, isTrue);
      expect(result.dataOrNull?.status, 'ok');
      expect(result.dataOrNull?.isHealthy, isTrue);
    });

    test('getHealth returns ApiFailure on 500 error code', () async {
      final mockClient = MockClient((request) async {
        return http.Response('Internal Server Error', 500);
      });

      final client = ApiClient(
        baseUrl: 'http://example.com',
        client: mockClient,
      );

      final result = await client.getHealth();

      expect(result.isFailure, isTrue);
      expect(result.errorOrNull, contains('HTTP 500'));
    });

    test('getHealth returns ApiFailure on non-JSON response', () async {
      final mockClient = MockClient((request) async {
        return http.Response('not valid json', 200);
      });

      final client = ApiClient(
        baseUrl: 'http://example.com',
        client: mockClient,
      );

      final result = await client.getHealth();

      expect(result.isFailure, isTrue);
      expect(result.errorOrNull, contains('Invalid JSON response'));
    });
  });
}
