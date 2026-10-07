/// Corridor congestion ranking item matching GET `/routing/congestion-ranking`.
class CongestionRankingItem {
  const CongestionRankingItem({
    required this.roadId,
    required this.roadName,
    this.fromIntersectionId,
    this.toIntersectionId,
    required this.congestionLevel,
    required this.rank,
  });

  final int roadId;
  final String roadName;
  final int? fromIntersectionId;
  final int? toIntersectionId;
  final double congestionLevel;
  final int rank;

  factory CongestionRankingItem.fromJson(Map<String, dynamic> json) {
    return CongestionRankingItem(
      roadId: (json['road_id'] as num?)?.toInt() ?? 0,
      roadName: (json['road_name'] as String?) ?? 'Unknown Road',
      fromIntersectionId: (json['from_intersection_id'] as num?)?.toInt(),
      toIntersectionId: (json['to_intersection_id'] as num?)?.toInt(),
      congestionLevel: (json['congestion_level'] as num?)?.toDouble() ?? 0.0,
      rank: (json['rank'] as num?)?.toInt() ?? 1,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'road_id': roadId,
      'road_name': roadName,
      'from_intersection_id': fromIntersectionId,
      'to_intersection_id': toIntersectionId,
      'congestion_level': congestionLevel,
      'rank': rank,
    };
  }
}
