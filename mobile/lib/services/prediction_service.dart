import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/ai_decision.dart';
import '../models/prediction.dart';
import 'api_client.dart';
import 'auth_service.dart';

/// Helper to map 422 insufficient data responses into typed [InsufficientDataException].
void _mapForecastingInsufficientData(ApiException e, [int? intersectionId]) {
  if (e.statusCode == 422) {
    dynamic payload = e.details;
    if (payload is Map && payload['detail'] is Map) {
      payload = payload['detail'];
    }

    String finalMessage = e.message;
    final msg = e.message.toLowerCase();
    bool isInsufficient =
        msg.contains('insufficient') || msg.contains('not enough data');
    int? rowsFound;
    int? rowsRequired;

    if (payload is Map) {
      final err = payload['error']?.toString().toLowerCase();
      if (err == 'insufficient_data' ||
          payload.toString().contains('insufficient_data')) {
        isInsufficient = true;
      }
      rowsFound = (payload['rows_found'] as num?)?.toInt();
      rowsRequired = (payload['rows_required'] as num?)?.toInt();
      if (payload['message'] != null) {
        finalMessage = payload['message'].toString();
      }
    } else if (payload is List) {
      if (payload.toString().contains('insufficient_data')) {
        isInsufficient = true;
      }
    }

    if (isInsufficient) {
      throw InsufficientDataException(
        message: finalMessage,
        rowsFound: rowsFound,
        rowsRequired: rowsRequired,
        intersectionId: intersectionId,
        details: e.details,
      );
    }
  }
}

/// Service managing deep learning traffic predictions, forecasts, and AI decisions history.
class PredictionService {
  PredictionService({required this.apiClient});

  final ApiClient apiClient;

  /// Retrieves 30-minute forward predictions for an intersection using POST `/forecasting/predict`.
  ///
  /// Maps 422 `insufficient_data` or status `insufficient_data` to [InsufficientDataException].
  Future<PredictionResult> getPrediction(int intersectionId) async {
    try {
      final dynamic res = await apiClient.post(
        '/forecasting/predict',
        body: {
          'intersection_ids': [intersectionId],
        },
      );

      if (res is Map<String, dynamic>) {
        // Handle PredictBatchResponse structure
        if (res.containsKey('insufficient') && res['insufficient'] is List) {
          final insufficientList = res['insufficient'] as List;
          final match = insufficientList.cast<dynamic>().firstWhere(
                (item) =>
                    item is Map &&
                    (item['intersection_id'] as num?)?.toInt() == intersectionId,
                orElse: () => null,
              );
          if (match != null && match is Map<String, dynamic>) {
            throw InsufficientDataException(
              message: match['message']?.toString() ??
                  'Not enough telemetry records for forecasting',
              rowsFound: (match['rows_found'] as num?)?.toInt(),
              rowsRequired: (match['rows_required'] as num?)?.toInt() ?? 20,
              intersectionId: intersectionId,
              details: match,
            );
          }
        }

        if (res.containsKey('predictions') && res['predictions'] is List) {
          final predList = res['predictions'] as List;
          final match = predList.cast<dynamic>().firstWhere(
                (item) =>
                    item is Map &&
                    (item['intersection_id'] as num?)?.toInt() == intersectionId,
                orElse: () => null,
              );
          if (match != null && match is Map<String, dynamic>) {
            return PredictionResult.fromJson(match);
          } else if (predList.isNotEmpty && predList.first is Map) {
            return PredictionResult.fromJson(
                predList.first as Map<String, dynamic>);
          }
        }

        // Direct PredictionResult
        if (res['status'] == 'insufficient_data') {
          throw InsufficientDataException(
            message: res['message']?.toString() ??
                'Not enough data yet for predictions',
            rowsFound: (res['rows_found'] as num?)?.toInt(),
            rowsRequired: (res['rows_required'] as num?)?.toInt() ?? 20,
            intersectionId: intersectionId,
            details: res,
          );
        }

        return PredictionResult.fromJson(res);
      }

      throw ApiException(
        statusCode: 500,
        message: 'Invalid prediction response structure',
      );
    } on ApiException catch (e) {
      _mapForecastingInsufficientData(e, intersectionId);
      rethrow;
    }
  }

  /// Retrieves paginated AI predictions from GET `/ai-predictions`.
  Future<PaginatedAIPredictions> getAiPredictions({
    int? intersectionId,
    String? predictionType,
    int page = 1,
    int perPage = 20,
  }) async {
    final queryParams = <String, dynamic>{};
    if (intersectionId != null) {
      queryParams['intersection_id'] = intersectionId;
    }
    if (predictionType != null && predictionType.isNotEmpty) {
      queryParams['prediction_type'] = predictionType;
    }

    final dynamic res = await apiClient.get(
      '/ai-predictions',
      queryParameters: queryParams.isEmpty ? null : queryParams,
      page: page,
      perPage: perPage,
    );

    if (res is Map<String, dynamic>) {
      return PaginatedAIPredictions.fromJson(res);
    }
    return const PaginatedAIPredictions(
      items: [],
      total: 0,
      page: 1,
      perPage: 20,
      pages: 1,
    );
  }

  /// Retrieves paginated AI decisions history from GET `/ai-decisions`.
  Future<PaginatedAIDecisions> getAiDecisions({
    int? intersectionId,
    String? decisionType,
    String? status,
    int page = 1,
    int perPage = 20,
  }) async {
    final queryParams = <String, dynamic>{};
    if (intersectionId != null) {
      queryParams['intersection_id'] = intersectionId;
    }
    if (decisionType != null && decisionType.isNotEmpty) {
      queryParams['decision_type'] = decisionType;
    }
    if (status != null && status.isNotEmpty) {
      queryParams['status'] = status;
    }

    final dynamic res = await apiClient.get(
      '/ai-decisions',
      queryParameters: queryParams.isEmpty ? null : queryParams,
      page: page,
      perPage: perPage,
    );

    if (res is Map<String, dynamic>) {
      return PaginatedAIDecisions.fromJson(res);
    }
    return const PaginatedAIDecisions(
      items: [],
      total: 0,
      page: 1,
      perPage: 20,
      pages: 1,
    );
  }
}

/// Provider supplying the [PredictionService] instance.
final Provider<PredictionService> predictionServiceProvider =
    Provider<PredictionService>((ref) {
  final client = ref.watch(apiClientProvider);
  return PredictionService(apiClient: client);
});
