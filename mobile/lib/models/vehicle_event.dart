import 'package:flutter/material.dart';

/// Single vehicle perception detection event matching GET `/vehicle-events`.
class VehicleEvent {
  const VehicleEvent({
    required this.id,
    this.intersectionId,
    this.laneId,
    required this.eventType,
    required this.vehicleType,
    this.speedKmh,
    this.direction,
    this.confidence,
    required this.detectedAt,
  });

  final int id;
  final int? intersectionId;
  final int? laneId;
  final String eventType;
  final String vehicleType;
  final double? speedKmh;
  final String? direction;
  final double? confidence;
  final DateTime detectedAt;

  IconData get icon {
    switch (vehicleType.toLowerCase()) {
      case 'truck':
        return Icons.local_shipping_rounded;
      case 'bus':
        return Icons.directions_bus_rounded;
      case 'motorcycle':
        return Icons.two_wheeler_rounded;
      case 'bicycle':
        return Icons.pedal_bike_rounded;
      case 'car':
      default:
        return Icons.directions_car_rounded;
    }
  }

  factory VehicleEvent.fromJson(Map<String, dynamic> json) {
    DateTime parseDate(dynamic v) {
      if (v == null) return DateTime.now();
      return DateTime.tryParse(v.toString()) ?? DateTime.now();
    }

    return VehicleEvent(
      id: (json['id'] as num?)?.toInt() ?? 0,
      intersectionId: (json['intersection_id'] as num?)?.toInt(),
      laneId: (json['lane_id'] as num?)?.toInt(),
      eventType: (json['event_type'] as String?) ?? 'detection',
      vehicleType: (json['vehicle_type'] as String?) ?? 'car',
      speedKmh: (json['speed_kmh'] as num?)?.toDouble(),
      direction: json['direction'] as String?,
      confidence: (json['confidence'] as num?)?.toDouble(),
      detectedAt: parseDate(json['detected_at']),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'intersection_id': intersectionId,
      'lane_id': laneId,
      'event_type': eventType,
      'vehicle_type': vehicleType,
      'speed_kmh': speedKmh,
      'direction': direction,
      'confidence': confidence,
      'detected_at': detectedAt.toIso8601String(),
    };
  }
}

/// Paginated vehicle events listing response schema.
class PaginatedVehicleEvents {
  const PaginatedVehicleEvents({
    required this.items,
    required this.total,
    required this.page,
    required this.perPage,
    required this.pages,
  });

  final List<VehicleEvent> items;
  final int total;
  final int page;
  final int perPage;
  final int pages;

  factory PaginatedVehicleEvents.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'];
    List<VehicleEvent> itemList = [];
    if (rawItems is List) {
      itemList = rawItems
          .whereType<Map<String, dynamic>>()
          .map(VehicleEvent.fromJson)
          .toList();
    }

    return PaginatedVehicleEvents(
      items: itemList,
      total: (json['total'] as num?)?.toInt() ?? itemList.length,
      page: (json['page'] as num?)?.toInt() ?? 1,
      perPage: (json['per_page'] as num?)?.toInt() ?? 20,
      pages: (json['pages'] as num?)?.toInt() ?? 1,
    );
  }
}
