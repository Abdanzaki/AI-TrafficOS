/// Signal phase configuration and state details.
class SignalPhaseSummary {
  const SignalPhaseSummary({
    required this.id,
    required this.signalId,
    this.intersectionId,
    required this.name,
    required this.phaseOrder,
    required this.durationSeconds,
    required this.state,
    required this.isActive,
  });

  final int id;
  final int signalId;
  final int? intersectionId;
  final String name;
  final int phaseOrder;
  final int durationSeconds;
  final String state;
  final bool isActive;

  factory SignalPhaseSummary.fromJson(Map<String, dynamic> json) {
    return SignalPhaseSummary(
      id: (json['id'] as num?)?.toInt() ?? 0,
      signalId: (json['signal_id'] as num?)?.toInt() ?? 0,
      intersectionId: (json['intersection_id'] as num?)?.toInt(),
      name: (json['name'] as String?) ?? '',
      phaseOrder: (json['phase_order'] as num?)?.toInt() ?? 1,
      durationSeconds: (json['duration_seconds'] as num?)?.toInt() ?? 30,
      state: (json['state'] as String?) ?? 'red',
      isActive: (json['is_active'] as bool?) ?? true,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'signal_id': signalId,
      'intersection_id': intersectionId,
      'name': name,
      'phase_order': phaseOrder,
      'duration_seconds': durationSeconds,
      'state': state,
      'is_active': isActive,
    };
  }
}

/// Hardware traffic signal controller representation.
class SignalSummary {
  const SignalSummary({
    required this.id,
    required this.intersectionId,
    required this.code,
    required this.status,
    this.observedState,
    this.observedConfidence,
    this.observedAt,
    this.phases = const [],
  });

  final int id;
  final int intersectionId;
  final String code;
  final String status;
  final String? observedState;
  final double? observedConfidence;
  final DateTime? observedAt;
  final List<SignalPhaseSummary> phases;

  factory SignalSummary.fromJson(Map<String, dynamic> json) {
    final rawPhases = json['phases'];
    List<SignalPhaseSummary> phasesList = [];
    if (rawPhases is List) {
      phasesList = rawPhases
          .whereType<Map<String, dynamic>>()
          .map(SignalPhaseSummary.fromJson)
          .toList();
    }

    DateTime? obsAt;
    if (json['observed_at'] != null) {
      obsAt = DateTime.tryParse(json['observed_at'].toString());
    }

    return SignalSummary(
      id: (json['id'] as num?)?.toInt() ?? 0,
      intersectionId: (json['intersection_id'] as num?)?.toInt() ?? 0,
      code: (json['code'] as String?) ?? '',
      status: (json['status'] as String?) ?? 'active',
      observedState: json['observed_state'] as String?,
      observedConfidence: (json['observed_confidence'] as num?)?.toDouble(),
      observedAt: obsAt,
      phases: phasesList,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'intersection_id': intersectionId,
      'code': code,
      'status': status,
      'observed_state': observedState,
      'observed_confidence': observedConfidence,
      'observed_at': observedAt?.toIso8601String(),
      'phases': phases.map((p) => p.toJson()).toList(),
    };
  }
}

/// Lane configuration at junction.
class LaneSummary {
  const LaneSummary({
    required this.id,
    required this.roadId,
    this.intersectionId,
    required this.laneNumber,
    required this.direction,
    required this.laneType,
  });

  final int id;
  final int roadId;
  final int? intersectionId;
  final int laneNumber;
  final String direction;
  final String laneType;

  factory LaneSummary.fromJson(Map<String, dynamic> json) {
    return LaneSummary(
      id: (json['id'] as num?)?.toInt() ?? 0,
      roadId: (json['road_id'] as num?)?.toInt() ?? 0,
      intersectionId: (json['intersection_id'] as num?)?.toInt(),
      laneNumber: (json['lane_number'] as num?)?.toInt() ?? 1,
      direction: (json['direction'] as String?) ?? 'unknown',
      laneType: (json['lane_type'] as String?) ?? 'through',
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'road_id': roadId,
      'intersection_id': intersectionId,
      'lane_number': laneNumber,
      'direction': direction,
      'lane_type': laneType,
    };
  }
}

/// Physical municipal intersection / junction model matching GET `/junctions`.
class Junction {
  const Junction({
    required this.id,
    required this.name,
    required this.code,
    required this.status,
    this.city,
    this.zone,
    this.latitude,
    this.longitude,
    this.createdAt,
    this.updatedAt,
    this.signals = const [],
    this.lanes = const [],
  });

  final int id;
  final String name;
  final String code;
  final String status;
  final String? city;
  final String? zone;
  final double? latitude;
  final double? longitude;
  final DateTime? createdAt;
  final DateTime? updatedAt;
  final List<SignalSummary> signals;
  final List<LaneSummary> lanes;

  bool get isActive => status.toLowerCase() == 'active';

  factory Junction.fromJson(Map<String, dynamic> json) {
    final lat = (json['lat'] as num?)?.toDouble() ??
        (json['latitude'] as num?)?.toDouble();
    final lon = (json['lon'] as num?)?.toDouble() ??
        (json['longitude'] as num?)?.toDouble();

    DateTime? created;
    if (json['created_at'] != null) {
      created = DateTime.tryParse(json['created_at'].toString());
    }

    DateTime? updated;
    if (json['updated_at'] != null) {
      updated = DateTime.tryParse(json['updated_at'].toString());
    }

    List<SignalSummary> signalsList = [];
    if (json['signals'] is List) {
      signalsList = (json['signals'] as List)
          .whereType<Map<String, dynamic>>()
          .map(SignalSummary.fromJson)
          .toList();
    }

    List<LaneSummary> lanesList = [];
    if (json['lanes'] is List) {
      lanesList = (json['lanes'] as List)
          .whereType<Map<String, dynamic>>()
          .map(LaneSummary.fromJson)
          .toList();
    }

    return Junction(
      id: (json['id'] as num?)?.toInt() ?? 0,
      name: (json['name'] as String?) ?? 'Unknown Junction',
      code: (json['code'] as String?) ?? '',
      status: (json['status'] as String?) ?? 'active',
      city: json['city'] as String?,
      zone: json['zone'] as String?,
      latitude: lat,
      longitude: lon,
      createdAt: created,
      updatedAt: updated,
      signals: signalsList,
      lanes: lanesList,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      'code': code,
      'status': status,
      'city': city,
      'zone': zone,
      'lat': latitude,
      'lon': longitude,
      'created_at': createdAt?.toIso8601String(),
      'updated_at': updatedAt?.toIso8601String(),
      'signals': signals.map((s) => s.toJson()).toList(),
      'lanes': lanes.map((l) => l.toJson()).toList(),
    };
  }
}

/// Paginated junctions response matching FastAPI `PaginatedIntersections`.
class PaginatedJunctions {
  const PaginatedJunctions({
    required this.items,
    required this.total,
    required this.page,
    required this.perPage,
    required this.pages,
  });

  final List<Junction> items;
  final int total;
  final int page;
  final int perPage;
  final int pages;

  factory PaginatedJunctions.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'];
    List<Junction> itemList = [];
    if (rawItems is List) {
      itemList = rawItems
          .whereType<Map<String, dynamic>>()
          .map(Junction.fromJson)
          .toList();
    }

    return PaginatedJunctions(
      items: itemList,
      total: (json['total'] as num?)?.toInt() ?? itemList.length,
      page: (json['page'] as num?)?.toInt() ?? 1,
      perPage: (json['per_page'] as num?)?.toInt() ?? 20,
      pages: (json['pages'] as num?)?.toInt() ?? 1,
    );
  }
}
