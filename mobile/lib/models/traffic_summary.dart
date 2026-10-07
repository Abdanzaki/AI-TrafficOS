/// Traffic summary aggregation models matching GET `/analytics/traffic-summary`.
class TrafficSummaryBucket {
  const TrafficSummaryBucket({
    required this.bucket,
    required this.avgVehicleCount,
    this.avgSpeed,
    required this.avgCongestion,
    required this.recordCount,
  });

  final DateTime bucket;
  final double avgVehicleCount;
  final double? avgSpeed;
  final double avgCongestion;
  final int recordCount;

  factory TrafficSummaryBucket.fromJson(Map<String, dynamic> json) {
    DateTime parsedBucket;
    if (json['bucket'] != null) {
      parsedBucket = DateTime.tryParse(json['bucket'].toString()) ?? DateTime.now();
    } else {
      parsedBucket = DateTime.now();
    }

    final avgVc = (json['avg_vehicle_count'] as num?)?.toDouble() ?? 0.0;
    final speed = (json['avg_speed'] as num?)?.toDouble() ??
        (json['avg_speed_kmh'] as num?)?.toDouble();
    final congestion = (json['avg_congestion'] as num?)?.toDouble() ??
        (json['avg_congestion_level'] as num?)?.toDouble() ??
        0.0;
    final count = (json['record_count'] as num?)?.toInt() ?? 0;

    return TrafficSummaryBucket(
      bucket: parsedBucket,
      avgVehicleCount: avgVc,
      avgSpeed: speed,
      avgCongestion: congestion,
      recordCount: count,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'bucket': bucket.toIso8601String(),
      'avg_vehicle_count': avgVehicleCount,
      'avg_speed': avgSpeed,
      'avg_congestion': avgCongestion,
      'record_count': recordCount,
    };
  }
}
