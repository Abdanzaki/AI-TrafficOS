import 'dart:async';
import 'dart:convert';
import 'package:ai_trafficos/screens/predictions_screen.dart';
import 'package:ai_trafficos/services/api_client.dart';
import 'package:ai_trafficos/services/auth_service.dart';
import 'package:ai_trafficos/widgets/empty_state.dart';
import 'package:ai_trafficos/widgets/error_state.dart';
import 'package:ai_trafficos/widgets/loading_state.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
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
  group('PredictionsScreen Widget Tests', () {
    testWidgets('renders LoadingState while generating forecast', (tester) async {
      final completer = Completer<http.Response>();

      final mockClient = MockClient((request) async {
        if (request.url.path.endsWith('/junctions')) {
          return http.Response(
            jsonEncode({
              'items': [
                {'id': 1, 'name': 'Main & 1st', 'code': 'INT-01', 'status': 'active'}
              ],
              'total': 1,
              'page': 1,
              'per_page': 50,
              'pages': 1,
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        if (request.url.path.contains('/predict')) {
          return completer.future;
        }
        return http.Response(
          jsonEncode({'items': [], 'total': 0, 'page': 1, 'per_page': 20, 'pages': 1}),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(apiClient),
          ],
          child: const MaterialApp(
            home: PredictionsScreen(initialIntersectionId: 1),
          ),
        ),
      );

      await tester.pump();
      expect(find.byType(LoadingState), findsOneWidget);

      // Finish future
      completer.complete(
        http.Response(
          jsonEncode({
            'intersection_id': 1,
            'status': 'predicted',
            'flow': {'value': 120.0, 'confidence': 0.85},
            'congestion': {'value': 45.0, 'confidence': 0.9, 'queue': 3.0},
          }),
          200,
          headers: {'content-type': 'application/json'},
        ),
      );
      await tester.pumpAndSettle();
    });

    testWidgets('renders InsufficientDataException with clean empty state and required row count', (tester) async {
      final mockClient = MockClient((request) async {
        if (request.url.path.endsWith('/junctions')) {
          return http.Response(
            jsonEncode({
              'items': [
                {'id': 1, 'name': 'Main & 1st', 'code': 'INT-01', 'status': 'active'}
              ],
              'total': 1,
              'page': 1,
              'per_page': 50,
              'pages': 1,
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        if (request.url.path.contains('/predict')) {
          return http.Response(
            jsonEncode({
              'detail': {
                'error': 'insufficient_data',
                'rows_found': 7,
                'rows_required': 20,
                'message': 'Telemetry records below minimum threshold for prediction',
              },
            }),
            422,
            headers: {'content-type': 'application/json'},
          );
        }

        return http.Response(
          jsonEncode({'items': [], 'total': 0, 'page': 1, 'per_page': 20, 'pages': 1}),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(apiClient),
          ],
          child: const MaterialApp(
            home: PredictionsScreen(initialIntersectionId: 1),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.byType(EmptyState), findsWidgets);
      expect(find.text('Insufficient Telemetry Data'), findsOneWidget);
      expect(
        find.textContaining('Not enough data yet — predictions need 20 rows (found 7)'),
        findsOneWidget,
      );
    });

    testWidgets('renders ErrorState with retry button when prediction fails with 500 error', (tester) async {
      final mockClient = MockClient((request) async {
        if (request.url.path.endsWith('/junctions')) {
          return http.Response(
            jsonEncode({
              'items': [
                {'id': 1, 'name': 'Main & 1st', 'code': 'INT-01', 'status': 'active'}
              ],
              'total': 1,
              'page': 1,
              'per_page': 50,
              'pages': 1,
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        if (request.url.path.contains('/predict')) {
          return http.Response(
            jsonEncode({'detail': 'Internal Server Error: Neural inference failed'}),
            500,
            headers: {'content-type': 'application/json'},
          );
        }

        return http.Response(
          jsonEncode({'items': [], 'total': 0, 'page': 1, 'per_page': 20, 'pages': 1}),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(apiClient),
          ],
          child: const MaterialApp(
            home: PredictionsScreen(initialIntersectionId: 1),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.byType(ErrorState), findsOneWidget);
      expect(find.text('Prediction Unavailable'), findsOneWidget);
      expect(find.text('Retry'), findsOneWidget);
    });

    testWidgets('renders forecast metrics cards and confidence bars on success', (tester) async {
      final mockClient = MockClient((request) async {
        if (request.url.path.endsWith('/junctions')) {
          return http.Response(
            jsonEncode({
              'items': [
                {'id': 1, 'name': 'Main & 1st', 'code': 'INT-01', 'status': 'active'}
              ],
              'total': 1,
              'page': 1,
              'per_page': 50,
              'pages': 1,
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        if (request.url.path.contains('/predict')) {
          return http.Response(
            jsonEncode({
              'intersection_id': 1,
              'status': 'predicted',
              'model_version': 'traffic_forecaster_v2',
              'flow': {'value': 165.4, 'confidence': 0.88},
              'congestion': {'value': 54.2, 'confidence': 0.91, 'queue': 4.6, 'queue_confidence': 0.82},
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        if (request.url.path.contains('/ai-predictions')) {
          return http.Response(
            jsonEncode({
              'items': [
                {
                  'id': 701,
                  'intersection_id': 1,
                  'prediction_type': 'congestion',
                  'predicted_for': '2026-10-07T15:00:00Z',
                  'confidence': 0.92,
                  'model_version': 'traffic_forecaster_v2',
                  'payload': {'congestion': 54.2},
                  'created_at': '2026-10-07T14:30:00Z',
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
        }

        return http.Response(
          jsonEncode({'items': [], 'total': 0, 'page': 1, 'per_page': 20, 'pages': 1}),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(apiClient),
          ],
          child: const MaterialApp(
            home: PredictionsScreen(initialIntersectionId: 1),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('30-Min Forward Forecast'), findsOneWidget);
      expect(find.text('Forecast Vehicular Volume'), findsOneWidget);
      expect(find.text('165.4 veh/min'), findsOneWidget);
      expect(find.text('Forecast Congestion Index'), findsOneWidget);
      expect(find.text('54.2%'), findsOneWidget);
      expect(find.text('Forecast Stop-Bar Queue Growth'), findsOneWidget);
      expect(find.text('+4.6 veh'), findsOneWidget);

      await tester.drag(find.byType(ListView), const Offset(0, -600));
      await tester.pumpAndSettle();

      expect(find.text('Historical AI Predictions'), findsOneWidget);
      expect(find.text('CONGESTION'), findsOneWidget);
      expect(find.text('92% CONF'), findsOneWidget);
    });
  });
}
