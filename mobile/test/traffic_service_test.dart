import 'dart:convert';
import 'package:ai_trafficos/services/api_client.dart';
import 'package:ai_trafficos/services/traffic_service.dart';
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
  group('TrafficService Tests', () {
    test('getTrafficSummary successfully parses bucket list and properties', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/analytics/traffic-summary');
        expect(request.url.queryParameters['bucket'], 'hour');

        final payload = [
          {
            'bucket': '2026-10-07T12:00:00Z',
            'avg_vehicle_count': 142.5,
            'avg_speed': 48.2,
            'avg_congestion': 35.8,
            'record_count': 30,
          },
          {
            'bucket': '2026-10-07T13:00:00Z',
            'avg_vehicle_count': 210.0,
            'avg_speed_kmh': 42.0,
            'avg_congestion_level': 58.4,
            'record_count': 45,
          },
        ];

        return http.Response(
          jsonEncode(payload),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);
      final service = TrafficService(apiClient: apiClient);

      final buckets = await service.getTrafficSummary(bucket: 'hour');

      expect(buckets.length, 2);
      expect(buckets.first.avgVehicleCount, 142.5);
      expect(buckets.first.avgSpeed, 48.2);
      expect(buckets.first.avgCongestion, 35.8);
      expect(buckets.first.recordCount, 30);
      expect(buckets.last.avgSpeed, 42.0);
      expect(buckets.last.avgCongestion, 58.4);
    });

    test('getHotspots successfully parses congestion hotspots', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/analytics/congestion-hotspots');
        expect(request.url.queryParameters['limit'], '5');

        final payload = [
          {
            'intersection_id': 101,
            'name': 'Main St & 4th Ave',
            'code': 'INT-0101',
            'avg_congestion_level': 88.5,
            'record_count': 120,
          },
          {
            'intersection_id': 102,
            'name': 'Broadway & 7th St',
            'code': 'INT-0102',
            'avg_congestion': 72.0,
            'record_count': 95,
          },
        ];

        return http.Response(
          jsonEncode(payload),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);
      final service = TrafficService(apiClient: apiClient);

      final hotspots = await service.getHotspots(limit: 5);

      expect(hotspots.length, 2);
      expect(hotspots[0].intersectionId, 101);
      expect(hotspots[0].name, 'Main St & 4th Ave');
      expect(hotspots[0].code, 'INT-0101');
      expect(hotspots[0].avgCongestionLevel, 88.5);
      expect(hotspots[0].recordCount, 120);
      expect(hotspots[1].avgCongestionLevel, 72.0);
    });

    test('getIncidentsSummary parses aggregations and calculates activeCount', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/analytics/incidents-summary');

        final payload = {
          'total': 15,
          'by_severity': {
            'low': 4,
            'medium': 6,
            'high': 3,
            'critical': 2,
          },
          'by_status': {
            'reported': 5,
            'acknowledged': 3,
            'resolved': 7,
          },
        };

        return http.Response(
          jsonEncode(payload),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);
      final service = TrafficService(apiClient: apiClient);

      final summary = await service.getIncidentsSummary();

      expect(summary.total, 15);
      expect(summary.bySeverity['critical'], 2);
      expect(summary.byStatus['reported'], 5);
      expect(summary.activeCount, 8);
    });

    test('getTrafficRecords handles pagination and parses records', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/traffic-records');
        expect(request.url.queryParameters['page'], '2');
        expect(request.url.queryParameters['per_page'], '15');
        expect(request.url.queryParameters['intersection_id'], '42');

        final payload = {
          'items': [
            {
              'id': 201,
              'intersection_id': 42,
              'lane_id': 5,
              'recorded_at': '2026-10-07T14:30:00Z',
              'vehicle_count': 18,
              'avg_speed_kmh': 45.5,
              'congestion_level': 25,
              'source': 'camera',
              'created_at': '2026-10-07T14:30:01Z',
              'updated_at': '2026-10-07T14:30:01Z',
            }
          ],
          'total': 31,
          'page': 2,
          'per_page': 15,
          'pages': 3,
        };

        return http.Response(
          jsonEncode(payload),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);
      final service = TrafficService(apiClient: apiClient);

      final paged = await service.getTrafficRecords(
        intersectionId: 42,
        page: 2,
        perPage: 15,
      );

      expect(paged.page, 2);
      expect(paged.perPage, 15);
      expect(paged.total, 31);
      expect(paged.pages, 3);
      expect(paged.items.length, 1);
      expect(paged.items.first.id, 201);
      expect(paged.items.first.vehicleCount, 18);
      expect(paged.items.first.avgSpeedKmh, 45.5);
      expect(paged.items.first.source, 'camera');
    });

    test('getVehicleEvents parses paginated vehicle detection events', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/vehicle-events');

        final payload = {
          'items': [
            {
              'id': 301,
              'intersection_id': 10,
              'lane_id': 2,
              'event_type': 'detection',
              'vehicle_type': 'truck',
              'speed_kmh': 52.0,
              'direction': 'northbound',
              'confidence': 0.94,
              'detected_at': '2026-10-07T15:00:00Z',
              'created_at': '2026-10-07T15:00:00Z',
              'updated_at': '2026-10-07T15:00:00Z',
            }
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
      final service = TrafficService(apiClient: apiClient);

      final paged = await service.getVehicleEvents();

      expect(paged.items.length, 1);
      final event = paged.items.first;
      expect(event.id, 301);
      expect(event.vehicleType, 'truck');
      expect(event.speedKmh, 52.0);
      expect(event.direction, 'northbound');
      expect(event.confidence, 0.94);
    });

    test('getCongestionRanking parses corridor rankings from routing API', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/v1/routing/congestion-ranking');
        expect(request.url.queryParameters['limit'], '5');

        final payload = [
          {
            'road_id': 12,
            'road_name': 'Grand Avenue Arterial',
            'from_intersection_id': 1,
            'to_intersection_id': 2,
            'congestion_level': 85.0,
            'rank': 1,
          }
        ];

        return http.Response(
          jsonEncode(payload),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);
      final service = TrafficService(apiClient: apiClient);

      final ranking = await service.getCongestionRanking(limit: 5);

      expect(ranking.length, 1);
      expect(ranking.first.roadName, 'Grand Avenue Arterial');
      expect(ranking.first.congestionLevel, 85.0);
      expect(ranking.first.rank, 1);
    });

    test('error mapping translates server error into typed ApiException', () async {
      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode({'detail': 'Sensor database connection pool exhausted'}),
          500,
          headers: {'content-type': 'application/json'},
        );
      });

      final apiClient = createTestClient(mockClient);
      final service = TrafficService(apiClient: apiClient);

      expect(
        () => service.getTrafficSummary(),
        throwsA(isA<ApiException>().having(
          (e) => e.statusCode,
          'statusCode',
          500,
        ).having(
          (e) => e.message,
          'message',
          contains('Sensor database connection pool exhausted'),
        )),
      );
    });
  });
}
