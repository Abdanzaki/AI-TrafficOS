/// Traffic sensor and telemetry record observation model matching GET `/traffic-records`.
class TrafficRecord {
  const TrafficRecord({
    required this.id,
    required this.intersectionId,
    this.laneId,
    required this.recordedAt,
    required this.vehicleCount,
    this.avgSpeedKmh,
    required this.congestionLevel,
    required this.source,
  });

  final int id;
  final int intersectionId;
  final int? laneId;
  final DateTime recordedAt;
  final int vehicleCount;
  final double? avgSpeedKmh;
  final int congestionLevel;
  final String source;

  factory TrafficRecord.fromJson(Map<String, dynamic> json) {
    DateTime parsedRecordedAt;
    if (json['recorded_at'] != null) {
      parsedRecordedAt =
          DateTime.tryParse(json['recorded_at'].toString()) ?? DateTime.now();
    } else {
      parsedRecordedAt = DateTime.now();
    }

    return TrafficRecord(
      id: (json['id'] as num?)?.toInt() ?? 0,
      intersectionId: (json['intersection_id'] as num?)?.toInt() ?? 0,
      laneId: (json['lane_id'] as num?)?.toInt(),
      recordedAt: parsedRecordedAt,
      vehicleCount: (json['vehicle_count'] as num?)?.toInt() ?? 0,
      avgSpeedKmh: (json['avg_speed_kmh'] as num?)?.toDouble(),
      congestionLevel: (json['congestion_level'] as num?)?.toInt() ?? 0,
      source: (json['source'] as String?) ?? 'sensor',
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'intersection_id': intersectionId,
      'lane_id': laneId,
      'recorded_at': recordedAt.toIso8601String(),
      'vehicle_count': vehicleCount,
      'avg_speed_kmh': avgSpeedKmh,
      'congestion_level': congestionLevel,
      'source': source,
    };
  }
}

/// Paginated traffic records listing response schema.
class PaginatedTrafficRecords {
  const PaginatedTrafficRecords({
    required this.items,
    required this.total,
    required this.page,
    required this.perPage,
    required this.pages,
  });

  final List<TrafficRecord> items;
  final int total;
  final int page;
  final int perPage;
  final int pages;

  factory PaginatedTrafficRecords.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'];
    List<TrafficRecord> itemList = [];
    if (rawItems is List) {
      itemList = rawItems
          .whereType<Map<String, dynamic>>()
          .map(TrafficRecord.fromJson)
          .toList();
    }

    return PaginatedTrafficRecords(
      items: itemList,
      total: (json['total'] as num?)?.toInt() ?? itemList.length,
      page: (json['page'] as num?)?.toInt() ?? 1,
      perPage: (json['per_page'] as num?)?.toInt() ?? 20,
      pages: (json['pages'] as num?)?.toInt() ?? 1,
    );
  }
}
