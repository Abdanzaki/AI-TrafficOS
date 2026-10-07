/// Represents the health status response from the AI TrafficOS backend API.
class HealthStatus {
  const HealthStatus({
    required this.status,
    required this.service,
    required this.version,
    this.timestamp,
    this.raw = const {},
  });

  /// Status string returned by backend (e.g., 'ok', 'healthy', 'degraded').
  final String status;

  /// Name of the service (e.g., 'ai-trafficos-backend').
  final String service;

  /// Version string of the backend service.
  final String version;

  /// Optional ISO timestamp of the health check.
  final DateTime? timestamp;

  /// Raw JSON payload received from backend.
  final Map<String, dynamic> raw;

  /// Returns true when status is considered healthy ('ok' or 'healthy').
  bool get isHealthy {
    final s = status.trim().toLowerCase();
    return s == 'ok' || s == 'healthy';
  }

  /// Parses [HealthStatus] from a backend JSON map.
  factory HealthStatus.fromJson(Map<String, dynamic> json) {
    DateTime? parsedTimestamp;
    if (json['timestamp'] != null) {
      parsedTimestamp = DateTime.tryParse(json['timestamp'].toString());
    }

    return HealthStatus(
      status: (json['status'] as String?)?.trim() ?? 'unknown',
      service: (json['service'] as String?)?.trim() ?? 'ai-trafficos-backend',
      version: (json['version'] as String?)?.trim() ?? '1.0.0',
      timestamp: parsedTimestamp,
      raw: Map<String, dynamic>.unmodifiable(json),
    );
  }

  /// Creates a copy with the given fields replaced by new values.
  HealthStatus copyWith({
    String? status,
    String? service,
    String? version,
    DateTime? timestamp,
    Map<String, dynamic>? raw,
  }) {
    return HealthStatus(
      status: status ?? this.status,
      service: service ?? this.service,
      version: version ?? this.version,
      timestamp: timestamp ?? this.timestamp,
      raw: raw ?? this.raw,
    );
  }

  @override
  String toString() =>
      'HealthStatus(status: $status, service: $service, version: $version, timestamp: $timestamp)';

  @override
  bool operator ==(Object other) {
    if (identical(this, other)) return true;
    return other is HealthStatus &&
        other.status == status &&
        other.service == service &&
        other.version == version &&
        other.timestamp == timestamp;
  }

  @override
  int get hashCode => Object.hash(status, service, version, timestamp);
}
