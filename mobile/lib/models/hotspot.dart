/// Congestion hotspot model matching GET `/analytics/congestion-hotspots`.
class CongestionHotspot {
  const CongestionHotspot({
    required this.intersectionId,
    required this.name,
    required this.code,
    required this.avgCongestionLevel,
    required this.recordCount,
  });

  final int intersectionId;
  final String name;
  final String code;
  final double avgCongestionLevel;
  final int recordCount;

  factory CongestionHotspot.fromJson(Map<String, dynamic> json) {
    final congLevel = (json['avg_congestion_level'] as num?)?.toDouble() ??
        (json['avg_congestion'] as num?)?.toDouble() ??
        0.0;

    return CongestionHotspot(
      intersectionId: (json['intersection_id'] as num?)?.toInt() ?? 0,
      name: (json['name'] as String?) ?? 'Unknown Junction',
      code: (json['code'] as String?) ?? '',
      avgCongestionLevel: congLevel,
      recordCount: (json['record_count'] as num?)?.toInt() ?? 0,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'intersection_id': intersectionId,
      'name': name,
      'code': code,
      'avg_congestion_level': avgCongestionLevel,
      'record_count': recordCount,
    };
  }
}
