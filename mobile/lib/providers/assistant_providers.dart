import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../services/assistant_service.dart';
import '../services/auth_service.dart';

/// Provider for the [AssistantService] instance.
final Provider<AssistantService> assistantServiceProvider =
    Provider<AssistantService>((ref) {
  final apiClient = ref.watch(apiClientProvider);
  return AssistantService(apiClient: apiClient);
});

/// Represents a single message bubble within the mobile assistant chat.
class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.role,
    required this.content,
    required this.timestamp,
    this.toolCalls = const [],
    this.provenance = const [],
    this.insufficientData = false,
    this.suggestedFollowups = const [],
    this.isError = false,
    this.elapsedSeconds,
  });

  final String id;
  final String role; // 'user' or 'assistant'
  final String content;
  final DateTime timestamp;
  final List<ToolCall> toolCalls;
  final List<ProvenanceSegment> provenance;
  final bool insufficientData;
  final List<String> suggestedFollowups;
  final bool isError;
  final double? elapsedSeconds;

  bool get isUser => role == 'user';
  bool get isAssistant => role == 'assistant';

  AssistantMessage toAssistantMessage() =>
      AssistantMessage(role: role, content: content);
}

/// Reactive state for the AI Assistant chat conversation.
class AssistantChatState {
  const AssistantChatState({
    this.messages = const [],
    this.isLoading = false,
    this.error,
    this.conversationId,
    this.insufficientData = false,
    this.suggestedFollowups = const [],
  });

  final List<ChatMessage> messages;
  final bool isLoading;
  final AssistantException? error;
  final String? conversationId;
  final bool insufficientData;
  final List<String> suggestedFollowups;

  AssistantChatState copyWith({
    List<ChatMessage>? messages,
    bool? isLoading,
    AssistantException? Function()? error,
    String? Function()? conversationId,
    bool? insufficientData,
    List<String>? suggestedFollowups,
  }) {
    return AssistantChatState(
      messages: messages ?? this.messages,
      isLoading: isLoading ?? this.isLoading,
      error: error != null ? error() : this.error,
      conversationId:
          conversationId != null ? conversationId() : this.conversationId,
      insufficientData: insufficientData ?? this.insufficientData,
      suggestedFollowups: suggestedFollowups ?? this.suggestedFollowups,
    );
  }
}

/// State notifier managing assistant conversation turns, sending messages, and retrying.
///
/// NOTE on local persistence:
/// `shared_preferences` is not included in pubspec.yaml; conversation history is
/// preserved in-memory within this notifier for the duration of the current application session.
class AssistantChatNotifier extends StateNotifier<AssistantChatState> {
  AssistantChatNotifier(this.assistantService)
      : super(const AssistantChatState());

  final AssistantService assistantService;
  bool _isCancelled = false;

  /// Cancels any in-flight assistant request and re-enables composer.
  void cancelRequest() {
    _isCancelled = true;
    state = state.copyWith(isLoading: false);
  }

  /// Loads conversational history.
  ///
  /// Note: As `shared_preferences` is not installed in pubspec.yaml, conversation
  /// history operates in-memory for the operator's current session lifecycle.
  Future<void> loadHistory() async {
    // In-memory state already retained across widget rebuilds in Riverpod container.
  }

  /// Sends a user question or directive to the backend assistant.
  Future<void> sendMessage(String text) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty || state.isLoading) return;

    _isCancelled = false;
    final userMessage = ChatMessage(
      id: 'usr_${DateTime.now().microsecondsSinceEpoch}',
      role: 'user',
      content: trimmed,
      timestamp: DateTime.now(),
    );

    // Collect preceding conversational history turns (excluding current new message)
    final priorHistory = state.messages
        .where((m) => !m.isError)
        .map((m) => m.toAssistantMessage())
        .toList();

    state = state.copyWith(
      messages: [...state.messages, userMessage],
      isLoading: true,
      error: () => null,
    );

    final stopwatch = Stopwatch()..start();
    try {
      final response = await assistantService.chat(
        message: trimmed,
        history: priorHistory,
        conversationId: state.conversationId,
      );
      stopwatch.stop();

      if (_isCancelled) return;

      final elapsedMs = stopwatch.elapsedMilliseconds;
      final elapsedSec = elapsedMs > 0 ? (elapsedMs / 1000.0) : 1.2;

      final assistantMessage = ChatMessage(
        id: 'ast_${DateTime.now().microsecondsSinceEpoch}',
        role: 'assistant',
        content: response.answer,
        timestamp: DateTime.now(),
        toolCalls: response.toolCalls,
        provenance: response.provenance,
        insufficientData: response.insufficientData,
        suggestedFollowups: response.suggestedFollowups,
        elapsedSeconds: elapsedSec,
      );

      if (_isCancelled) return;

      state = state.copyWith(
        messages: [...state.messages, assistantMessage],
        isLoading: false,
        conversationId: () => response.conversationId,
        insufficientData: response.insufficientData,
        suggestedFollowups: response.suggestedFollowups,
        error: () => null,
      );
    } on AssistantException catch (e) {
      if (_isCancelled) return;
      state = state.copyWith(
        isLoading: false,
        error: () => e,
      );
    } catch (e) {
      if (_isCancelled) return;
      state = state.copyWith(
        isLoading: false,
        error: () => AssistantGeneralException('Unexpected error: $e'),
      );
    }
  }

  /// Retries sending the last user message after an error.
  Future<void> retry() async {
    if (state.isLoading) return;

    // Find the latest user message
    final lastUserMsgIndex = state.messages.lastIndexWhere((m) => m.isUser);
    if (lastUserMsgIndex == -1) return;

    final lastUserMsg = state.messages[lastUserMsgIndex];

    // Collect prior history before this last user message
    final priorHistory = state.messages
        .sublist(0, lastUserMsgIndex)
        .where((m) => !m.isError)
        .map((m) => m.toAssistantMessage())
        .toList();

    _isCancelled = false;
    state = state.copyWith(
      isLoading: true,
      error: () => null,
    );

    final stopwatch = Stopwatch()..start();
    try {
      final response = await assistantService.chat(
        message: lastUserMsg.content,
        history: priorHistory,
        conversationId: state.conversationId,
      );
      stopwatch.stop();

      if (_isCancelled) return;

      final elapsedMs = stopwatch.elapsedMilliseconds;
      final elapsedSec = elapsedMs > 0 ? (elapsedMs / 1000.0) : 1.2;

      final assistantMessage = ChatMessage(
        id: 'ast_${DateTime.now().microsecondsSinceEpoch}',
        role: 'assistant',
        content: response.answer,
        timestamp: DateTime.now(),
        toolCalls: response.toolCalls,
        provenance: response.provenance,
        insufficientData: response.insufficientData,
        suggestedFollowups: response.suggestedFollowups,
        elapsedSeconds: elapsedSec,
      );

      if (_isCancelled) return;

      state = state.copyWith(
        messages: [...state.messages, assistantMessage],
        isLoading: false,
        conversationId: () => response.conversationId,
        insufficientData: response.insufficientData,
        suggestedFollowups: response.suggestedFollowups,
        error: () => null,
      );
    } on AssistantException catch (e) {
      if (_isCancelled) return;
      state = state.copyWith(
        isLoading: false,
        error: () => e,
      );
    } catch (e) {
      if (_isCancelled) return;
      state = state.copyWith(
        isLoading: false,
        error: () => AssistantGeneralException('Unexpected error: $e'),
      );
    }
  }

  /// Clears the active chat session and starts a new conversation.
  void newConversation() {
    state = const AssistantChatState();
  }
}

/// Provider managing active conversation state.
final StateNotifierProvider<AssistantChatNotifier, AssistantChatState>
    assistantChatProvider =
    StateNotifierProvider<AssistantChatNotifier, AssistantChatState>((ref) {
  final service = ref.watch(assistantServiceProvider);
  return AssistantChatNotifier(service);
});
