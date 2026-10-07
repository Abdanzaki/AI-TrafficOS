import 'dart:convert';
import 'package:ai_trafficos/models/user.dart';
import 'package:ai_trafficos/screens/dashboard_screen.dart';
import 'package:ai_trafficos/services/api_client.dart';
import 'package:ai_trafficos/services/auth_service.dart';
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

void main() {
  group('DashboardScreen Widget Tests', () {
    late ApiClient mockApiClient;
    late FakeSecureStorage fakeStorage;

    setUp(() {
      final mockClient = MockClient((request) async {
        final path = request.url.path;

        if (path.endsWith('/junctions')) {
          return http.Response(
            jsonEncode({
              'items': [
                {
                  'id': 1,
                  'name': 'Main & 1st',
                  'code': 'INT-01',
                  'status': 'active',
                  'signals': [
                    {
                      'id': 11,
                      'intersection_id': 1,
                      'code': 'SIG-01',
                      'status': 'active',
                    }
                  ],
                  'lanes': [],
                }
              ],
              'total': 24,
              'page': 1,
              'per_page': 50,
              'pages': 1,
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        if (path.endsWith('/analytics/congestion-hotspots')) {
          return http.Response(
            jsonEncode([
              {
                'intersection_id': 1,
                'name': 'Corridor Peak North',
                'code': 'CP-01',
                'avg_congestion_level': 82.5,
                'record_count': 150,
              }
            ]),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        if (path.endsWith('/analytics/incidents-summary')) {
          return http.Response(
            jsonEncode({
              'total': 8,
              'by_severity': {'high': 3, 'low': 5},
              'by_status': {'reported': 2, 'acknowledged': 1, 'resolved': 5},
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        if (path.endsWith('/incidents')) {
          return http.Response(
            jsonEncode({
              'items': [
                {
                  'id': 50,
                  'severity': 'high',
                  'status': 'reported',
                  'description': 'Stalled bus blocking curb lane',
                  'created_at': '2026-10-07T12:00:00Z',
                  'updated_at': '2026-10-07T12:00:00Z',
                }
              ],
              'total': 1,
              'page': 1,
              'per_page': 5,
              'pages': 1,
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        if (path.endsWith('/analytics/traffic-summary')) {
          return http.Response(
            jsonEncode([
              {
                'bucket': '2026-10-07T12:00:00Z',
                'avg_vehicle_count': 120.0,
                'avg_speed': 45.0,
                'avg_congestion': 54.0,
                'record_count': 20,
              }
            ]),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        return http.Response('{}', 200, headers: {'content-type': 'application/json'});
      });

      fakeStorage = FakeSecureStorage();
      mockApiClient = ApiClient(
        baseUrl: 'http://test',
        client: mockClient,
        storage: fakeStorage,
      );
    });

    testWidgets('DashboardScreen renders greeting with user and role chip', (tester) async {
      const testUser = User(
        id: 7,
        email: 'analyst@city.gov',
        fullName: 'Jane Doe',
        role: User.roleAnalyst,
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(mockApiClient),
            currentUserProvider.overrideWithValue(testUser),
          ],
          child: const MaterialApp(
            home: Scaffold(
              body: DashboardScreen(),
            ),
          ),
        ),
      );

      // Loading state initially
      expect(find.byType(CircularProgressIndicator), findsOneWidget);

      // Pump asynchronous data load
      await tester.pumpAndSettle();

      // Check greeting text and role chip
      expect(find.text('Welcome, Jane Doe'), findsOneWidget);
      expect(find.text('ANALYST'), findsOneWidget);
    });

    testWidgets('DashboardScreen renders KPI cards with real API aggregated numbers', (tester) async {
      const testUser = User(
        id: 1,
        email: 'officer@city.gov',
        fullName: 'Officer Smith',
        role: User.roleTrafficOfficer,
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(mockApiClient),
            currentUserProvider.overrideWithValue(testUser),
          ],
          child: const MaterialApp(
            home: Scaffold(
              body: DashboardScreen(),
            ),
          ),
        ),
      );

      await tester.pumpAndSettle();

      // Total Junctions card (total = 24)
      expect(find.text('Total Junctions'), findsOneWidget);
      expect(find.text('24'), findsOneWidget);

      // Active Incidents card (reported: 2 + ack: 1 = 3)
      expect(find.text('Active Incidents'), findsOneWidget);
      expect(find.text('3'), findsOneWidget);

      // Signals online (1 signal in items)
      expect(find.text('Signals Online'), findsOneWidget);
      expect(find.text('1'), findsOneWidget);

      // Avg Congestion (from traffic summary = 54.0%)
      expect(find.text('Avg Congestion'), findsOneWidget);
      expect(find.text('54.0%'), findsOneWidget);
    });

    testWidgets('DashboardScreen renders Hotspots and Recent Incidents lists', (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(mockApiClient),
            currentUserProvider.overrideWithValue(
              const User(
                id: 1,
                email: 'test@city.gov',
                fullName: 'Test Operator',
                role: 'admin',
              ),
            ),
          ],
          child: const MaterialApp(
            home: Scaffold(
              body: DashboardScreen(),
            ),
          ),
        ),
      );

      await tester.pumpAndSettle();

      // Hotspot item
      expect(find.text('Corridor Peak North'), findsOneWidget);
      expect(find.text('83%'), findsOneWidget); // 82.5 rounded

      // Scroll to recent incidents if needed
      await tester.scrollUntilVisible(
        find.text('Stalled bus blocking curb lane'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      // Recent Incident item
      expect(find.text('Stalled bus blocking curb lane'), findsOneWidget);
    });

    testWidgets('Tapping KPI card triggers navigation callback', (tester) async {
      int? tappedIndex;

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(mockApiClient),
            currentUserProvider.overrideWithValue(
              const User(
                id: 1,
                email: 'test@city.gov',
                fullName: 'Test Operator',
                role: 'admin',
              ),
            ),
          ],
          child: MaterialApp(
            home: Scaffold(
              body: DashboardScreen(
                onNavigateTab: (index) {
                  tappedIndex = index;
                },
              ),
            ),
          ),
        ),
      );

      await tester.pumpAndSettle();

      // Tap on 'Total Junctions' card
      await tester.tap(find.text('Total Junctions'));
      await tester.pumpAndSettle();

      // Map tab is index 2
      expect(tappedIndex, 2);
    });
  });
}
