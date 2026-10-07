/// Exception thrown when telemetry data is insufficient for machine learning predictions.
class InsufficientDataException implements Exception {
  const InsufficientDataException({
    required this.message,
    this.rowsFound,
    this.rowsRequired,
    this.intersectionId,
    this.details,
  });

  final String message;
  final int? rowsFound;
  final int? rowsRequired;
  final int? intersectionId;
  final dynamic details;

  String get userFriendlyMessage {
    if (rowsRequired != null) {
      final foundStr = rowsFound != null ? ' (found $rowsFound)' : '';
      return 'Not enough data yet — predictions need $rowsRequired rows$foundStr';
    }
    return message;
  }

  @override
  String toString() {
    if (rowsFound != null && rowsRequired != null) {
      return 'InsufficientDataException: $message (found: $rowsFound, required: $rowsRequired)';
    }
    return 'InsufficientDataException: $message';
  }
}

/// 30-minute forward prediction result matching GET `/forecasting/predict`.
class PredictionResult {
  const PredictionResult({
    required this.intersectionId,
    required this.status,
    this.predictedFor,
    this.modelVersion,
    this.volume,
    this.volumeConfidence,
    this.congestion,
    this.congestionConfidence,
    this.queue,
    this.queueConfidence,
    this.overallConfidence,
    this.predictionIds = const [],
    this.rowsFound,
    this.rowsRequired,
    this.message,
  });

  final int intersectionId;
  final String status;
  final DateTime? predictedFor;
  final String? modelVersion;
  final double? volume;
  final double? volumeConfidence;
  final double? congestion;
  final double? congestionConfidence;
  final double? queue;
  final double? queueConfidence;
  final double? overallConfidence;
  final List<int> predictionIds;
  final int? rowsFound;
  final int? rowsRequired;
  final String? message;

  bool get isPredicted => status == 'predicted';
  bool get isInsufficientData => status == 'insufficient_data';

  factory PredictionResult.fromJson(Map<String, dynamic> json) {
    DateTime? parseDate(dynamic v) {
      if (v == null) return null;
      return DateTime.tryParse(v.toString());
    }

    double? parseDouble(dynamic v) {
      if (v is num) return v.toDouble();
      if (v != null) return double.tryParse(v.toString());
      return null;
    }

    // Extract flow info
    final flowMap = json['flow'] as Map<String, dynamic>?;
    final double? volume = parseDouble(flowMap?['value'] ?? json['volume']);
    final double? volumeConf =
        parseDouble(flowMap?['confidence'] ?? json['volume_confidence']);

    // Extract congestion info
    final congMap = json['congestion'] as Map<String, dynamic>?;
    final double? congVal =
        parseDouble(congMap?['value'] ?? json['congestion']);
    final double? congConf =
        parseDouble(congMap?['confidence'] ?? json['congestion_confidence']);
    final double? queueVal =
        parseDouble(congMap?['queue'] ?? json['queue']);
    final double? queueConf =
        parseDouble(congMap?['queue_confidence'] ?? json['queue_confidence']);

    double? overallConf = parseDouble(json['confidence']);
    overallConf ??= congConf ?? volumeConf;

    List<int> predIds = [];
    if (json['prediction_ids'] is List) {
      predIds = (json['prediction_ids'] as List)
          .whereType<num>()
          .map((n) => n.toInt())
          .toList();
    }

    return PredictionResult(
      intersectionId: (json['intersection_id'] as num?)?.toInt() ?? 0,
      status: (json['status'] as String?) ?? 'predicted',
      predictedFor: parseDate(json['predicted_for']),
      modelVersion: json['model_version'] as String?,
      volume: volume,
      volumeConfidence: volumeConf,
      congestion: congVal,
      congestionConfidence: congConf,
      queue: queueVal,
      queueConfidence: queueConf,
      overallConfidence: overallConf,
      predictionIds: predIds,
      rowsFound: (json['rows_found'] as num?)?.toInt(),
      rowsRequired: (json['rows_required'] as num?)?.toInt(),
      message: json['message'] as String?,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'intersection_id': intersectionId,
      'status': status,
      'predicted_for': predictedFor?.toIso8601String(),
      'model_version': modelVersion,
      'volume': volume,
      'congestion': congestion,
      'queue': queue,
      'confidence': overallConfidence,
      'prediction_ids': predictionIds,
      'rows_found': rowsFound,
      'rows_required': rowsRequired,
      'message': message,
    };
  }
}

/// AIPrediction record matching GET `/ai-predictions`.
class AIPrediction {
  const AIPrediction({
    required this.id,
    this.intersectionId,
    required this.predictionType,
    required this.predictedFor,
    required this.payload,
    this.confidence,
    required this.modelVersion,
    required this.createdAt,
    this.updatedAt,
  });

  final int id;
  final int? intersectionId;
  final String predictionType;
  final DateTime predictedFor;
  final Map<String, dynamic> payload;
  final double? confidence;
  final String modelVersion;
  final DateTime createdAt;
  final DateTime? updatedAt;

  factory AIPrediction.fromJson(Map<String, dynamic> json) {
    DateTime parseDate(dynamic v) {
      if (v == null) return DateTime.now();
      return DateTime.tryParse(v.toString()) ?? DateTime.now();
    }

    return AIPrediction(
      id: (json['id'] as num?)?.toInt() ?? 0,
      intersectionId: (json['intersection_id'] as num?)?.toInt(),
      predictionType: (json['prediction_type'] as String?) ?? 'congestion',
      predictedFor: parseDate(json['predicted_for']),
      payload: (json['payload'] as Map<String, dynamic>?) ?? {},
      confidence: (json['confidence'] as num?)?.toDouble(),
      modelVersion: (json['model_version'] as String?) ?? '1.0.0',
      createdAt: parseDate(json['created_at']),
      updatedAt: json['updated_at'] != null
          ? DateTime.tryParse(json['updated_at'].toString())
          : null,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'intersection_id': intersectionId,
      'prediction_type': predictionType,
      'predicted_for': predictedFor.toIso8601String(),
      'payload': payload,
      'confidence': confidence,
      'model_version': modelVersion,
      'created_at': createdAt.toIso8601String(),
      'updated_at': updatedAt?.toIso8601String(),
    };
  }
}

/// Paginated AI predictions list response matching GET `/ai-predictions`.
class PaginatedAIPredictions {
  const PaginatedAIPredictions({
    required this.items,
    required this.total,
    required this.page,
    required this.perPage,
    required this.pages,
  });

  final List<AIPrediction> items;
  final int total;
  final int page;
  final int perPage;
  final int pages;

  factory PaginatedAIPredictions.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'];
    List<AIPrediction> itemList = [];
    if (rawItems is List) {
      itemList = rawItems
          .whereType<Map<String, dynamic>>()
          .map(AIPrediction.fromJson)
          .toList();
    }

    return PaginatedAIPredictions(
      items: itemList,
      total: (json['total'] as num?)?.toInt() ?? itemList.length,
      page: (json['page'] as num?)?.toInt() ?? 1,
      perPage: (json['per_page'] as num?)?.toInt() ?? 20,
      pages: (json['pages'] as num?)?.toInt() ?? 1,
    );
  }
}
