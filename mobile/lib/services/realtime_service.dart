import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../core/app_config.dart';
import 'realtime_protocol.dart';

/// Connection state machine for real-time WebSocket communication.
enum RealtimeConnectionStatus {
  disconnected,
  connecting,
  connected,
  error,
}

/// Factory signature for constructing [WebSocketChannel] instances.
typedef WebSocketChannelFactory = WebSocketChannel Function(Uri uri);

/// Primary real-time synchronization service for AI TrafficOS mobile clients.
///
/// Features:
/// - Injectable [WebSocketChannelFactory] for decoupled testing.
/// - Exponential backoff reconnection with randomized jitter (1s - 30s cap).
/// - Resync support via `last_event_id` with strictly ordered event application.
/// - Client-side LRU deduplication of event IDs (capped at 1,000).
/// - Per-topic stale tracking (`isTopicStale`) based on heartbeat interval threshold.
/// - Ping/pong keepalive management.
/// - Authentication termination on HTTP 4401 close code without reconnect retries.
/// - Broadcast [Stream] for real-time events and granular per-topic filtering.
class RealtimeService {
  RealtimeService({
    String? apiBaseUrl,
    WebSocketChannelFactory? channelFactory,
    FlutterSecureStorage? storage,
    this.onAuthFailure,
    DateTime Function()? clock,
    this._enableJitter = true,
    Random? random,
  })  : _apiBaseUrl = apiBaseUrl ?? AppConfig.apiBaseUrl,
        _channelFactory = channelFactory ?? WebSocketChannel.connect,
        _storage = storage ?? const FlutterSecureStorage(),
        _clock = clock ?? DateTime.now,
        _random = random ?? Random();

  final String _apiBaseUrl;
  final WebSocketChannelFactory _channelFactory;
  final FlutterSecureStorage _storage;
  final DateTime Function() _clock;
  final bool _enableJitter;
  final Random _random;

  /// Callback fired when backend terminates connection with 4401 Unauthorized.
  VoidCallback? onAuthFailure;

  // Active channel and subscription state
  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _channelSubscription;
  String? _token;
  final Set<String> _subscribedTopics = <String>{};
  String? _lastEventId;
  DateTime? _lastEventAt;
  Duration _heartbeatInterval = const Duration(milliseconds: 15000);

  // Stale detection & deduplication structures
  final Map<String, DateTime> _topicLastReceivedAt = <String, DateTime>{};
  final LinkedHashSet<String> _seenEventIds = LinkedHashSet<String>();
  static const int _maxSeenEventIds = 1000;

  // Reconnection state
  Timer? _reconnectTimer;
  int _reconnectAttempts = 0;
  bool _isExplicitlyDisconnected = false;
  bool _isDisposed = false;

  // Status & Event Streams
  final StreamController<RealtimeEvent> _eventController =
      StreamController<RealtimeEvent>.broadcast();
  final StreamController<RealtimeConnectionStatus> _statusController =
      StreamController<RealtimeConnectionStatus>.broadcast();
  final ValueNotifier<RealtimeConnectionStatus> _statusNotifier =
      ValueNotifier<RealtimeConnectionStatus>(RealtimeConnectionStatus.disconnected);

  RealtimeConnectionStatus _status = RealtimeConnectionStatus.disconnected;

  /// Current real-time connection status.
  RealtimeConnectionStatus get status => _status;

  /// ValueNotifier exposing reactive status updates for Flutter widgets.
  ValueListenable<RealtimeConnectionStatus> get statusListenable => _statusNotifier;

  /// Stream of connection status transitions.
  Stream<RealtimeConnectionStatus> get statusStream => _statusController.stream;

  /// Broadcast stream of all received real-time events.
  Stream<RealtimeEvent> get events => _eventController.stream;

  /// Timestamp when the most recent real-time event was received.
  DateTime? get lastEventAt => _lastEventAt;

  /// Negotiated or default heartbeat interval from server.
  Duration get heartbeatInterval => _heartbeatInterval;

  /// Currently subscribed topic list.
  List<String> get subscribedTopics => List.unmodifiable(_subscribedTopics);

  /// The most recent event ID received by this client.
  String? get lastEventId => _lastEventId;

  /// Filtered stream for a specific topic (or wildcard suffix `.*`).
  Stream<RealtimeEvent> streamFor(String topic) {
    if (topic.endsWith('.*')) {
      final prefix = topic.substring(0, topic.length - 2);
      return events.where((e) => e.topic.startsWith(prefix));
    }
    return events.where((e) => e.topic == topic);
  }

  /// Checks whether telemetry for a specific topic has exceeded 2x the heartbeat interval.
  bool isTopicStale(String topic) {
    final lastReceived = _topicLastReceivedAt[topic];
    if (lastReceived == null) {
      return false;
    }
    final elapsed = _clock().difference(lastReceived);
    return elapsed > (_heartbeatInterval * 2);
  }

  /// Whether overall connected telemetry is stale (no events received within 2x heartbeat).
  bool get isStale {
    if (_status != RealtimeConnectionStatus.connected) return false;
    if (_lastEventAt == null) return false;
    return _clock().difference(_lastEventAt!) > (_heartbeatInterval * 2);
  }

  /// Initiates a real-time connection with given [jwt] and initial [topics].
  Future<void> connect({
    required String jwt,
    required List<String> topics,
    String? lastEventId,
  }) async {
    _token = jwt;
    _subscribedTopics
      ..clear()
      ..addAll(topics);
    if (lastEventId != null) {
      _lastEventId = lastEventId;
    }
    _isExplicitlyDisconnected = false;
    _reconnectAttempts = 0;
    _stopReconnectTimer();

    await _establishConnection();
  }

  /// Disconnects the active WebSocket stream and halts automatic reconnection.
  void disconnect() {
    _isExplicitlyDisconnected = true;
    _stopReconnectTimer();
    _closeChannel();
    _updateStatus(RealtimeConnectionStatus.disconnected);
  }

  /// Re-establishes the connection using cached token, topics, and sequence id.
  Future<void> reconnect() async {
    _isExplicitlyDisconnected = false;
    _stopReconnectTimer();
    _closeChannel();
    await _establishConnection();
  }

  /// Re-authenticates and reconnects following token refresh.
  Future<void> reconnectWithToken(String jwt) async {
    _token = jwt;
    await reconnect();
  }

  /// Reads stored access JWT from device secure storage.
  Future<String?> getStoredToken() async {
    return await _storage.read(key: AppConfig.accessTokenKey);
  }

  /// Dynamically subscribes to additional topics on the active connection.
  void subscribe(List<String> topics) {
    final newTopics = topics.where((t) => !_subscribedTopics.contains(t)).toList();
    if (newTopics.isEmpty) return;

    _subscribedTopics.addAll(newTopics);
    if (_status == RealtimeConnectionStatus.connected) {
      try {
        _channel?.sink.add(buildSubscribeFrame(newTopics));
      } catch (e) {
        debugPrint('RealtimeService: Failed to send subscribe frame: $e');
      }
    }
  }

  /// Dynamically unsubscribes from topics on the active connection.
  void unsubscribe(List<String> topics) {
    final toRemove = topics.where((t) => _subscribedTopics.contains(t)).toList();
    if (toRemove.isEmpty) return;

    _subscribedTopics.removeAll(toRemove);
    if (_status == RealtimeConnectionStatus.connected) {
      try {
        _channel?.sink.add(buildUnsubscribeFrame(toRemove));
      } catch (e) {
        debugPrint('RealtimeService: Failed to send unsubscribe frame: $e');
      }
    }
  }

  /// Requests a sequence resync from the backend beginning after [lastEventId].
  void requestResync([String? lastEventId]) {
    final targetId = lastEventId ?? _lastEventId;
    if (targetId != null && _status == RealtimeConnectionStatus.connected) {
      try {
        _channel?.sink.add(buildResyncRequestFrame(targetId));
      } catch (e) {
        debugPrint('RealtimeService: Failed to send resync request frame: $e');
      }
    }
  }

  /// Internal connection routine.
  Future<void> _establishConnection() async {
    if (_isDisposed || _isExplicitlyDisconnected) return;

    final token = _token ?? await getStoredToken();
    if (token == null || token.trim().isEmpty) {
      _updateStatus(RealtimeConnectionStatus.disconnected);
      return;
    }

    _updateStatus(RealtimeConnectionStatus.connecting);

    try {
      final uri = buildWebSocketUri(
        apiBaseUrl: _apiBaseUrl,
        token: token,
        topics: _subscribedTopics.toList(),
        lastEventId: _lastEventId,
      );

      _channel = _channelFactory(uri);
      _channelSubscription = _channel!.stream.listen(
        _handleMessage,
        onDone: _handleChannelDone,
        onError: _handleChannelError,
        cancelOnError: true,
      );
    } catch (e) {
      debugPrint('RealtimeService: Connection initiation failed: $e');
      _updateStatus(RealtimeConnectionStatus.error);
      _scheduleReconnect();
    }
  }

  /// Processes raw incoming frames from server.
  void _handleMessage(dynamic message) {
    if (message is! String) return;

    try {
      final dynamic decoded = jsonDecode(message);
      if (decoded is! Map<String, dynamic>) return;
      _processFrame(decoded);
    } catch (e) {
      // Malformed frames are logged and safely ignored; never throw into stream
      debugPrint('RealtimeService: Malformed frame ignored: $e');
    }
  }

  /// Evaluates typed protocol frame actions.
  void _processFrame(Map<String, dynamic> frame) {
    final type = frame['type'] as String?;
    if (type == null) return;

    switch (type) {
      case 'connected':
      case 'connection.established':
        if (frame['heartbeat_interval_ms'] is int) {
          _heartbeatInterval =
              Duration(milliseconds: frame['heartbeat_interval_ms'] as int);
        }
        _reconnectAttempts = 0;
        _updateStatus(RealtimeConnectionStatus.connected);
        break;

      case 'event':
        final event = RealtimeEvent.fromJson(frame);
        if (_recordAndCheckDuplicate(event.eventId)) {
          // Drop duplicate event
          break;
        }
        _lastEventId = event.eventId;
        _lastEventAt = event.timestamp;
        _topicLastReceivedAt[event.topic] = _clock();
        _eventController.add(event);
        break;

      case 'heartbeat':
        try {
          _channel?.sink.add(buildPongFrame(_clock()));
        } catch (e) {
          debugPrint('RealtimeService: Failed to reply with pong: $e');
        }
        break;

      case 'resync':
      case 'resync.complete':
        final rawEvents = frame['events'];
        if (rawEvents is List) {
          for (final raw in rawEvents) {
            if (raw is Map<String, dynamic>) {
              final event = RealtimeEvent.fromJson(raw);
              if (!_recordAndCheckDuplicate(event.eventId)) {
                _lastEventId = event.eventId;
                _lastEventAt = event.timestamp;
                _topicLastReceivedAt[event.topic] = _clock();
                _eventController.add(event);
              }
            }
          }
        }
        final resyncLastId = frame['last_event_id'] as String?;
        if (resyncLastId != null && resyncLastId.isNotEmpty) {
          _lastEventId = resyncLastId;
        }
        break;

      case 'auth.expired':
        _stopReconnectTimer();
        _closeChannel();
        _updateStatus(RealtimeConnectionStatus.disconnected);
        onAuthFailure?.call();
        break;

      case 'error':
        final code = frame['code'] as String?;
        debugPrint('RealtimeService: Server error frame received ($code): ${frame['message']}');
        if (code == 'UNAUTHORIZED' || code == 'FORBIDDEN') {
          // Check if auth expired
          if (code == 'UNAUTHORIZED') {
            _stopReconnectTimer();
            _closeChannel();
            _updateStatus(RealtimeConnectionStatus.disconnected);
            onAuthFailure?.call();
          }
        }
        break;

      default:
        // Handle backend event frames where "type" is the topic itself (e.g. "traffic.update")
        if (frame.containsKey('event_id') &&
            (frame.containsKey('payload') || frame.containsKey('data'))) {
          final event = RealtimeEvent.fromJson(frame);
          if (_recordAndCheckDuplicate(event.eventId)) {
            break;
          }
          _lastEventId = event.eventId;
          _lastEventAt = event.timestamp;
          _topicLastReceivedAt[event.topic] = _clock();
          _eventController.add(event);
        }
        break;
    }
  }

  /// Deduplication check using LRU-bounded set.
  bool _recordAndCheckDuplicate(String eventId) {
    if (eventId.isEmpty) return false;
    if (_seenEventIds.contains(eventId)) {
      return true;
    }
    _seenEventIds.add(eventId);
    if (_seenEventIds.length > _maxSeenEventIds) {
      _seenEventIds.remove(_seenEventIds.first);
    }
    return false;
  }

  /// Channel termination handler checking for 4401 auth revocation.
  void _handleChannelDone() {
    final closeCode = _channel?.closeCode;
    _closeChannel();

    if (closeCode == 4401) {
      debugPrint('RealtimeService: Received 4401 close code. Halting reconnection.');
      _stopReconnectTimer();
      _updateStatus(RealtimeConnectionStatus.disconnected);
      onAuthFailure?.call();
      return;
    }

    if (!_isExplicitlyDisconnected && !_isDisposed) {
      _updateStatus(RealtimeConnectionStatus.error);
      _scheduleReconnect();
    } else {
      _updateStatus(RealtimeConnectionStatus.disconnected);
    }
  }

  /// Channel error handler.
  void _handleChannelError(dynamic error) {
    debugPrint('RealtimeService: WebSocket channel stream error: $error');
    final closeCode = _channel?.closeCode;
    _closeChannel();

    if (closeCode == 4401) {
      _stopReconnectTimer();
      _updateStatus(RealtimeConnectionStatus.disconnected);
      onAuthFailure?.call();
      return;
    }

    if (!_isExplicitlyDisconnected && !_isDisposed) {
      _updateStatus(RealtimeConnectionStatus.error);
      _scheduleReconnect();
    } else {
      _updateStatus(RealtimeConnectionStatus.disconnected);
    }
  }

  /// Schedules next reconnection attempt with exponential backoff and jitter.
  void _scheduleReconnect() {
    if (_isExplicitlyDisconnected || _isDisposed) return;
    if (_reconnectTimer?.isActive ?? false) return;

    final delay = _calculateBackoff();
    _reconnectAttempts++;
    debugPrint(
      'RealtimeService: Scheduling reconnect attempt #$_reconnectAttempts in ${delay.inMilliseconds}ms',
    );

    _reconnectTimer = Timer(delay, () {
      if (!_isExplicitlyDisconnected && !_isDisposed) {
        _establishConnection();
      }
    });
  }

  /// Calculates backoff duration capped at 30 seconds with optional jitter.
  Duration _calculateBackoff() {
    // 1s, 2s, 4s, 8s, 16s, 32s (capped at 30s)
    final attempt = min(_reconnectAttempts, 5);
    final baseSeconds = min(30, 1 << attempt);
    final jitterMs = _enableJitter ? _random.nextInt(1000) : 0;
    return Duration(seconds: baseSeconds, milliseconds: jitterMs);
  }

  void _stopReconnectTimer() {
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
  }

  void _closeChannel() {
    _channelSubscription?.cancel();
    _channelSubscription = null;
    try {
      _channel?.sink.close();
    } catch (_) {}
    _channel = null;
  }

  void _updateStatus(RealtimeConnectionStatus next) {
    if (_status == next) return;
    _status = next;
    _statusNotifier.value = next;
    if (!_statusController.isClosed) {
      _statusController.add(next);
    }
  }

  /// Cleans up all active subscriptions, timers, and controllers.
  void dispose() {
    _isDisposed = true;
    _stopReconnectTimer();
    _closeChannel();
    _eventController.close();
    _statusController.close();
    _statusNotifier.dispose();
  }
}
