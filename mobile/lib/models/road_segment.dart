/// Road segment model representing physical network links connecting intersections.
class RoadSegment {
  const RoadSegment({
    required this.id,
    required this.name,
    required this.roadType,
    this.fromIntersectionId,
    this.toIntersectionId,
    this.speedLimitKmh,
    this.lengthKm,
    this.isBidirectional = true,
  });

  final int id;
  final String name;
  final String roadType;
  final int? fromIntersectionId;
  final int? toIntersectionId;
  final int? speedLimitKmh;
  final double? lengthKm;
  final bool isBidirectional;

  factory RoadSegment.fromJson(Map<String, dynamic> json) {
    return RoadSegment(
      id: (json['id'] as num).toInt(),
      name: json['name'] as String? ?? 'Road Segment',
      roadType: json['road_type'] as String? ?? 'arterial',
      fromIntersectionId: (json['from_intersection_id'] as num?)?.toInt(),
      toIntersectionId: (json['to_intersection_id'] as num?)?.toInt(),
      speedLimitKmh: (json['speed_limit_kmh'] as num?)?.toInt(),
      lengthKm: (json['length_km'] as num?)?.toDouble(),
      isBidirectional: json['is_bidirectional'] as bool? ?? true,
    );
  }
}
