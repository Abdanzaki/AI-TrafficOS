import 'dart:convert';

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
    this.geometry,
  });

  final int id;
  final String name;
  final String roadType;
  final int? fromIntersectionId;
  final int? toIntersectionId;
  final int? speedLimitKmh;
  final double? lengthKm;
  final bool isBidirectional;
  final String? geometry;

  factory RoadSegment.fromJson(Map<String, dynamic> json) {
    final rawGeo = json['geometry'];
    String? geoStr;
    if (rawGeo is String) {
      geoStr = rawGeo;
    } else if (rawGeo != null) {
      try {
        geoStr = jsonEncode(rawGeo);
      } catch (_) {
        geoStr = null;
      }
    }

    return RoadSegment(
      id: (json['id'] as num).toInt(),
      name: json['name'] as String? ?? 'Road Segment',
      roadType: json['road_type'] as String? ?? 'arterial',
      fromIntersectionId: (json['from_intersection_id'] as num?)?.toInt(),
      toIntersectionId: (json['to_intersection_id'] as num?)?.toInt(),
      speedLimitKmh: (json['speed_limit_kmh'] as num?)?.toInt(),
      lengthKm: (json['length_km'] as num?)?.toDouble(),
      isBidirectional: json['is_bidirectional'] as bool? ?? true,
      geometry: geoStr,
    );
  }

  /// Parses GeoJSON or WKT geometry representation into a list of [lat, lon] points.
  /// Returns null if geometry is absent or cannot be decoded with at least 2 valid points.
  List<List<double>>? parseCoordinates() {
    if (geometry == null || geometry!.trim().isEmpty) return null;
    final trimmed = geometry!.trim();

    // 1. Try parsing WKT LINESTRING (e.g., "LINESTRING(77.20 28.61, 77.25 28.65)")
    final wktMatch = RegExp(r'LINESTRING\s*\(([^)]+)\)', caseSensitive: false).firstMatch(trimmed);
    if (wktMatch != null) {
      final rawCoords = wktMatch.group(1);
      if (rawCoords != null) {
        final points = <List<double>>[];
        final pairs = rawCoords.split(',');
        for (final pair in pairs) {
          final parts = pair.trim().split(RegExp(r'\s+'));
          if (parts.length >= 2) {
            final lon = double.tryParse(parts[0]);
            final lat = double.tryParse(parts[1]);
            if (lat != null && lon != null) {
              points.add([lat, lon]);
            }
          }
        }
        if (points.length >= 2) return points;
      }
    }

    // 2. Try parsing GeoJSON (LineString, Feature, or MultiLineString)
    try {
      dynamic decoded = jsonDecode(trimmed);
      if (decoded is Map<String, dynamic>) {
        if (decoded['type'] == 'Feature' && decoded['geometry'] is Map<String, dynamic>) {
          decoded = decoded['geometry'];
        }

        final type = decoded['type'];
        final rawCoords = decoded['coordinates'];

        if (type == 'LineString' && rawCoords is List) {
          final points = <List<double>>[];
          for (final item in rawCoords) {
            if (item is List && item.length >= 2) {
              final lon = (item[0] as num?)?.toDouble();
              final lat = (item[1] as num?)?.toDouble();
              if (lat != null && lon != null) {
                points.add([lat, lon]);
              }
            }
          }
          if (points.length >= 2) return points;
        }

        if (type == 'MultiLineString' && rawCoords is List) {
          for (final line in rawCoords) {
            if (line is List) {
              final points = <List<double>>[];
              for (final item in line) {
                if (item is List && item.length >= 2) {
                  final lon = (item[0] as num?)?.toDouble();
                  final lat = (item[1] as num?)?.toDouble();
                  if (lat != null && lon != null) {
                    points.add([lat, lon]);
                  }
                }
              }
              if (points.length >= 2) return points;
            }
          }
        }
      }
    } catch (_) {
      // Not valid GeoJSON JSON
    }

    return null;
  }
}

