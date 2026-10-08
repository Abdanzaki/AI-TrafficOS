import 'dart:convert';

import 'package:ai_trafficos/services/realtime_protocol.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('RealtimeTopics and Role Mapping', () {
    test('all contains all required system topics', () {
      expect(RealtimeTopics.all, containsAll([
        'traffic.update',
        'congestion.change',
        'signal.change',
        'incident.created',
        'incident.updated',
        'emergency.created',
        'emergency.updated',
        'prediction.published',
        'control.decision',
        'notification.created',
        'system.status',
      ]));
    });

    test('analyst role does not receive emergency or control decision topics', () {
      final analystTopics = topicsForRole('analyst');
      expect(analystTopics, contains('traffic.update'));
      expect(analystTopics, contains('congestion.change'));
      expect(analystTopics, contains('signal.change'));
      expect(analystTopics, contains('incident.created'));
      expect(analystTopics, contains('incident.updated'));
      expect(analystTopics, contains('prediction.published'));
      expect(analystTopics, contains('notification.created'));
      expect(analystTopics, contains('system.status'));
      expect(analystTopics, isNot(contains(RealtimeTopics.emergencyCreated)));
      expect(analystTopics, isNot(contains(RealtimeTopics.emergencyUpdated)));
      expect(analystTopics, isNot(contains(RealtimeTopics.controlDecision)));
    });

    test('traffic_officer and admin roles receive all topics', () {
      expect(topicsForRole('admin'), equals(RealtimeTopics.all));
      expect(topicsForRole('traffic_officer'), equals(RealtimeTopics.all));
    });
  });

  group('RealtimeEvent Envelope', () {
    test('serializes and deserializes correctly', () {
      final now = DateTime.utc(2026, 10, 8, 12, 0, 0);
      final json = {
        'type': 'event',
        'event_id': 'evt-1234-uuid',
        'topic': 'traffic.update',
        'data': {'speed': 45.2, 'volume': 120},
        'timestamp': now.toIso8601String(),
        'last_event_id': 'evt-1233-uuid',
      };

      final event = RealtimeEvent.fromJson(json);
      expect(event.eventId, equals('evt-1234-uuid'));
      expect(event.topic, equals('traffic.update'));
      expect(event.data['speed'], equals(45.2));
      expect(event.timestamp, equals(now));
      expect(event.lastEventId, equals('evt-1233-uuid'));

      final encoded = event.toJson();
      expect(encoded['event_id'], equals('evt-1234-uuid'));
      expect(encoded['topic'], equals('traffic.update'));
      expect(encoded['last_event_id'], equals('evt-1233-uuid'));
    });

    test('handles fallback timestamp and empty data gracefully', () {
      final event = RealtimeEvent.fromJson({
        'event_id': 'fallback-id',
        'topic': 'system.status',
      });
      expect(event.eventId, equals('fallback-id'));
      expect(event.topic, equals('system.status'));
      expect(event.data, isEmpty);
      expect(event.timestamp, isNotNull);
    });
  });

  group('Frame Builders', () {
    test('buildSubscribeFrame produces valid JSON with event_types key', () {
      final frame = buildSubscribeFrame(['traffic.update', 'signal.change']);
      final decoded = jsonDecode(frame) as Map<String, dynamic>;
      expect(decoded['type'], equals('subscribe'));
      expect(decoded['event_types'], equals(['traffic.update', 'signal.change']));
      expect(decoded.containsKey('topics'), isFalse);
    });

    test('buildUnsubscribeFrame produces valid JSON with event_types key', () {
      final frame = buildUnsubscribeFrame(['traffic.update']);
      final decoded = jsonDecode(frame) as Map<String, dynamic>;
      expect(decoded['type'], equals('unsubscribe'));
      expect(decoded['event_types'], equals(['traffic.update']));
      expect(decoded.containsKey('topics'), isFalse);
    });

    test('buildPongFrame produces valid JSON with timestamp', () {
      final ts = DateTime.utc(2026, 10, 8, 12, 30);
      final frame = buildPongFrame(ts);
      final decoded = jsonDecode(frame) as Map<String, dynamic>;
      expect(decoded['type'], equals('pong'));
      expect(decoded['timestamp'], equals(ts.toIso8601String()));
    });

    test('buildResyncRequestFrame produces valid JSON', () {
      final frame = buildResyncRequestFrame('last-123');
      final decoded = jsonDecode(frame) as Map<String, dynamic>;
      expect(decoded['type'], equals('resync_request'));
      expect(decoded['last_event_id'], equals('last-123'));
    });
  });

  group('buildWebSocketUri', () {
    test('derives ws:// from http:// with token and event_types', () {
      final uri = buildWebSocketUri(
        apiBaseUrl: 'http://10.0.2.2:8000/api/v1',
        token: 'jwt-access-token',
        topics: ['traffic.update', 'congestion.change'],
      );

      expect(uri.scheme, equals('ws'));
      expect(uri.host, equals('10.0.2.2'));
      expect(uri.port, equals(8000));
      expect(uri.path, equals('/ws/v1/stream'));
      expect(uri.queryParameters['token'], equals('jwt-access-token'));
      expect(uri.queryParameters['event_types'], equals('traffic.update,congestion.change'));
      expect(uri.queryParameters.containsKey('topics'), isFalse);
      expect(uri.queryParameters.containsKey('last_event_id'), isFalse);
    });

    test('derives wss:// from https:// and attaches last_event_id', () {
      final uri = buildWebSocketUri(
        apiBaseUrl: 'https://traffic.city.gov/api/v1',
        token: 'secure-token',
        topics: ['all'],
        lastEventId: 'uuid-seq-99',
      );

      expect(uri.scheme, equals('wss'));
      expect(uri.host, equals('traffic.city.gov'));
      expect(uri.path, equals('/ws/v1/stream'));
      expect(uri.queryParameters['token'], equals('secure-token'));
      expect(uri.queryParameters['event_types'], equals('all'));
      expect(uri.queryParameters['last_event_id'], equals('uuid-seq-99'));
    });
  });
}
