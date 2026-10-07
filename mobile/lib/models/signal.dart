import 'package:flutter/material.dart';

import '../theme/app_tokens.dart';

/// State of a traffic signal light or phase interval.
enum SignalState {
  red,
  yellow,
  green,
  unknown;

  static SignalState fromString(String? val) {
    if (val == null) return SignalState.unknown;
    switch (val.toLowerCase().trim()) {
      case 'red':
        return SignalState.red;
      case 'yellow':
      case 'amber':
        return SignalState.yellow;
      case 'green':
        return SignalState.green;
      default:
        return SignalState.unknown;
    }
  }

  String get label {
    switch (this) {
      case SignalState.red:
        return 'Red';
      case SignalState.yellow:
        return 'Yellow';
      case SignalState.green:
        return 'Green';
      case SignalState.unknown:
        return 'Unknown';
    }
  }

  Color get color {
    switch (this) {
      case SignalState.red:
        return AppTokens.danger;
      case SignalState.yellow:
        return AppTokens.amber;
      case SignalState.green:
        return AppTokens.success;
      case SignalState.unknown:
        return AppTokens.muted;
    }
  }
}

/// Represents an individual phase interval of a signal cycle.
class SignalPhase {
  const SignalPhase({
    required this.id,
    required this.signalId,
    this.intersectionId,
    required this.name,
    required this.phaseOrder,
    required this.durationSeconds,
    required this.state,
    required this.isActive,
    this.createdAt,
    this.updatedAt,
  });

  final int id;
  final int signalId;
  final int? intersectionId;
  final String name;
  final int phaseOrder;
  final int durationSeconds;
  final SignalState state;
  final bool isActive;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  Color get color => state.color;

  factory SignalPhase.fromJson(Map<String, dynamic> json) {
    DateTime? parseDate(dynamic v) {
      if (v == null) return null;
      return DateTime.tryParse(v.toString());
    }

    return SignalPhase(
      id: (json['id'] as num?)?.toInt() ?? 0,
      signalId: (json['signal_id'] as num?)?.toInt() ?? 0,
      intersectionId: (json['intersection_id'] as num?)?.toInt(),
      name: (json['name'] as String?) ?? 'Phase',
      phaseOrder: (json['phase_order'] as num?)?.toInt() ?? 1,
      durationSeconds: (json['duration_seconds'] as num?)?.toInt() ?? 30,
      state: SignalState.fromString(json['state'] as String?),
      isActive: (json['is_active'] as bool?) ?? false,
      createdAt: parseDate(json['created_at']),
      updatedAt: parseDate(json['updated_at']),
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
      'state': state.name,
      'is_active': isActive,
      'created_at': createdAt?.toIso8601String(),
      'updated_at': updatedAt?.toIso8601String(),
    };
  }
}

/// Hardware traffic signal controller model matching GET `/signals`.
class Signal {
  const Signal({
    required this.id,
    required this.intersectionId,
    required this.name,
    required this.code,
    required this.status,
    this.currentPhase,
    this.state = SignalState.unknown,
    this.observedState,
    this.observedConfidence,
    this.observedAt,
    this.createdAt,
    this.updatedAt,
    this.phases = const [],
  });

  final int id;
  final int intersectionId;
  final String name;
  final String code;
  final String status;
  final String? currentPhase;
  final SignalState state;
  final String? observedState;
  final double? observedConfidence;
  final DateTime? observedAt;
  final DateTime? createdAt;
  final DateTime? updatedAt;
  final List<SignalPhase> phases;

  Color get stateColor => state.color;

  Color get statusColor {
    switch (status.toLowerCase()) {
      case 'active':
        return AppTokens.success;
      case 'maintenance':
        return AppTokens.amber;
      case 'fault':
      case 'inactive':
        return AppTokens.danger;
      default:
        return AppTokens.muted;
    }
  }

  bool get isActive => status.toLowerCase() == 'active';

  factory Signal.fromJson(Map<String, dynamic> json) {
    DateTime? parseDate(dynamic v) {
      if (v == null) return null;
      return DateTime.tryParse(v.toString());
    }

    final id = (json['id'] as num?)?.toInt() ?? 0;
    final code = (json['code'] as String?) ?? 'SIG-$id';
    final name = (json['name'] as String?) ?? code;

    List<SignalPhase> phasesList = [];
    if (json['phases'] is List) {
      phasesList = (json['phases'] as List)
          .whereType<Map<String, dynamic>>()
          .map(SignalPhase.fromJson)
          .toList()
        ..sort((a, b) => a.phaseOrder.compareTo(b.phaseOrder));
    }

    // Determine active phase name and state
    String? currentPhase = json['current_phase'] as String? ??
        json['currentPhase'] as String?;
    SignalState signalState = SignalState.unknown;

    if (json['state'] != null) {
      signalState = SignalState.fromString(json['state'] as String?);
    } else if (json['observed_state'] != null) {
      signalState = SignalState.fromString(json['observed_state'] as String?);
    }

    if (phasesList.isNotEmpty) {
      final activePhase = phasesList.cast<SignalPhase?>().firstWhere(
            (p) => p?.isActive ?? false,
            orElse: () => null,
          );
      if (activePhase != null) {
        currentPhase ??= activePhase.name;
        if (signalState == SignalState.unknown) {
          signalState = activePhase.state;
        }
      } else if (currentPhase == null && phasesList.isNotEmpty) {
        currentPhase = phasesList.first.name;
      }
    }

    return Signal(
      id: id,
      intersectionId: (json['intersection_id'] as num?)?.toInt() ?? 0,
      name: name,
      code: code,
      status: (json['status'] as String?) ?? 'active',
      currentPhase: currentPhase,
      state: signalState,
      observedState: json['observed_state'] as String?,
      observedConfidence: (json['observed_confidence'] as num?)?.toDouble(),
      observedAt: parseDate(json['observed_at']),
      createdAt: parseDate(json['created_at']),
      updatedAt: parseDate(json['updated_at']),
      phases: phasesList,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'intersection_id': intersectionId,
      'name': name,
      'code': code,
      'status': status,
      'current_phase': currentPhase,
      'state': state.name,
      'observed_state': observedState,
      'observed_confidence': observedConfidence,
      'observed_at': observedAt?.toIso8601String(),
      'created_at': createdAt?.toIso8601String(),
      'updated_at': updatedAt?.toIso8601String(),
      'phases': phases.map((p) => p.toJson()).toList(),
    };
  }
}

/// Paginated signals response matching GET `/signals`.
class PaginatedSignals {
  const PaginatedSignals({
    required this.items,
    required this.total,
    required this.page,
    required this.perPage,
    required this.pages,
  });

  final List<Signal> items;
  final int total;
  final int page;
  final int perPage;
  final int pages;

  factory PaginatedSignals.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'];
    List<Signal> itemList = [];
    if (rawItems is List) {
      itemList = rawItems
          .whereType<Map<String, dynamic>>()
          .map(Signal.fromJson)
          .toList();
    }

    return PaginatedSignals(
      items: itemList,
      total: (json['total'] as num?)?.toInt() ?? itemList.length,
      page: (json['page'] as num?)?.toInt() ?? 1,
      perPage: (json['per_page'] as num?)?.toInt() ?? 20,
      pages: (json['pages'] as num?)?.toInt() ?? 1,
    );
  }
}
