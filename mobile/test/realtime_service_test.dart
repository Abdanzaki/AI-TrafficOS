// ignore_for_file: depend_on_referenced_packages

import 'dart:async';
import 'dart:convert';

import 'package:ai_trafficos/services/realtime_protocol.dart';
import 'package:ai_trafficos/services/realtime_service.dart';
import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:stream_channel/stream_channel.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

class FakeWebSocketSink implements WebSocketSink {
  FakeWebSocketSink({this.onClose});

  final void Function(int? code, String? reason)? onClose;
  final List<dynamic> sentMessages = <dynamic>[];
  final Completer<void> _doneCompleter = Completer<void>();
  int? closeCode;
  String? closeReason;

  @override
  void add(dynamic data) {
    sentMessages.add(data);
  }

  @override
  void addError(Object error, [StackTrace? stackTrace]) {}

  @override
  Future<void> addStream(Stream<dynamic> stream) async {
    await for (final data in stream) {
      add(data);
    }
  }

  @override
  Future<void> close([int? closeCode, String? closeReason]) async {
    this.closeCode = closeCode;
    this.closeReason = closeReason;
    onClose?.call(closeCode, closeReason);
    if (!_doneCompleter.isCompleted) {
      _doneCompleter.complete();
    }
  }

  @override
  Future<void> get done => _doneCompleter.future;
}

class FakeWebSocketChannel extends StreamChannelMixin<dynamic>
    implements WebSocketChannel {
  FakeWebSocketChannel(this.uri) {
    sink = FakeWebSocketSink(
      onClose: (code, reason) {
        _closeCode = code;
        _closeReason = reason;
        if (!incomingController.isClosed) {
          incomingController.close();
        }
      },
    );
  }

  final Uri uri;
  final StreamController<dynamic> incomingController =
      StreamController<dynamic>.broadcast();

  @override
  late final FakeWebSocketSink sink;

  int? _closeCode;
  String? _closeReason;

  @override
  Stream<dynamic> get stream => incomingController.stream;

  @override
  int? get closeCode => _closeCode;

  @override
  String? get closeReason => _closeReason;

  @override
  String? get protocol => null;

  @override
  Future<void> get ready => Future.value();

  void serverSend(dynamic message) {
    incomingController.add(message);
  }

  void serverClose({int? closeCode, String? closeReason}) {
    _closeCode = closeCode;
    _closeReason = closeReason;
    incomingController.close();
  }

  void serverError(dynamic error) {
    incomingController.addError(error);
  }
}

void main() {
  group('RealtimeService Tests', () {
    late List<FakeWebSocketChannel> channels;
    late List<Uri> connectedUris;

    setUp(() {
      channels = [];
      connectedUris = [];
    });

    FakeWebSocketChannel channelFactory(Uri uri) {
      connectedUris.add(uri);
      final ch = FakeWebSocketChannel(uri);
      channels.add(ch);
      return ch;
    }

    test('connect URL carries token, topics, and ws scheme', () async {
      final service = RealtimeService(
        apiBaseUrl: 'http://10.0.2.2:8000/api/v1',
        channelFactory: channelFactory,
        enableJitter: false,
      );

      await service.connect(
        jwt: 'test-jwt-token',
        topics: ['traffic.update', 'signal.change'],
        lastEventId: 'last-evt-uuid',
      );

      expect(connectedUris, hasLength(1));
      final uri = connectedUris.first;
      expect(uri.scheme, equals('ws'));
      expect(uri.host, equals('10.0.2.2'));
      expect(uri.port, equals(8000));
      expect(uri.path, equals('/ws/v1/stream'));
      expect(uri.queryParameters['token'], equals('test-jwt-token'));
      expect(uri.queryParameters['event_types'], equals('traffic.update,signal.change'));
      expect(uri.queryParameters['last_event_id'], equals('last-evt-uuid'));
      expect(service.status, equals(RealtimeConnectionStatus.connecting));

      // Simulate server connected frame
      channels.first.serverSend(jsonEncode({
        'type': 'connected',
        'server_time': '2026-10-08T12:00:00Z',
        'heartbeat_interval_ms': 15000,
      }));
      await Future<void>.delayed(Duration.zero);

      expect(service.status, equals(RealtimeConnectionStatus.connected));
      service.dispose();
    });

    test('close code 4401 stops retries and fires onAuthFailure', () {
      fakeAsync((async) {
        bool authFailed = false;
        final service = RealtimeService(
          apiBaseUrl: 'http://10.0.2.2:8000/api/v1',
          channelFactory: channelFactory,
          onAuthFailure: () {
            authFailed = true;
          },
          enableJitter: false,
        );

        service.connect(
          jwt: 'expired-jwt',
          topics: ['traffic.update'],
        );
        async.flushMicrotasks();

        expect(channels, hasLength(1));
        final ch = channels.first;

        // Server closes connection with 4401
        ch.serverClose(closeCode: 4401, closeReason: 'Session Expired');
        async.flushMicrotasks();

        expect(authFailed, isTrue);
        expect(service.status, equals(RealtimeConnectionStatus.disconnected));

        // Advance simulated time past backoff durations to confirm NO reconnect occurs
        async.elapse(const Duration(seconds: 60));
        expect(channels, hasLength(1)); // Still only 1 attempt

        service.dispose();
      });
    });

    test('backoff reconnect attempts with exponential timing in fakeAsync', () {
      fakeAsync((async) {
        final service = RealtimeService(
          apiBaseUrl: 'http://10.0.2.2:8000/api/v1',
          channelFactory: channelFactory,
          enableJitter: false,
        );

        service.connect(
          jwt: 'valid-jwt',
          topics: ['traffic.update'],
        );
        async.flushMicrotasks();

        expect(channels, hasLength(1));

        // First disconnect (unexpected drop)
        channels[0].serverClose(closeCode: 1006);
        async.flushMicrotasks();
        expect(service.status, equals(RealtimeConnectionStatus.error));

        // Attempt 1 backoff is 1s
        async.elapse(const Duration(milliseconds: 999));
        expect(channels, hasLength(1));
        async.elapse(const Duration(milliseconds: 1));
        expect(channels, hasLength(2));

        // Attempt 2 fails and drops
        channels[1].serverClose(closeCode: 1006);
        async.flushMicrotasks();

        // Attempt 2 backoff is 2s
        async.elapse(const Duration(milliseconds: 1999));
        expect(channels, hasLength(2));
        async.elapse(const Duration(milliseconds: 1));
        expect(channels, hasLength(3));

        // Attempt 3 fails and drops
        channels[2].serverClose(closeCode: 1006);
        async.flushMicrotasks();

        // Attempt 3 backoff is 4s
        async.elapse(const Duration(milliseconds: 3999));
        expect(channels, hasLength(3));
        async.elapse(const Duration(milliseconds: 1));
        expect(channels, hasLength(4));

        // Now server sends connected frame on channel 4
        channels[3].serverSend(jsonEncode({
          'type': 'connected',
          'heartbeat_interval_ms': 15000,
        }));
        async.flushMicrotasks();

        expect(service.status, equals(RealtimeConnectionStatus.connected));

        // Subsequent drop should reset attempts back to 1s
        channels[3].serverClose(closeCode: 1006);
        async.flushMicrotasks();

        async.elapse(const Duration(seconds: 1));
        expect(channels, hasLength(5));

        service.dispose();
      });
    });

    test('resync sends last_event_id and applies ordered resync events', () async {
      final service = RealtimeService(
        apiBaseUrl: 'http://10.0.2.2:8000/api/v1',
        channelFactory: channelFactory,
        enableJitter: false,
      );

      final receivedEvents = <RealtimeEvent>[];
      final sub = service.events.listen(receivedEvents.add);

      await service.connect(
        jwt: 'valid-jwt',
        topics: ['traffic.update'],
      );

      // Server sends first event
      channels[0].serverSend(jsonEncode({
        'type': 'event',
        'event_id': 'evt-100',
        'topic': 'traffic.update',
        'data': {'count': 10},
        'timestamp': '2026-10-08T10:00:00Z',
      }));
      await Future<void>.delayed(Duration.zero);

      expect(receivedEvents, hasLength(1));
      expect(service.lastEventId, equals('evt-100'));

      // Drop connection and reconnect
      channels[0].serverClose(closeCode: 1006);
      await service.reconnect();

      // Check reconnect URI includes last_event_id
      expect(connectedUris.last.queryParameters['last_event_id'], equals('evt-100'));

      // Server responds with resync bundle
      channels[1].serverSend(jsonEncode({
        'type': 'resync',
        'events': [
          {
            'type': 'event',
            'event_id': 'evt-101',
            'topic': 'traffic.update',
            'data': {'count': 11},
            'timestamp': '2026-10-08T10:00:05Z',
          },
          {
            'type': 'event',
            'event_id': 'evt-102',
            'topic': 'traffic.update',
            'data': {'count': 12},
            'timestamp': '2026-10-08T10:00:10Z',
          },
        ],
        'last_event_id': 'evt-102',
      }));
      await Future<void>.delayed(Duration.zero);

      expect(receivedEvents, hasLength(3));
      expect(receivedEvents[1].eventId, equals('evt-101'));
      expect(receivedEvents[2].eventId, equals('evt-102'));
      expect(service.lastEventId, equals('evt-102'));

      await sub.cancel();
      service.dispose();
    });

    test('dedupe drops duplicate event_id', () async {
      final service = RealtimeService(
        apiBaseUrl: 'http://10.0.2.2:8000/api/v1',
        channelFactory: channelFactory,
        enableJitter: false,
      );

      final receivedEvents = <RealtimeEvent>[];
      final sub = service.events.listen(receivedEvents.add);

      await service.connect(
        jwt: 'valid-jwt',
        topics: ['traffic.update'],
      );

      final eventPayload = jsonEncode({
        'type': 'event',
        'event_id': 'duplicate-uuid',
        'topic': 'traffic.update',
        'data': {'speed': 60},
        'timestamp': '2026-10-08T10:00:00Z',
      });

      // Send same event twice
      channels[0].serverSend(eventPayload);
      channels[0].serverSend(eventPayload);
      await Future<void>.delayed(Duration.zero);

      expect(receivedEvents, hasLength(1));
      expect(receivedEvents.first.eventId, equals('duplicate-uuid'));

      await sub.cancel();
      service.dispose();
    });

    test('stale detection after missed heartbeats using injectable clock', () async {
      var simulatedTime = DateTime.utc(2026, 10, 8, 12, 0, 0);

      final service = RealtimeService(
        apiBaseUrl: 'http://10.0.2.2:8000/api/v1',
        channelFactory: channelFactory,
        clock: () => simulatedTime,
        enableJitter: false,
      );

      await service.connect(
        jwt: 'valid-jwt',
        topics: ['traffic.update'],
      );

      channels[0].serverSend(jsonEncode({
        'type': 'connected',
        'heartbeat_interval_ms': 15000, // 15 seconds -> 2x = 30 seconds threshold
      }));
      await Future<void>.delayed(Duration.zero);

      // Initially, no events on topic -> not stale
      expect(service.isTopicStale('traffic.update'), isFalse);
      expect(service.isStale, isFalse);

      // Event arrives at T0
      channels[0].serverSend(jsonEncode({
        'type': 'event',
        'event_id': 'evt-stale-test',
        'topic': 'traffic.update',
        'data': {},
        'timestamp': simulatedTime.toIso8601String(),
      }));
      await Future<void>.delayed(Duration.zero);

      expect(service.isTopicStale('traffic.update'), isFalse);
      expect(service.isStale, isFalse);
      expect(service.lastEventAt, equals(simulatedTime));

      // Advance time by 20s (< 30s threshold)
      simulatedTime = simulatedTime.add(const Duration(seconds: 20));
      expect(service.isTopicStale('traffic.update'), isFalse);
      expect(service.isStale, isFalse);

      // Advance time past 30s (> 2 * heartbeat)
      simulatedTime = simulatedTime.add(const Duration(seconds: 15)); // total 35s
      expect(service.isTopicStale('traffic.update'), isTrue);
      expect(service.isStale, isTrue);

      service.dispose();
    });

    test('subscribe and unsubscribe frames sent when connected', () async {
      final service = RealtimeService(
        apiBaseUrl: 'http://10.0.2.2:8000/api/v1',
        channelFactory: channelFactory,
        enableJitter: false,
      );

      await service.connect(
        jwt: 'valid-jwt',
        topics: ['traffic.update'],
      );

      channels[0].serverSend(jsonEncode({'type': 'connected'}));
      await Future<void>.delayed(Duration.zero);

      service.subscribe(['congestion.change']);
      expect(channels[0].sink.sentMessages, hasLength(1));
      final subFrame = jsonDecode(channels[0].sink.sentMessages[0] as String);
      expect(subFrame['type'], equals('subscribe'));
      expect(subFrame['event_types'], equals(['congestion.change']));

      service.unsubscribe(['traffic.update']);
      expect(channels[0].sink.sentMessages, hasLength(2));
      final unsubFrame = jsonDecode(channels[0].sink.sentMessages[1] as String);
      expect(unsubFrame['type'], equals('unsubscribe'));
      expect(unsubFrame['event_types'], equals(['traffic.update']));

      service.dispose();
    });

    test('heartbeat ping from server elicits pong reply', () async {
      final service = RealtimeService(
        apiBaseUrl: 'http://10.0.2.2:8000/api/v1',
        channelFactory: channelFactory,
        enableJitter: false,
      );

      await service.connect(
        jwt: 'valid-jwt',
        topics: ['traffic.update'],
      );

      channels[0].serverSend(jsonEncode({
        'type': 'heartbeat',
        'timestamp': '2026-10-08T12:00:00Z',
      }));
      await Future<void>.delayed(Duration.zero);

      expect(channels[0].sink.sentMessages, hasLength(1));
      final pong = jsonDecode(channels[0].sink.sentMessages[0] as String);
      expect(pong['type'], equals('pong'));
      expect(pong.containsKey('timestamp'), isTrue);

      service.dispose();
    });

    test('malformed frames are ignored and do not crash or emit error', () async {
      final service = RealtimeService(
        apiBaseUrl: 'http://10.0.2.2:8000/api/v1',
        channelFactory: channelFactory,
        enableJitter: false,
      );

      final receivedEvents = <RealtimeEvent>[];
      final sub = service.events.listen(receivedEvents.add);

      await service.connect(
        jwt: 'valid-jwt',
        topics: ['traffic.update'],
      );

      // Send corrupted non-json strings, non-map json, and incomplete frames
      channels[0].serverSend('invalid {json string}');
      channels[0].serverSend('[1, 2, 3]');
      channels[0].serverSend(jsonEncode({'unknown_key': 123}));
      await Future<void>.delayed(Duration.zero);

      // Now send valid event to confirm stream is completely healthy
      channels[0].serverSend(jsonEncode({
        'type': 'event',
        'event_id': 'valid-after-junk',
        'topic': 'traffic.update',
        'data': {'ok': true},
        'timestamp': '2026-10-08T12:00:00Z',
      }));
      await Future<void>.delayed(Duration.zero);

      expect(receivedEvents, hasLength(1));
      expect(receivedEvents.first.eventId, equals('valid-after-junk'));

      await sub.cancel();
      service.dispose();
    });

    test('per-topic streams only receive matching topics', () async {
      final service = RealtimeService(
        apiBaseUrl: 'http://10.0.2.2:8000/api/v1',
        channelFactory: channelFactory,
        enableJitter: false,
      );

      final trafficEvents = <RealtimeEvent>[];
      final signalEvents = <RealtimeEvent>[];

      final trafficSub = service.streamFor('traffic.update').listen(trafficEvents.add);
      final signalSub = service.streamFor('signal.change').listen(signalEvents.add);

      await service.connect(
        jwt: 'valid-jwt',
        topics: ['traffic.update', 'signal.change'],
      );

      // Send event on traffic.update
      channels[0].serverSend(jsonEncode({
        'type': 'event',
        'event_id': 'evt-traffic',
        'topic': 'traffic.update',
        'data': {},
        'timestamp': '2026-10-08T12:00:00Z',
      }));
      // Send event on signal.change
      channels[0].serverSend(jsonEncode({
        'type': 'event',
        'event_id': 'evt-signal',
        'topic': 'signal.change',
        'data': {},
        'timestamp': '2026-10-08T12:00:01Z',
      }));
      await Future<void>.delayed(Duration.zero);

      expect(trafficEvents, hasLength(1));
      expect(trafficEvents.first.eventId, equals('evt-traffic'));

      expect(signalEvents, hasLength(1));
      expect(signalEvents.first.eventId, equals('evt-signal'));

      await trafficSub.cancel();
      await signalSub.cancel();
      service.dispose();
    });

    test('wildcard stream matching for incident.*', () async {
      final service = RealtimeService(
        apiBaseUrl: 'http://10.0.2.2:8000/api/v1',
        channelFactory: channelFactory,
        enableJitter: false,
      );

      final incidentEvents = <RealtimeEvent>[];
      final sub = service.streamFor('incident.*').listen(incidentEvents.add);

      await service.connect(
        jwt: 'valid-jwt',
        topics: ['incident.created', 'incident.updated'],
      );

      channels[0].serverSend(jsonEncode({
        'type': 'event',
        'event_id': 'inc-created',
        'topic': 'incident.created',
        'data': {},
        'timestamp': '2026-10-08T12:00:00Z',
      }));
      channels[0].serverSend(jsonEncode({
        'type': 'event',
        'event_id': 'inc-updated',
        'topic': 'incident.updated',
        'data': {},
        'timestamp': '2026-10-08T12:00:01Z',
      }));
      channels[0].serverSend(jsonEncode({
        'type': 'event',
        'event_id': 'other-topic',
        'topic': 'signal.change',
        'data': {},
        'timestamp': '2026-10-08T12:00:02Z',
      }));
      await Future<void>.delayed(Duration.zero);

      expect(incidentEvents, hasLength(2));
      expect(incidentEvents[0].eventId, equals('inc-created'));
      expect(incidentEvents[1].eventId, equals('inc-updated'));

      await sub.cancel();
      service.dispose();
    });
  });
}
