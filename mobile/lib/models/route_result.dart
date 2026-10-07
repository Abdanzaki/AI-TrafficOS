/// Directed roadway segment traversed within calculated route.
class RouteEdge {
  const RouteEdge({
    required this.roadId,
    required this.fromIntersectionId,
    required this.toIntersectionId,
    required this.lengthKm,
    required this.costMinutes,
  });

  final int roadId;
  final int fromIntersectionId;
  final int toIntersectionId;
  final double lengthKm;
  final double costMinutes;

  factory RouteEdge.fromJson(Map<String, dynamic> json) {
    return RouteEdge(
      roadId: (json['road_id'] as num?)?.toInt() ?? 0,
      fromIntersectionId: (json['from_intersection_id'] as num?)?.toInt() ?? 0,
      toIntersectionId: (json['to_intersection_id'] as num?)?.toInt() ?? 0,
      lengthKm: (json['length_km'] as num?)?.toDouble() ?? 0.0,
      costMinutes: (json['cost_minutes'] as num?)?.toDouble() ?? 0.0,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'road_id': roadId,
      'from_intersection_id': fromIntersectionId,
      'to_intersection_id': toIntersectionId,
      'length_km': lengthKm,
      'cost_minutes': costMinutes,
    };
  }
}

/// Calculated optimal path response across network topology.
class RouteResult {
  const RouteResult({
    required this.algorithm,
    required this.path,
    required this.edges,
    required this.totalCostMinutes,
    required this.totalDistanceKm,
  });

  final String algorithm;
  final List<int> path;
  final List<RouteEdge> edges;
  final double totalCostMinutes;
  final double totalDistanceKm;

  List<int> get waypoints => path;
  int get waypointCount => path.length;

  String get formattedDistance => '${totalDistanceKm.toStringAsFixed(2)} km';

  String get formattedDuration {
    if (totalCostMinutes < 1.0) {
      final sec = (totalCostMinutes * 60).round();
      return '$sec sec';
    }
    return '${totalCostMinutes.toStringAsFixed(1)} min';
  }

  factory RouteResult.fromJson(Map<String, dynamic> json) {
    List<int> parsePath(dynamic raw) {
      if (raw is List) {
        return raw.map((e) => (e as num).toInt()).toList();
      }
      return [];
    }

    List<RouteEdge> parseEdges(dynamic raw) {
      if (raw is List) {
        return raw
            .whereType<Map<String, dynamic>>()
            .map(RouteEdge.fromJson)
            .toList();
      }
      return [];
    }

    return RouteResult(
      algorithm: (json['algorithm'] as String?) ?? 'astar',
      path: parsePath(json['path']),
      edges: parseEdges(json['edges']),
      totalCostMinutes: (json['total_cost_minutes'] as num?)?.toDouble() ?? 0.0,
      totalDistanceKm: (json['total_distance_km'] as num?)?.toDouble() ?? 0.0,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'algorithm': algorithm,
      'path': path,
      'edges': edges.map((e) => e.toJson()).toList(),
      'total_cost_minutes': totalCostMinutes,
      'total_distance_km': totalDistanceKm,
    };
  }
}
