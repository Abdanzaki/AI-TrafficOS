import 'dart:convert';
import 'package:ai_trafficos/screens/analytics_screen.dart';
import 'package:ai_trafficos/services/analytics_service.dart';
import 'package:ai_trafficos/services/api_client.dart';
import 'package:ai_trafficos/services/auth_service.dart';
import 'package:ai_trafficos/services/traffic_service.dart';
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
  group('AnalyticsService Unit Tests', () {
    test('getTrafficSummary delegates to trafficService and returns parsed buckets', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/analytics/traffic-summary');
        expect(request.url.queryParameters['bucket'], 'hour');

        return http.Response(
          jsonEncode([
            {
              'bucket': '2026-10-07T12:00:00Z',
              'avg_vehicle_count': 142.5,
              'avg_speed': 45.2,
              'avg_congestion': 58.0,
              'record_count': 120,
            }
          ]),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);
      final trafficService = TrafficService(apiClient: apiClient);
      final analyticsService = AnalyticsService(trafficService: trafficService);

      final buckets = await analyticsService.getTrafficSummary(bucket: 'hour');
      expect(buckets.length, 1);
      expect(buckets.first.avgVehicleCount, 142.5);
      expect(buckets.first.avgSpeed, 45.2);
      expect(buckets.first.avgCongestion, 58.0);
    });

    test('getHotspots delegates to trafficService and returns parsed hotspots', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/analytics/congestion-hotspots');
        expect(request.url.queryParameters['limit'], '5');

        return http.Response(
          jsonEncode([
            {
              'intersection_id': 10,
              'name': 'Broadway & 7th',
              'code': 'INT-10',
              'avg_congestion_level': 78.4,
              'record_count': 250,
            }
          ]),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);
      final trafficService = TrafficService(apiClient: apiClient);
      final analyticsService = AnalyticsService(trafficService: trafficService);

      final hotspots = await analyticsService.getHotspots(limit: 5);
      expect(hotspots.length, 1);
      expect(hotspots.first.name, 'Broadway & 7th');
      expect(hotspots.first.avgCongestionLevel, 78.4);
    });

    test('getIncidentsSummary delegates to trafficService and calculates activeCount', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/analytics/incidents-summary');

        return http.Response(
          jsonEncode({
            'total': 15,
            'by_severity': {'critical': 3, 'high': 5, 'medium': 4, 'low': 3},
            'by_status': {'reported': 4, 'acknowledged': 6, 'resolved': 5},
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);
      final trafficService = TrafficService(apiClient: apiClient);
      final analyticsService = AnalyticsService(trafficService: trafficService);

      final summary = await analyticsService.getIncidentsSummary();
      expect(summary.total, 15);
      expect(summary.activeCount, 10);
      expect(summary.bySeverity['critical'], 3);
    });
  });

  group('AnalyticsScreen Widget Tests', () {
    testWidgets('renders KPI metrics cards, volume chart, hotspots, and incidents distribution', (tester) async {
      await tester.binding.setSurfaceSize(const Size(800, 1600));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      final mockClient = MockClient((request) async {
        if (request.url.path.contains('/traffic-summary')) {
          return http.Response(
            jsonEncode([
              {
                'bucket': '2026-10-07T12:00:00Z',
                'avg_vehicle_count': 150.0,
                'avg_speed': 42.5,
                'avg_congestion': 64.0,
                'record_count': 200,
              },
              {
                'bucket': '2026-10-07T13:00:00Z',
                'avg_vehicle_count': 180.0,
                'avg_speed': 38.0,
                'avg_congestion': 72.0,
                'record_count': 240,
              },
            ]),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        if (request.url.path.contains('/congestion-hotspots')) {
          return http.Response(
            jsonEncode([
              {
                'intersection_id': 1,
                'name': 'Main & 1st',
                'code': 'INT-01',
                'avg_congestion_level': 85.0,
                'record_count': 300,
              },
              {
                'intersection_id': 2,
                'name': 'Market & 4th',
                'code': 'INT-02',
                'avg_congestion_level': 65.0,
                'record_count': 280,
              },
            ]),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        if (request.url.path.contains('/incidents-summary')) {
          return http.Response(
            jsonEncode({
              'total': 12,
              'by_severity': {'critical': 2, 'high': 4, 'medium': 6},
              'by_status': {'reported': 3, 'acknowledged': 4, 'resolved': 5},
            }),
            200,
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
            home: AnalyticsScreen(),
          ),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('Citywide Traffic Analytics'), findsOneWidget);
      expect(find.text('Telemetry Aggregation'), findsOneWidget);
      expect(find.text('Active Incidents'), findsOneWidget);
      expect(find.text('7 of 12'), findsOneWidget);
      expect(find.text('Network Average Speed'), findsOneWidget);
      expect(find.text('40.3 km/h'), findsOneWidget);
      expect(find.text('Peak Congestion Index'), findsOneWidget);
      expect(find.text('72%'), findsOneWidget);
      expect(find.text('Volume Trend & Congestion Curve'), findsOneWidget);
      expect(find.text('Top Congestion Hotspots'), findsOneWidget);
      expect(find.text('Main & 1st'), findsOneWidget);
      expect(find.text('85.0%'), findsOneWidget);
      expect(find.text('Market & 4th'), findsOneWidget);
      expect(find.text('65.0%'), findsOneWidget);
      expect(find.text('Incidents Distribution'), findsOneWidget);
      expect(find.text('12 Total'), findsOneWidget);
    });
  });
}
