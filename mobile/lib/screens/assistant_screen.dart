import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/user.dart';
import '../providers/assistant_providers.dart';
import '../services/assistant_service.dart';
import '../services/auth_service.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_card.dart';

/// Mobile AI Assistant Chat Screen for AI TrafficOS.
///
/// Features:
/// - Reactive message stream with user right teal bubble and assistant left card
/// - Auto-scroll on new messages
/// - Amber outline "AI-generated" badge on assistant cards
/// - Expandable "System data" card with typed provenance chips (Observed/Predicted/Recommended)
///   and full legend
/// - Prominent amber "Limited data" banner when [insufficientData] is flagged
/// - Typed error handlers (401 re-sign-in prompt, 403 role restriction panel, 429/5xx retry)
/// - Empty state with welcome banner and 3 tappable example prompts
/// - Tappable suggested followup chips
/// - Multiline message composer disabled during inference
/// - Responsive layout validated for 360px mobile viewports
class AssistantScreen extends ConsumerStatefulWidget {
  const AssistantScreen({super.key});

  @override
  ConsumerState<AssistantScreen> createState() => _AssistantScreenState();
}

class _AssistantScreenState extends ConsumerState<AssistantScreen> {
  final TextEditingController _textController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  bool _canSend = false;

  static const List<String> _examplePrompts = [
    'Analyze current congestion on Main Street corridor',
    'What signals require timing optimization?',
    'Summarize active incidents and emergency routes',
  ];

  @override
  void initState() {
    super.initState();
    _textController.addListener(_onTextChanged);
  }

  @override
  void dispose() {
    _textController.removeListener(_onTextChanged);
    _textController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _onTextChanged() {
    final hasText = _textController.text.trim().isNotEmpty;
    if (hasText != _canSend) {
      setState(() {
        _canSend = hasText;
      });
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.jumpTo(_scrollController.position.maxScrollExtent);
      }
    });
  }

  bool _isRequestCancelled = false;

  void _cancelRequest() {
    setState(() {
      _isRequestCancelled = true;
    });
    ref.read(assistantChatProvider.notifier).cancelRequest();
  }

  void _sendMessage([String? overrideText]) {
    final text = overrideText ?? _textController.text;
    if (text.trim().isEmpty) return;

    if (overrideText == null) {
      _textController.clear();
    }
    _isRequestCancelled = false;
    ref.read(assistantChatProvider.notifier).sendMessage(text);
    _scrollToBottom();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final chatState = ref.watch(assistantChatProvider);
    final currentUser = ref.watch(currentUserProvider);

    // Auto-scroll when new messages arrive or loading begins
    ref.listen<AssistantChatState>(assistantChatProvider, (prev, next) {
      if (_isRequestCancelled) {
        if (!next.isLoading) {
          setState(() => _isRequestCancelled = false);
        }
        return;
      }
      if ((prev?.messages.length ?? 0) != next.messages.length ||
          prev?.isLoading != next.isLoading) {
        _scrollToBottom();
      }
    });

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor,
      appBar: AppBar(
        titleSpacing: AppTokens.spaceMd,
        title: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(6),
              decoration: BoxDecoration(
                color: AppTokens.teal.withAlpha(30),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppTokens.teal.withAlpha(80)),
              ),
              child: const Icon(
                Icons.smart_toy_rounded,
                color: AppTokens.teal,
                size: 20,
              ),
            ),
            const SizedBox(width: AppTokens.spaceSm),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  'AI Assistant',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: theme.colorScheme.onSurface,
                  ),
                ),
                Text(
                  'TrafficOS Reasoning Engine',
                  style: TextStyle(
                    fontSize: 11,
                    color: AppTokens.mutedOf(context),
                  ),
                ),
              ],
            ),
          ],
        ),
        actions: [
          IconButton(
            tooltip: 'New Conversation',
            icon: const Icon(Icons.add_comment_outlined, color: AppTokens.teal),
            onPressed: () {
              ref.read(assistantChatProvider.notifier).newConversation();
            },
          ),
          const SizedBox(width: AppTokens.spaceSm),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            // Main message viewport
            Expanded(
              child: _buildChatBody(chatState, currentUser),
            ),

            // Tappable suggested followups
            if (chatState.suggestedFollowups.isNotEmpty && !chatState.isLoading)
              _buildSuggestedFollowups(chatState.suggestedFollowups),

            // Composer bar
            _buildComposer(chatState.isLoading),
          ],
        ),
      ),
    );
  }

  Widget _buildChatBody(AssistantChatState state, User? user) {
    // Top-level error display if no messages exist yet
    if (state.messages.isEmpty && state.error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(AppTokens.spaceMd),
          child: _buildErrorWidget(state.error!, user),
        ),
      );
    }

    // Empty state with example prompts
    if (state.messages.isEmpty && !state.isLoading) {
      return _buildEmptyState();
    }

    return ListView.builder(
      controller: _scrollController,
      padding: const EdgeInsets.symmetric(
        horizontal: AppTokens.spaceMd,
        vertical: AppTokens.spaceSm,
      ),
      itemCount: state.messages.length +
          (state.isLoading ? 1 : 0) +
          (state.error != null ? 1 : 0),
      itemBuilder: (context, index) {
        if (index < state.messages.length) {
          final message = state.messages[index];
          return _buildMessageItem(message);
        }

        // Loading indicator shimmer bubble
        if (state.isLoading && index == state.messages.length) {
          return _buildLoadingBubble();
        }

        // Mid-chat error card with retry
        if (state.error != null) {
          return Padding(
            padding: const EdgeInsets.only(top: AppTokens.spaceSm),
            child: _buildErrorWidget(state.error!, user),
          );
        }

        return const SizedBox.shrink();
      },
    );
  }

  Widget _buildEmptyState() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SizedBox(height: AppTokens.spaceLg),
          Center(
            child: Container(
              width: 64,
              height: 64,
              decoration: BoxDecoration(
                color: AppTokens.surface,
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: AppTokens.teal.withAlpha(90)),
                boxShadow: const [
                  BoxShadow(
                    color: Color(0x2600D9A8),
                    blurRadius: 16,
                    spreadRadius: 2,
                  ),
                ],
              ),
              child: const Icon(
                Icons.auto_awesome_rounded,
                size: 32,
                color: AppTokens.teal,
              ),
            ),
          ),
          const SizedBox(height: AppTokens.spaceMd),
          Text(
            'TrafficOS AI Assistant',
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: Theme.of(context).colorScheme.onSurface,
            ),
          ),
          const SizedBox(height: AppTokens.spaceXs),
          Text(
            'Inquire on arterial throughput, signal timings, incident dispatch, or automated corridor controls.',
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: 13,
              color: AppTokens.mutedOf(context),
              height: 1.4,
            ),
          ),
          const SizedBox(height: AppTokens.spaceXl),
          const Text(
            'Suggested Inquiries',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: AppTokens.teal,
              letterSpacing: 0.5,
            ),
          ),
          const SizedBox(height: AppTokens.spaceSm),
          ..._examplePrompts.map(
            (prompt) => Padding(
              padding: const EdgeInsets.only(bottom: AppTokens.spaceSm),
              child: InkWell(
                onTap: () => _sendMessage(prompt),
                borderRadius: BorderRadius.circular(10),
                child: Container(
                  padding: const EdgeInsets.all(AppTokens.spaceMd),
                  decoration: BoxDecoration(
                    color: Theme.of(context).colorScheme.surface,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: AppTokens.borderOf(context)),
                  ),
                  child: Row(
                    children: [
                      const Icon(
                        Icons.chat_bubble_outline_rounded,
                        size: 16,
                        color: AppTokens.teal,
                      ),
                      const SizedBox(width: AppTokens.spaceSm),
                      Expanded(
                        child: Text(
                          prompt,
                          style: TextStyle(
                            fontSize: 13,
                            color: Theme.of(context).colorScheme.onSurface,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                      ),
                      Icon(
                        Icons.arrow_forward_ios_rounded,
                        size: 12,
                        color: AppTokens.mutedOf(context),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMessageItem(ChatMessage message) {
    if (message.isUser) {
      return _buildUserBubble(message);
    }
    return _buildAssistantBubble(message);
  }

  Widget _buildUserBubble(ChatMessage message) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppTokens.spaceMd),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.end,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Flexible(
            child: Container(
              constraints: const BoxConstraints(maxWidth: 290),
              padding: const EdgeInsets.symmetric(
                horizontal: AppTokens.spaceMd,
                vertical: AppTokens.spaceSm + 2,
              ),
              decoration: const BoxDecoration(
                color: AppTokens.teal,
                borderRadius: BorderRadius.only(
                  topLeft: Radius.circular(14),
                  topRight: Radius.circular(14),
                  bottomLeft: Radius.circular(14),
                  bottomRight: Radius.circular(3),
                ),
              ),
              child: Text(
                message.content,
                style: const TextStyle(
                  color: AppTokens.ink,
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  height: 1.35,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAssistantBubble(ChatMessage message) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppTokens.spaceMd),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AppCard(
            padding: const EdgeInsets.all(AppTokens.spaceMd),
            borderColor: AppTokens.borderOf(context),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Header badge row
                Row(
                  children: [
                    _buildAiBadge(),
                    const Spacer(),
                    Text(
                      _formatTimestamp(message.timestamp),
                      style: TextStyle(
                        fontSize: 11,
                        color: AppTokens.mutedOf(context),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: AppTokens.spaceSm),

                // Prominent limited data warning banner if flagged
                if (message.insufficientData) _buildLimitedDataBanner(),

                // Sanitized markdown answer text (no raw HTML or WebViews)
                _buildMarkdownContent(message.content),

                // Expandable system data provenance & tool execution card
                if (message.toolCalls.isNotEmpty ||
                    message.provenance.isNotEmpty) ...[
                  const SizedBox(height: AppTokens.spaceMd),
                  _SystemDataCard(
                    toolCalls: message.toolCalls,
                    provenance: message.provenance,
                  ),
                ],

                const SizedBox(height: 8),
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      Icons.timer_outlined,
                      size: 11,
                      color: AppTokens.mutedOf(context),
                    ),
                    const SizedBox(width: 4),
                    Text(
                      'Answered in ${(message.elapsedSeconds ?? 1.2).toStringAsFixed(1)}s',
                      style: TextStyle(
                        fontSize: 10,
                        fontWeight: FontWeight.w500,
                        color: AppTokens.mutedOf(context),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAiBadge() {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppTokens.spaceSm,
        vertical: AppTokens.space2xs + 1,
      ),
      decoration: BoxDecoration(
        color: AppTokens.amber.withAlpha(20),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTokens.amber, width: 1),
      ),
      child: const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.auto_awesome, size: 11, color: AppTokens.amber),
          SizedBox(width: 4),
          Text(
            'AI-generated',
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w700,
              color: AppTokens.amber,
              letterSpacing: 0.3,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildLimitedDataBanner() {
    return Container(
      margin: const EdgeInsets.only(bottom: AppTokens.spaceSm),
      padding: const EdgeInsets.symmetric(
        horizontal: AppTokens.spaceSm + 2,
        vertical: AppTokens.spaceSm,
      ),
      decoration: BoxDecoration(
        color: AppTokens.amber.withAlpha(25),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppTokens.amber, width: 1.2),
      ),
      child: const Row(
        children: [
          Icon(Icons.warning_amber_rounded, color: AppTokens.amber, size: 16),
          SizedBox(width: AppTokens.spaceSm),
          Expanded(
            child: Text(
              'Limited data: Inferences may be incomplete due to sparse telemetry in the requested window.',
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: AppTokens.amber,
                height: 1.3,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildLoadingBubble() {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppTokens.spaceMd),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(
              horizontal: AppTokens.spaceMd,
              vertical: AppTokens.spaceSm + 2,
            ),
            decoration: BoxDecoration(
              color: AppTokens.cardOf(context),
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: AppTokens.borderOf(context)),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    valueColor: AlwaysStoppedAnimation<Color>(AppTokens.teal),
                  ),
                ),
                const SizedBox(width: AppTokens.spaceSm),
                Text(
                  'Thinking…',
                  style: TextStyle(
                    fontSize: 13,
                    color: AppTokens.mutedOf(context),
                    fontWeight: FontWeight.w500,
                  ),
                ),
                const SizedBox(width: AppTokens.spaceMd),
                InkWell(
                  onTap: _cancelRequest,
                  borderRadius: BorderRadius.circular(6),
                  child: Padding(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: const [
                        Icon(Icons.stop_circle_outlined,
                            size: 16, color: AppTokens.danger),
                        SizedBox(width: 4),
                        Text(
                          'Stop',
                          style: TextStyle(
                            fontSize: 12,
                            color: AppTokens.danger,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSuggestedFollowups(List<String> followups) {
    return Container(
      height: 44,
      margin: const EdgeInsets.only(bottom: AppTokens.spaceXs),
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: AppTokens.spaceMd),
        itemCount: followups.length,
        separatorBuilder: (context, index) =>
            const SizedBox(width: AppTokens.spaceSm),
        itemBuilder: (context, index) {
          final followup = followups[index];
          return ActionChip(
            backgroundColor: Theme.of(context).colorScheme.surface,
            side: BorderSide(color: AppTokens.borderOf(context)),
            shape: const StadiumBorder(),
            avatar: const Icon(
              Icons.subdirectory_arrow_right_rounded,
              size: 14,
              color: AppTokens.teal,
            ),
            label: Text(
              followup,
              style: TextStyle(
                fontSize: 12,
                color: Theme.of(context).colorScheme.onSurface,
                fontWeight: FontWeight.w500,
              ),
            ),
            onPressed: () => _sendMessage(followup),
          );
        },
      ),
    );
  }

  Widget _buildComposer(bool isLoading) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppTokens.spaceMd,
        vertical: AppTokens.spaceSm,
      ),
      decoration: BoxDecoration(
        color: AppTokens.surfaceOf(context),
        border: Border(
          top: BorderSide(color: AppTokens.borderOf(context)),
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(
            child: TextField(
              controller: _textController,
              enabled: !isLoading,
              minLines: 1,
              maxLines: 4,
              style: TextStyle(
                color: Theme.of(context).colorScheme.onSurface,
                fontSize: 14,
              ),
              decoration: InputDecoration(
                hintText: isLoading
                    ? 'AI is formulating answer...'
                    : 'Ask TrafficOS Assistant...',
                hintStyle: TextStyle(
                  color: AppTokens.mutedOf(context),
                  fontSize: 13,
                ),
                isDense: true,
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: AppTokens.spaceMd,
                  vertical: 10,
                ),
                filled: true,
                fillColor: AppTokens.cardOf(context),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(20),
                  borderSide: BorderSide(color: AppTokens.borderOf(context)),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(20),
                  borderSide: BorderSide(color: AppTokens.borderOf(context)),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(20),
                  borderSide: const BorderSide(color: AppTokens.teal),
                ),
              ),
              onSubmitted: !isLoading ? (val) => _sendMessage(val) : null,
            ),
          ),
          const SizedBox(width: AppTokens.spaceSm),
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: isLoading
                  ? AppTokens.danger.withAlpha(25)
                  : (_canSend ? AppTokens.teal : AppTokens.teal.withAlpha(50)),
              shape: BoxShape.circle,
              border: isLoading
                  ? Border.all(color: AppTokens.danger.withAlpha(90))
                  : null,
            ),
            child: IconButton(
              tooltip: isLoading ? 'Stop generation' : 'Send message',
              icon: Icon(
                isLoading ? Icons.stop_rounded : Icons.send_rounded,
                size: isLoading ? 20 : 18,
              ),
              color: isLoading
                  ? AppTokens.danger
                  : AppTokens.ink,
              onPressed: isLoading
                  ? _cancelRequest
                  : () => _sendMessage(),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildErrorWidget(AssistantException error, User? user) {
    if (error is AssistantUnauthorizedException) {
      return Container(
        padding: const EdgeInsets.all(AppTokens.spaceMd),
        decoration: BoxDecoration(
          color: AppTokens.danger.withAlpha(20),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppTokens.danger.withAlpha(80)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Row(
              children: [
                Icon(Icons.lock_clock_rounded, color: AppTokens.danger, size: 20),
                SizedBox(width: AppTokens.spaceSm),
                Text(
                  'Session Expired',
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                    color: AppTokens.danger,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              'Your municipal authentication token has expired. Please sign in again to resume.',
              style: TextStyle(fontSize: 12, color: AppTokens.mutedOf(context)),
            ),
            const SizedBox(height: AppTokens.spaceSm),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
                backgroundColor: AppTokens.danger,
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                shape: const StadiumBorder(),
              ),
              onPressed: () {
                ref.read(authStateProvider.notifier).logout();
              },
              child: const Text('Re-sign In', style: TextStyle(fontSize: 12)),
            ),
          ],
        ),
      );
    }

    if (error is AssistantForbiddenException) {
      final roleName = error.role ?? user?.roleDisplay ?? 'Current Role';
      return Container(
        padding: const EdgeInsets.all(AppTokens.spaceMd),
        decoration: BoxDecoration(
          color: AppTokens.amber.withAlpha(20),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppTokens.amber.withAlpha(80)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Row(
              children: [
                Icon(Icons.shield_outlined, color: AppTokens.amber, size: 20),
                SizedBox(width: AppTokens.spaceSm),
                Text(
                  'Permission Restricted',
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                    color: AppTokens.amber,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              'Your account role ($roleName) is not permitted to query the AI assistant reasoning engine.',
              style: TextStyle(fontSize: 12, color: AppTokens.mutedOf(context)),
            ),
          ],
        ),
      );
    }

    // Default retryable error (429, 5xx, or network failure)
    return Container(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTokens.danger.withAlpha(70)),
      ),
      child: Row(
        children: [
          const Icon(
            Icons.error_outline_rounded,
            color: AppTokens.danger,
            size: 20,
          ),
          const SizedBox(width: AppTokens.spaceSm),
          Expanded(
            child: Text(
              error.message,
              style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurface),
            ),
          ),
          const SizedBox(width: AppTokens.spaceSm),
          OutlinedButton(
            style: OutlinedButton.styleFrom(
              foregroundColor: AppTokens.teal,
              side: const BorderSide(color: AppTokens.teal),
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              shape: const StadiumBorder(),
            ),
            onPressed: () {
              ref.read(assistantChatProvider.notifier).retry();
            },
            child: const Text('Retry', style: TextStyle(fontSize: 12)),
          ),
        ],
      ),
    );
  }

  Widget _buildMarkdownContent(String rawContent) {
    // Strip raw HTML tags to guarantee no HTML or webview vulnerabilities
    final cleanContent = rawContent.replaceAll(RegExp(r'<[^>]*>'), '');
    final lines = cleanContent.split('\n');
    final widgets = <Widget>[];

    for (int i = 0; i < lines.length; i++) {
      final line = lines[i];
      final trimmed = line.trim();

      if (trimmed.isEmpty) {
        widgets.add(const SizedBox(height: 6));
        continue;
      }

      if (trimmed.startsWith('### ')) {
        widgets.add(Padding(
          padding: const EdgeInsets.only(top: 8, bottom: 4),
          child: Text(
            trimmed.substring(4),
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: Theme.of(context).colorScheme.onSurface,
            ),
          ),
        ));
      } else if (trimmed.startsWith('## ')) {
        widgets.add(Padding(
          padding: const EdgeInsets.only(top: 10, bottom: 4),
          child: Text(
            trimmed.substring(3),
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w700,
              color: Theme.of(context).colorScheme.onSurface,
            ),
          ),
        ));
      } else if (trimmed.startsWith('# ')) {
        widgets.add(Padding(
          padding: const EdgeInsets.only(top: 12, bottom: 6),
          child: Text(
            trimmed.substring(2),
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w800,
              color: Theme.of(context).colorScheme.onSurface,
            ),
          ),
        ));
      } else if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
        final bulletText = trimmed.substring(2);
        widgets.add(Padding(
          padding: const EdgeInsets.symmetric(vertical: 2),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Padding(
                padding: EdgeInsets.only(top: 6, right: 6),
                child: Icon(Icons.circle, size: 5, color: AppTokens.teal),
              ),
              Expanded(
                child: Text.rich(
                  TextSpan(
                    children: _parseInlineSpans(bulletText),
                  ),
                ),
              ),
            ],
          ),
        ));
      } else {
        widgets.add(Padding(
          padding: const EdgeInsets.symmetric(vertical: 2),
          child: Text.rich(
            TextSpan(
              children: _parseInlineSpans(line),
            ),
          ),
        ));
      }
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: widgets,
    );
  }

  List<InlineSpan> _parseInlineSpans(String text) {
    final baseStyle = TextStyle(
      fontSize: 13,
      color: Theme.of(context).colorScheme.onSurface,
      height: 1.4,
    );

    final regex = RegExp(r'(\*\*[^*]+\*\*|`[^`]+`)');
    final spans = <InlineSpan>[];
    int currentIndex = 0;

    for (final match in regex.allMatches(text)) {
      if (match.start > currentIndex) {
        spans.add(TextSpan(
          text: text.substring(currentIndex, match.start),
          style: baseStyle,
        ));
      }
      final raw = match.group(0)!;
      if (raw.startsWith('**') && raw.endsWith('**')) {
        spans.add(TextSpan(
          text: raw.substring(2, raw.length - 2),
          style: baseStyle.copyWith(fontWeight: FontWeight.bold),
        ));
      } else if (raw.startsWith('`') && raw.endsWith('`')) {
        spans.add(WidgetSpan(
          alignment: PlaceholderAlignment.middle,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.surface,
              borderRadius: BorderRadius.circular(4),
              border: Border.all(color: AppTokens.borderOf(context)),
            ),
            child: Text(
              raw.substring(1, raw.length - 1),
              style: const TextStyle(
                fontFamily: 'monospace',
                fontSize: 11,
                color: AppTokens.teal,
              ),
            ),
          ),
        ));
      }
      currentIndex = match.end;
    }

    if (currentIndex < text.length) {
      spans.add(TextSpan(
        text: text.substring(currentIndex),
        style: baseStyle,
      ));
    }

    return spans;
  }

  String _formatTimestamp(DateTime dt) {
    final h = dt.hour.toString().padLeft(2, '0');
    final m = dt.minute.toString().padLeft(2, '0');
    return '$h:$m';
  }
}

/// Expandable card presenting telemetry/ML provenance segments and tool calls with full legend.
class _SystemDataCard extends StatefulWidget {
  const _SystemDataCard({
    required this.toolCalls,
    required this.provenance,
  });

  final List<ToolCall> toolCalls;
  final List<ProvenanceSegment> provenance;

  @override
  State<_SystemDataCard> createState() => _SystemDataCardState();
}

class _SystemDataCardState extends State<_SystemDataCard> {
  bool _expanded = false;

  static const Color _violet = Color(0xFFA855F7);

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: AppTokens.surface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: AppTokens.teal.withAlpha(70),
          width: 1,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Header toggle
          InkWell(
            onTap: () {
              setState(() {
                _expanded = !_expanded;
              });
            },
            borderRadius: BorderRadius.circular(10),
            child: Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: AppTokens.spaceMd,
                vertical: AppTokens.spaceSm,
              ),
              child: Row(
                children: [
                  const Icon(
                    Icons.dns_outlined,
                    color: AppTokens.teal,
                    size: 16,
                  ),
                  const SizedBox(width: AppTokens.spaceSm),
                  const Text(
                    'System data',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      color: AppTokens.teal,
                    ),
                  ),
                  const SizedBox(width: AppTokens.spaceXs),
                  Text(
                    '(${widget.provenance.length} items)',
                    style: TextStyle(
                      fontSize: 11,
                      color: AppTokens.mutedOf(context),
                    ),
                  ),
                  const Spacer(),
                  Icon(
                    _expanded
                        ? Icons.keyboard_arrow_up_rounded
                        : Icons.keyboard_arrow_down_rounded,
                    color: AppTokens.teal,
                    size: 18,
                  ),
                ],
              ),
            ),
          ),

          // Collapsible body
          if (_expanded)
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppTokens.spaceMd,
                0,
                AppTokens.spaceMd,
                AppTokens.spaceMd,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Divider(color: AppTokens.borderOf(context)),

                  // Provenance segments
                  if (widget.provenance.isNotEmpty) ...[
                    Text(
                      'Data Provenance',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        color: Theme.of(context).colorScheme.onSurface,
                      ),
                    ),
                    const SizedBox(height: AppTokens.spaceXs),
                    ...widget.provenance.map(_buildProvenanceItem),
                    const SizedBox(height: AppTokens.spaceSm),
                  ],

                  // Tool execution records
                  if (widget.toolCalls.isNotEmpty) ...[
                    Text(
                      'Tool Executions',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        color: Theme.of(context).colorScheme.onSurface,
                      ),
                    ),
                    const SizedBox(height: AppTokens.spaceXs),
                    ...widget.toolCalls.map(_buildToolCallItem),
                    const SizedBox(height: AppTokens.spaceSm),
                  ],

                  // Legend explaining categories
                  _buildLegend(),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildProvenanceItem(ProvenanceSegment seg) {
    final (chipColor, labelText) = switch (seg.label) {
      ProvenanceLabel.observed => (AppTokens.teal, 'Observed'),
      ProvenanceLabel.predicted => (AppTokens.amber, 'Predicted'),
      ProvenanceLabel.recommended => (_violet, 'Recommended'),
      ProvenanceLabel.unknown => (AppTokens.mutedOf(context), 'General'),
    };

    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
            decoration: BoxDecoration(
              color: chipColor.withAlpha(25),
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: chipColor.withAlpha(90)),
            ),
            child: Text(
              labelText,
              style: TextStyle(
                fontSize: 10,
                fontWeight: FontWeight.w700,
                color: chipColor,
              ),
            ),
          ),
          const SizedBox(width: AppTokens.spaceSm),
          Expanded(
            child: Text(
              seg.segment,
              style: TextStyle(
                fontSize: 12,
                color: Theme.of(context).colorScheme.onSurface,
                height: 1.3,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildToolCallItem(ToolCall call) {
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.all(AppTokens.spaceSm),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: AppTokens.borderOf(context)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.code_rounded, size: 14, color: AppTokens.teal),
              const SizedBox(width: 4),
              Text(
                call.tool,
                style: const TextStyle(
                  fontSize: 11,
                  fontFamily: 'monospace',
                  fontWeight: FontWeight.w600,
                  color: AppTokens.teal,
                ),
              ),
            ],
          ),
          if (call.resultSummary.isNotEmpty) ...[
            const SizedBox(height: 3),
            Text(
              call.resultSummary,
              style: TextStyle(fontSize: 11, color: AppTokens.mutedOf(context)),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildLegend() {
    return Container(
      padding: const EdgeInsets.all(AppTokens.spaceSm),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: AppTokens.borderOf(context)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Provenance Legend',
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w700,
              color: AppTokens.mutedOf(context),
              letterSpacing: 0.3,
            ),
          ),
          const SizedBox(height: 4),
          _buildLegendRow(
            color: AppTokens.teal,
            label: 'Observed',
            desc: 'Real DB & telemetry observations',
          ),
          _buildLegendRow(
            color: AppTokens.amber,
            label: 'Predicted',
            desc: 'ML forecast and congestion projections',
          ),
          _buildLegendRow(
            color: _violet,
            label: 'Recommended',
            desc: 'AI suggestion, not an autonomous command',
          ),
        ],
      ),
    );
  }

  Widget _buildLegendRow({
    required Color color,
    required String label,
    required String desc,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 6),
          Text(
            '$label: ',
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w700,
              color: color,
            ),
          ),
          Expanded(
            child: Text(
              desc,
              style: TextStyle(fontSize: 10, color: AppTokens.mutedOf(context)),
            ),
          ),
        ],
      ),
    );
  }
}
