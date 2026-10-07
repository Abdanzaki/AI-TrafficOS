import 'dart:convert';
import 'package:ai_trafficos/screens/decisions_screen.dart';
import 'package:ai_trafficos/services/api_client.dart';
import 'package:ai_trafficos/services/auth_service.dart';
import 'package:ai_trafficos/widgets/app_card.dart';
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
  group('DecisionsScreen Widget Tests', () {
    testWidgets('renders list of decisions and toggles expand/collapse details', (tester) async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/ai-decisions');

        final payload = {
          'items': [
            {
              'id': 801,
              'intersection_id': 10,
              'junction': 'Main Street & 4th Avenue',
              'decision_type': 'EXTEND_GREEN',
              'action': 'EXTEND_GREEN',
              'reason': 'Surge detected on southbound approach due to stadium egress',
              'expected_impact': 'Prevents corridor gridlock and clears queue in 45s',
              'confidence': 0.94,
              'model_version': 'decision_engine_v2.1',
              'status': 'applied',
              'created_at': '2026-10-07T14:40:00Z',
              'applied_at': '2026-10-07T14:40:05Z',
            },
            {
              'id': 802,
              'intersection_id': 12,
              'junction': 'Broadway & 9th',
              'decision_type': 'SHORTEN_CYCLE',
              'action': 'SHORTEN_CYCLE',
              'reason': 'Low density across all cross-streets allows cycle compression',
              'expected_impact': 'Decreases average pedestrian waiting delay',
              'confidence': 0.86,
              'model_version': 'decision_engine_v2.1',
              'status': 'proposed',
              'created_at': '2026-10-07T14:38:00Z',
            },
          ],
          'total': 2,
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

      final apiClient = createTestClient(mockClient);

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(apiClient),
          ],
          child: const MaterialApp(
            home: DecisionsScreen(),
          ),
        ),
      );

      await tester.pumpAndSettle();

      // Verify list items render
      expect(find.widgetWithText(AppCard, 'EXTEND_GREEN'), findsOneWidget);
      expect(find.text('Main Street & 4th Avenue'), findsOneWidget);
      expect(find.text('APPLIED'), findsOneWidget);

      expect(find.widgetWithText(AppCard, 'SHORTEN_CYCLE'), findsOneWidget);
      expect(find.text('Broadway & 9th'), findsOneWidget);
      expect(find.text('PROPOSED'), findsOneWidget);

      // Verify expanded details are initially NOT visible
      expect(find.text('Engine Confidence'), findsNothing);
      expect(find.text('Expected Impact: '), findsNothing);
      expect(find.text('Model Version: '), findsNothing);

      // Tap first decision to EXPAND it
      await tester.tap(find.text('Main Street & 4th Avenue'));
      await tester.pumpAndSettle();

      // Verify expanded details now show
      expect(find.text('Engine Confidence'), findsOneWidget);
      expect(find.text('94%'), findsOneWidget);
      expect(find.text('Expected Impact: '), findsOneWidget);
      expect(
        find.text('Prevents corridor gridlock and clears queue in 45s'),
        findsOneWidget,
      );
      expect(find.text('Model Version: '), findsOneWidget);
      expect(find.text('decision_engine_v2.1'), findsOneWidget);

      // Tap first decision again to COLLAPSE it
      await tester.tap(find.text('Main Street & 4th Avenue'));
      await tester.pumpAndSettle();

      // Verify expanded details are hidden again
      expect(find.text('Engine Confidence'), findsNothing);
      expect(find.text('Expected Impact: '), findsNothing);
    });

    testWidgets('filtering by action type re-queries with selected decision type filter', (tester) async {
      String? queriedDecisionType;

      final mockClient = MockClient((request) async {
        queriedDecisionType = request.url.queryParameters['decision_type'];

        final payload = {
          'items': [
            {
              'id': 801,
              'intersection_id': 10,
              'junction': 'Main Street & 4th Avenue',
              'action': 'EXTEND_GREEN',
              'reason': 'Surge detected on southbound approach',
              'status': 'applied',
              'created_at': '2026-10-07T14:40:00Z',
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

      final apiClient = createTestClient(mockClient);

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(apiClient),
          ],
          child: const MaterialApp(
            home: DecisionsScreen(),
          ),
        ),
      );

      await tester.pumpAndSettle();

      // Initial query had no decision_type filter
      expect(queriedDecisionType, isNull);

      // Tap EXTEND_GREEN chip
      await tester.tap(find.widgetWithText(ChoiceChip, 'EXTEND_GREEN'));
      await tester.pumpAndSettle();

      // Verify filter was passed in query
      expect(queriedDecisionType, 'EXTEND_GREEN');
    });
  });
}
