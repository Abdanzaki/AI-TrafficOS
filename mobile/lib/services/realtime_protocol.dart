import 'dart:convert';

/// Real-Time WebSocket Protocol for AI TrafficOS.
///
/// CONTRACT SPECIFICATION & ASSUMPTIONS:
/// -------------------------------------
/// Backend Phase 9 WebSocket endpoint assumptions:
///
/// 1. Connection:
///    `ws(s)://HOST/ws/v1/stream?token=<JWT>&event_types=t1,t2&last_event_id=<id>`
///    - WebSocket base URL is derived from AppConfig.apiBaseUrl:
///      'http' -> 'ws', 'https' -> 'wss', path set to '/ws/v1/stream'.
///    - Query parameters:
///      - `token`: Access JWT string.
///      - `event_types`: Comma-separated list of event types to subscribe to initially.
///      - `last_event_id` (optional): The most recent event ID received by the client.
///
/// 2. Server -> Client frames (JSON):
///    - Connected Handshake:
///      `{"type":"connection.established","event_types":[...],"heartbeat_interval_ms":25000,"server_time":"<iso8601>"}`
///      (or legacy `{"type":"connected",...}`)
///    - Event:
///      `{"event_id":"<uuid>","type":"traffic.update","payload":{...},"timestamp":"<iso8601>"}`
///      (or envelope `{"type":"event","topic":"traffic.update","data":{...}}`)
///    - Heartbeat / Ping:
///      `{"type":"heartbeat","timestamp":"<iso8601>"}`
///    - Resync:
///      `{"type":"resync","events":[...],"last_event_id":"<uuid>"}`
///    - Error:
///      `{"type":"error","code":"FORBIDDEN","message":"..."}`
///
/// 3. Client -> Server frames (JSON):
///    - Subscribe: `{"type":"subscribe","event_types":[...]}`
///    - Unsubscribe: `{"type":"unsubscribe","event_types":[...]}`
///    - Pong: `{"type":"pong","timestamp":"<iso8601>"}`
///    - Resync Request: `{"type":"resync_request","last_event_id":"<id>"}`
///
/// 4. Termination & Status:
///    - Close code 4401: Authentication failure (token expired/invalid). Client halts
///      reconnection attempts and invokes onAuthFailure callback for user logout.
///
/// 5. Roles & Topic Subscriptions:
///    - 'analyst': Subscribes to traffic.update, congestion.change, signal.change,
///      incident.*, prediction.published, notification.created, system.status
///      (excludes emergency.* and control.decision).
///    - 'traffic_officer', 'admin': Subscribes to all topics.
abstract final class RealtimeTopics {
  RealtimeTopics._();

  static const String trafficUpdate = 'traffic.update';
  static const String congestionChange = 'congestion.change';
  static const String signalChange = 'signal.change';
  static const String incidentCreated = 'incident.created';
  static const String incidentUpdated = 'incident.updated';
  static const String emergencyCreated = 'emergency.created';
  static const String emergencyUpdated = 'emergency.updated';
  static const String predictionPublished = 'prediction.published';
  static const String controlDecision = 'control.decision';
  static const String notificationCreated = 'notification.created';
  static const String systemStatus = 'system.status';

  /// Complete set of topics recognized by AI TrafficOS backend.
  static const List<String> all = [
    trafficUpdate,
    congestionChange,
    signalChange,
    incidentCreated,
    incidentUpdated,
    emergencyCreated,
    emergencyUpdated,
    predictionPublished,
    controlDecision,
    notificationCreated,
    systemStatus,
  ];

  /// Topics available to the read-only 'analyst' role.
  /// Note: excludes emergency.* and control.decision per RBAC contract.
  static const List<String> analystTopics = [
    trafficUpdate,
    congestionChange,
    signalChange,
    incidentCreated,
    incidentUpdated,
    predictionPublished,
    notificationCreated,
    systemStatus,
  ];
}

/// Strongly typed envelope representing a real-time event.
class RealtimeEvent {
  const RealtimeEvent({
    required this.eventId,
    required this.topic,
    required this.data,
    required this.timestamp,
    this.lastEventId,
  });

  /// Unique identifier of the event (UUID).
  final String eventId;

  /// Dot-separated topic namespace (e.g. traffic.update).
  final String topic;

  /// Arbitrary structured payload carried by this event.
  final Map<String, dynamic> data;

  /// UTC timestamp of event emission.
  final DateTime timestamp;

  /// Optional preceding event identifier for sequence verification.
  final String? lastEventId;

  factory RealtimeEvent.fromJson(Map<String, dynamic> json) {
    final rawTimestamp = json['timestamp'];
    DateTime parsedTime;
    if (rawTimestamp is String) {
      parsedTime = DateTime.tryParse(rawTimestamp) ?? DateTime.now().toUtc();
    } else {
      parsedTime = DateTime.now().toUtc();
    }

    final rawData = json['data'] ?? json['payload'];
    final Map<String, dynamic> parsedData =
        rawData is Map<String, dynamic> ? rawData : <String, dynamic>{};

    final rawTopic = json['topic'] ??
        (json['type'] != null && json['type'] != 'event' ? json['type'] : null) ??
        '';

    return RealtimeEvent(
      eventId: (json['event_id'] ?? json['eventId'] ?? '') as String,
      topic: rawTopic as String,
      data: parsedData,
      timestamp: parsedTime,
      lastEventId: json['last_event_id'] as String?,
    );
  }

  Map<String, dynamic> toJson() => {
        'type': 'event',
        'event_id': eventId,
        'topic': topic,
        'data': data,
        'timestamp': timestamp.toIso8601String(),
        if (lastEventId != null) 'last_event_id': lastEventId,
      };

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is RealtimeEvent &&
          runtimeType == other.runtimeType &&
          eventId == other.eventId &&
          topic == other.topic;

  @override
  int get hashCode => eventId.hashCode ^ topic.hashCode;

  @override
  String toString() => 'RealtimeEvent(id: $eventId, topic: $topic, timestamp: $timestamp)';
}

/// Maps a user role string to its permitted real-time topics list.
List<String> topicsForRole(String role) {
  switch (role) {
    case 'admin':
    case 'traffic_officer':
      return RealtimeTopics.all;
    case 'analyst':
    default:
      return RealtimeTopics.analystTopics;
  }
}

/// Builds a client-to-server subscription frame.
String buildSubscribeFrame(List<String> topics) {
  return jsonEncode({
    'type': 'subscribe',
    'event_types': topics,
  });
}

/// Builds a client-to-server unsubscription frame.
String buildUnsubscribeFrame(List<String> topics) {
  return jsonEncode({
    'type': 'unsubscribe',
    'event_types': topics,
  });
}

/// Builds a client-to-server heartbeat pong frame.
String buildPongFrame([DateTime? timestamp]) {
  return jsonEncode({
    'type': 'pong',
    'timestamp': (timestamp ?? DateTime.now().toUtc()).toIso8601String(),
  });
}

/// Builds a client-to-server resync request frame.
String buildResyncRequestFrame(String lastEventId) {
  return jsonEncode({
    'type': 'resync_request',
    'last_event_id': lastEventId,
  });
}

/// Derives the fully qualified WebSocket stream [Uri] from the REST [apiBaseUrl].
Uri buildWebSocketUri({
  required String apiBaseUrl,
  required String token,
  required List<String> topics,
  String? lastEventId,
}) {
  final base = Uri.parse(apiBaseUrl);
  final isSecure = base.scheme == 'https' || base.scheme == 'wss';
  final wsScheme = isSecure ? 'wss' : 'ws';

  final queryParameters = <String, String>{
    'token': token,
    'event_types': topics.join(','),
  };
  if (lastEventId != null && lastEventId.isNotEmpty) {
    queryParameters['last_event_id'] = lastEventId;
  }

  return Uri(
    scheme: wsScheme,
    userInfo: base.userInfo.isEmpty ? null : base.userInfo,
    host: base.host,
    port: base.hasPort ? base.port : null,
    path: '/ws/v1/stream',
    queryParameters: queryParameters,
  );
}
