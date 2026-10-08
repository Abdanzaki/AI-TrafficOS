import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';

import 'api_client.dart';

/// CONTRACT (backend Phase 9 assistant built in parallel — code against these assumptions):
///
/// POST {apiBaseUrl}/api/v1/assistant/chat, Bearer JWT, JSON body:
///   {
///     "message": "string",
///     "history": [
///       {"role": "user" | "assistant", "content": "string"}
///     ],
///     "conversation_id": "optional-string"
///   }
///
/// 200 response:
///   {
///     "answer": "markdown string",
///     "conversation_id": "string",
///     "tool_calls": [
///       {"tool": "string", "arguments": {...}, "result_summary": "string"}
///     ],
///     "provenance": [
///       {"segment": "string", "label": "observed" | "predicted" | "recommended"}
///     ],
///     "insufficient_data": false,
///     "suggested_followups": ["string"]
///   }
///
/// Errors via ApiException:
///   - 401: session expired -> maps to [AssistantUnauthorizedException] (show re-sign-in prompt)
///   - 403: role not permitted -> maps to [AssistantForbiddenException] (permission-restriction state)
///   - 429: rate limited -> maps to [AssistantRateLimitedException] (retryable)
///   - 5xx: server error -> maps to [AssistantServerException] (retryable)
///   - network failure / timeout -> maps to [AssistantNetworkException] (retry)

/// Categorized provenance label identifying data origin and certainty.
enum ProvenanceLabel {
  observed,
  predicted,
  recommended,
  unknown;

  static ProvenanceLabel fromString(String? value) {
    return switch (value?.trim().toLowerCase()) {
      'observed' => ProvenanceLabel.observed,
      'predicted' => ProvenanceLabel.predicted,
      'recommended' => ProvenanceLabel.recommended,
      _ => ProvenanceLabel.unknown,
    };
  }

  String get displayName => switch (this) {
        ProvenanceLabel.observed => 'Observed',
        ProvenanceLabel.predicted => 'Predicted',
        ProvenanceLabel.recommended => 'Recommended',
        ProvenanceLabel.unknown => 'Unknown',
      };
}

/// Provenance segment detailing the specific data backing an answer claim.
class ProvenanceSegment {
  const ProvenanceSegment({
    required this.segment,
    required this.label,
  });

  final String segment;
  final ProvenanceLabel label;

  factory ProvenanceSegment.fromJson(Map<String, dynamic> json) {
    return ProvenanceSegment(
      segment: json['segment'] as String? ?? '',
      label: ProvenanceLabel.fromString(json['label'] as String?),
    );
  }

  Map<String, dynamic> toJson() => {
        'segment': segment,
        'label': label.name,
      };
}

/// Tool execution record triggered by the assistant reasoning agent.
class ToolCall {
  const ToolCall({
    required this.tool,
    required this.arguments,
    required this.resultSummary,
  });

  final String tool;
  final Map<String, dynamic> arguments;
  final String resultSummary;

  factory ToolCall.fromJson(Map<String, dynamic> json) {
    return ToolCall(
      tool: json['tool'] as String? ?? '',
      arguments: (json['arguments'] as Map<String, dynamic>?) ?? const {},
      resultSummary: json['result_summary'] as String? ?? '',
    );
  }

  Map<String, dynamic> toJson() => {
        'tool': tool,
        'arguments': arguments,
        'result_summary': resultSummary,
      };
}

/// Message payload representing conversational turn history.
class AssistantMessage {
  const AssistantMessage({
    required this.role,
    required this.content,
  });

  final String role;
  final String content;

  factory AssistantMessage.fromJson(Map<String, dynamic> json) {
    return AssistantMessage(
      role: json['role'] as String? ?? 'user',
      content: json['content'] as String? ?? '',
    );
  }

  Map<String, dynamic> toJson() => {
        'role': role,
        'content': content,
      };
}

/// Response returned from POST `/assistant/chat`.
class AssistantResponse {
  const AssistantResponse({
    required this.answer,
    required this.conversationId,
    this.toolCalls = const [],
    this.provenance = const [],
    this.insufficientData = false,
    this.suggestedFollowups = const [],
  });

  final String answer;
  final String conversationId;
  final List<ToolCall> toolCalls;
  final List<ProvenanceSegment> provenance;
  final bool insufficientData;
  final List<String> suggestedFollowups;

  factory AssistantResponse.fromJson(Map<String, dynamic> json) {
    return AssistantResponse(
      answer: json['answer'] as String? ?? '',
      conversationId: json['conversation_id'] as String? ?? '',
      toolCalls: (json['tool_calls'] as List<dynamic>?)
              ?.whereType<Map<String, dynamic>>()
              .map(ToolCall.fromJson)
              .toList() ??
          const [],
      provenance: (json['provenance'] as List<dynamic>?)
              ?.whereType<Map<String, dynamic>>()
              .map(ProvenanceSegment.fromJson)
              .toList() ??
          const [],
      insufficientData: json['insufficient_data'] as bool? ?? false,
      suggestedFollowups: (json['suggested_followups'] as List<dynamic>?)
              ?.map((e) => e.toString())
              .toList() ??
          const [],
    );
  }
}

/// Base typed exception thrown by [AssistantService].
abstract class AssistantException implements Exception {
  const AssistantException(this.message, {this.statusCode});
  final String message;
  final int? statusCode;

  @override
  String toString() => 'AssistantException: $message (status: $statusCode)';
}

/// Thrown when session credentials are invalid or expired (HTTP 401).
class AssistantUnauthorizedException extends AssistantException {
  const AssistantUnauthorizedException([
    super.message = 'Session expired. Please sign in again.',
  ]) : super(statusCode: 401);
}

/// Thrown when role is not permitted to use assistant (HTTP 403).
class AssistantForbiddenException extends AssistantException {
  const AssistantForbiddenException({
    String message =
        'Access denied. Your role is not permitted to access AI Assistant.',
    this.role,
    this.details,
  }) : super(message, statusCode: 403);

  final String? role;
  final dynamic details;
}

/// Thrown when request rate limits are hit (HTTP 429).
class AssistantRateLimitedException extends AssistantException {
  const AssistantRateLimitedException([
    super.message = 'Request rate limit exceeded. Please wait a moment.',
  ]) : super(statusCode: 429);
}

/// Thrown on server-side processing errors (HTTP 5xx).
class AssistantServerException extends AssistantException {
  const AssistantServerException({
    String message = 'AI Assistant service encountered an internal error.',
    int statusCode = 500,
  }) : super(message, statusCode: statusCode);
}

/// Thrown on network or transport failure.
class AssistantNetworkException extends AssistantException {
  const AssistantNetworkException([
    super.message =
        'Network communication failure. Please check your connection.',
  ]) : super(statusCode: null);
}

/// Thrown on unexpected or malformed assistant errors.
class AssistantGeneralException extends AssistantException {
  const AssistantGeneralException(super.message, {super.statusCode});
}

/// Assistant service client interacting with POST `/assistant/chat`.
class AssistantService {
  AssistantService({required this.apiClient});

  final ApiClient apiClient;

  /// Maximum prior conversation messages forwarded to backend.
  static const int maxHistoryLength = 20;

  /// Sends a user message with past conversational context and optional conversation ID.
  Future<AssistantResponse> chat({
    required String message,
    List<AssistantMessage>? history,
    String? conversationId,
  }) async {
    // Truncate history to the last ~20 messages
    final truncatedHistory = (history != null && history.length > maxHistoryLength)
        ? history.sublist(history.length - maxHistoryLength)
        : (history ?? const <AssistantMessage>[]);

    final body = <String, dynamic>{
      'message': message,
      'history': truncatedHistory.map((m) => m.toJson()).toList(),
    };
    if (conversationId != null && conversationId.isNotEmpty) {
      body['conversation_id'] = conversationId;
    }

    // Security guard: Never log message contents or PII beyond debug character count
    if (kDebugMode) {
      debugPrint(
        'AssistantService: POST /assistant/chat [len: ${message.length}, history_items: ${truncatedHistory.length}]',
      );
    }

    try {
      final dynamic response = await apiClient.post(
        '/assistant/chat',
        body: body,
      );

      if (response is Map<String, dynamic>) {
        return AssistantResponse.fromJson(response);
      }
      throw const AssistantGeneralException(
        'Invalid response format received from assistant API',
      );
    } on ApiException catch (e) {
      if (e.isUnauthorized) {
        throw AssistantUnauthorizedException(e.message);
      }
      if (e.isForbidden) {
        String? role;
        if (e.details is Map<String, dynamic>) {
          role = (e.details['role'] ?? e.details['required_role'])?.toString();
        }
        throw AssistantForbiddenException(
          message: e.message,
          role: role,
          details: e.details,
        );
      }
      if (e.statusCode == 429) {
        throw AssistantRateLimitedException(e.message);
      }
      if (e.statusCode != null && e.statusCode! >= 500) {
        throw AssistantServerException(
          message: e.message,
          statusCode: e.statusCode!,
        );
      }
      if (e.isNetworkError || e.statusCode == 408) {
        throw AssistantNetworkException(e.message);
      }
      throw AssistantGeneralException(e.message, statusCode: e.statusCode);
    } on TimeoutException catch (e) {
      throw AssistantNetworkException('Connection timed out: ${e.message}');
    } on SocketException catch (e) {
      throw AssistantNetworkException('Network unreachable: ${e.message}');
    } catch (e) {
      if (e is AssistantException) rethrow;
      throw AssistantGeneralException('Unexpected error: $e');
    }
  }
}
