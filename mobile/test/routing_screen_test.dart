import 'dart:async';
import 'dart:convert';
import 'package:ai_trafficos/screens/routing_screen.dart';
import 'package:ai_trafficos/services/api_client.dart';
import 'package:ai_trafficos/services/auth_service.dart';
import 'package:ai_trafficos/widgets/error_state.dart';
import 'package:ai_trafficos/widgets/junction_map.dart';
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
  group('RoutingScreen Widget Tests', () {
    testWidgets('renders origin and destination junction pickers and initial empty/ready state', (tester) async {
      final mockClient = MockClient((request) async {
        if (request.url.path.endsWith('/junctions')) {
          return http.Response(
            jsonEncode({
              'items': [
                {'id': 1, 'name': 'Main & 1st', 'code': 'INT-01', 'latitude': 37.7749, 'longitude': -122.4194, 'status': 'active'},
                {'id': 2, 'name': 'Market & 4th', 'code': 'INT-02', 'latitude': 37.7850, 'longitude': -122.4060, 'status': 'active'},
              ],
              'total': 2,
              'page': 1,
              'per_page': 50,
              'pages': 1,
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        return http.Response(
          jsonEncode({
            'algorithm': 'astar',
            'path': [1, 2],
            'edges': [
              {
                'road_id': 10,
                'from_intersection_id': 1,
                'to_intersection_id': 2,
                'length_km': 1.85,
                'cost_minutes': 3.4,
              }
            ],
            'total_cost_minutes': 3.4,
            'total_distance_km': 1.85,
          }),
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
            home: RoutingScreen(initialFromId: 1, initialToId: 2),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('Municipal Optimal Routing'), findsOneWidget);
      expect(find.text('Route Query Configuration'), findsOneWidget);
      expect(find.text('Find Optimal Route'), findsOneWidget);
      expect(find.text('Total Distance'), findsOneWidget);
      expect(find.text('1.85 km'), findsOneWidget);
      expect(find.text('Estimated Duration'), findsOneWidget);
      expect(find.text('3.4 min'), findsOneWidget);
      expect(find.byType(JunctionMapWidget), findsOneWidget);
      expect(find.text('Main & 1st'), findsWidgets);
      expect(find.text('Market & 4th'), findsWidgets);
    });

    testWidgets('renders LoadingState during path calculation', (tester) async {
      final completer = Completer<http.Response>();

      final mockClient = MockClient((request) async {
        if (request.url.path.endsWith('/junctions')) {
          return http.Response(
            jsonEncode({
              'items': [
                {'id': 1, 'name': 'Main & 1st', 'code': 'INT-01', 'latitude': 37.77, 'longitude': -122.41, 'status': 'active'},
                {'id': 2, 'name': 'Market & 4th', 'code': 'INT-02', 'latitude': 37.78, 'longitude': -122.40, 'status': 'active'},
              ],
              'total': 2,
              'page': 1,
              'per_page': 50,
              'pages': 1,
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        if (request.url.path.contains('/routing/optimal-route')) {
          return completer.future;
        }

        return http.Response(
          jsonEncode({}),
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
            home: RoutingScreen(initialFromId: 1, initialToId: 2),
          ),
        ),
      );

      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.byType(LoadingState), findsOneWidget);
      expect(find.text('Calculating minimum impedance path...'), findsOneWidget);

      completer.complete(
        http.Response(
          jsonEncode({
            'algorithm': 'astar',
            'path': [1, 2],
            'edges': [],
            'total_cost_minutes': 2.5,
            'total_distance_km': 1.2,
          }),
          200,
          headers: {'content-type': 'application/json'},
        ),
      );

      await tester.pumpAndSettle();
      expect(find.text('1.20 km'), findsOneWidget);
      expect(find.text('2.5 min'), findsOneWidget);
    });

    testWidgets('renders ErrorState when routing calculation fails', (tester) async {
      final mockClient = MockClient((request) async {
        if (request.url.path.endsWith('/junctions')) {
          return http.Response(
            jsonEncode({
              'items': [
                {'id': 1, 'name': 'Node A', 'code': 'NA', 'status': 'active'},
                {'id': 2, 'name': 'Node B', 'code': 'NB', 'status': 'active'},
              ],
              'total': 2,
              'page': 1,
              'per_page': 50,
              'pages': 1,
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        if (request.url.path.contains('/routing/optimal-route')) {
          return http.Response(
            jsonEncode({'detail': 'No traversable path between Node A and Node B'}),
            404,
            headers: {'content-type': 'application/json'},
          );
        }

        return http.Response(jsonEncode({}), 200, headers: {'content-type': 'application/json'});
      });

      final apiClient = createTestClient(mockClient);

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(apiClient),
          ],
          child: const MaterialApp(
            home: RoutingScreen(initialFromId: 1, initialToId: 2),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.byType(ErrorState), findsOneWidget);
      expect(find.text('Pathfinding Infeasible'), findsOneWidget);
      expect(find.textContaining('No traversable path'), findsOneWidget);
    });
  });
}
