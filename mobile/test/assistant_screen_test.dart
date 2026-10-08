import 'dart:async';

import 'package:ai_trafficos/models/user.dart';
import 'package:ai_trafficos/providers/assistant_providers.dart';
import 'package:ai_trafficos/screens/assistant_screen.dart';
import 'package:ai_trafficos/services/api_client.dart';
import 'package:ai_trafficos/services/assistant_service.dart';
import 'package:ai_trafficos/services/auth_service.dart';
import 'package:ai_trafficos/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class FakeAssistantService extends AssistantService {
  FakeAssistantService({
    this.cannedResponse,
    this.exceptionToThrow,
    this.onChatCompleter,
  }) : super(apiClient: ApiClient(baseUrl: 'https://test/api/v1'));

  AssistantResponse? cannedResponse;
  AssistantException? exceptionToThrow;
  Completer<void>? onChatCompleter;
  String? lastMessageSent;
  int chatCallCount = 0;

  @override
  Future<AssistantResponse> chat({
    required String message,
    List<AssistantMessage>? history,
    String? conversationId,
  }) async {
    chatCallCount++;
    lastMessageSent = message;

    if (onChatCompleter != null) {
      await onChatCompleter!.future;
    }

    if (exceptionToThrow != null) {
      throw exceptionToThrow!;
    }

    return cannedResponse ??
        const AssistantResponse(
          answer: 'Default answer for testing',
          conversationId: 'test-conv-1',
        );
  }
}

Widget buildTestScreen({
  required AssistantService fakeService,
  User? user,
  Size viewportSize = const Size(360, 720),
}) {
  return ProviderScope(
    overrides: [
      assistantServiceProvider.overrideWithValue(fakeService),
      currentUserProvider.overrideWithValue(
        user ??
            const User(
              id: 1,
              email: 'operator@city.gov',
              fullName: 'Alex Operator',
              role: 'traffic_officer',
            ),
      ),
    ],
    child: MaterialApp(
      theme: AppTheme.darkTheme,
      home: MediaQuery(
        data: MediaQueryData(size: viewportSize),
        child: const AssistantScreen(),
      ),
    ),
  );
}

void main() {
  group('AssistantScreen Widget Tests', () {
    testWidgets('renders empty state with welcome banner and 3 example prompt buttons', (tester) async {
      final fake = FakeAssistantService();

      await tester.pumpWidget(buildTestScreen(fakeService: fake));
      await tester.pumpAndSettle();

      // Verify header and branding
      expect(find.text('AI Assistant'), findsOneWidget);
      expect(find.text('TrafficOS AI Assistant'), findsOneWidget);

      // Verify 3 example prompts
      expect(
        find.text('Analyze current congestion on Main Street corridor'),
        findsOneWidget,
      );
      expect(
        find.text('What signals require timing optimization?'),
        findsOneWidget,
      );
      expect(
        find.text('Summarize active incidents and emergency routes'),
        findsOneWidget,
      );

      // Tap an example prompt to verify it immediately sends
      fake.cannedResponse = const AssistantResponse(
        answer: 'Main Street throughput is normal at 42 km/h.',
        conversationId: 'conv-main-1',
      );

      await tester.tap(
        find.text('Analyze current congestion on Main Street corridor'),
      );
      await tester.pumpAndSettle();

      expect(fake.chatCallCount, 1);
      expect(fake.lastMessageSent, 'Analyze current congestion on Main Street corridor');
      expect(find.text('Main Street throughput is normal at 42 km/h.'), findsOneWidget);
    });

    testWidgets('renders loading Thinking bubble while inference is in flight', (tester) async {
      final completer = Completer<void>();
      final fake = FakeAssistantService(onChatCompleter: completer);

      await tester.pumpWidget(buildTestScreen(fakeService: fake));
      await tester.pumpAndSettle();

      // Enter a prompt in composer
      final textField = find.byType(TextField);
      await tester.enterText(textField, 'Check junction #4');
      await tester.pump();

      // Tap send button
      final sendButton = find.byIcon(Icons.send_rounded);
      await tester.tap(sendButton);
      await tester.pump(); // Start request

      // Verify user message and thinking indicator
      expect(find.text('Check junction #4'), findsOneWidget);
      expect(find.text('Thinking…'), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsOneWidget);

      // Complete request
      fake.cannedResponse = const AssistantResponse(
        answer: 'Junction #4 is operating on green cycle.',
        conversationId: 'c1',
      );
      completer.complete();
      await tester.pumpAndSettle();

      // Thinking indicator should disappear, answer should be present
      expect(find.text('Thinking…'), findsNothing);
      expect(find.text('Junction #4 is operating on green cycle.'), findsOneWidget);
    });

    testWidgets('renders AI-generated badge and insufficient-data banner', (tester) async {
      final fake = FakeAssistantService(
        cannedResponse: const AssistantResponse(
          answer: 'Sensor coverage is restricted on route 7.',
          conversationId: 'c2',
          insufficientData: true,
        ),
      );

      await tester.pumpWidget(buildTestScreen(fakeService: fake));
      await tester.pumpAndSettle();

      // Send message
      await tester.enterText(find.byType(TextField), 'Check route 7');
      await tester.tap(find.byIcon(Icons.send_rounded));
      await tester.pumpAndSettle();

      // AI-generated chip
      expect(find.text('AI-generated'), findsOneWidget);

      // Limited data banner
      expect(find.textContaining('Limited data: Inferences may be incomplete'), findsOneWidget);
      expect(find.byIcon(Icons.warning_amber_rounded), findsOneWidget);
    });

    testWidgets('renders System data card with Observed, Predicted, and Recommended chips and legend', (tester) async {
      final fake = FakeAssistantService(
        cannedResponse: const AssistantResponse(
          answer: 'Analysis with system data backing.',
          conversationId: 'c3',
          toolCalls: [
            ToolCall(
              tool: 'query_sensors',
              arguments: {'limit': 5},
              resultSummary: 'Returned 5 radar units',
            ),
          ],
          provenance: [
            ProvenanceSegment(
              segment: 'Radar volume count: 820 veh/hr',
              label: ProvenanceLabel.observed,
            ),
            ProvenanceSegment(
              segment: 'Model forecasts 940 veh/hr by 18:00',
              label: ProvenanceLabel.predicted,
            ),
            ProvenanceSegment(
              segment: 'Shift phase split +10%',
              label: ProvenanceLabel.recommended,
            ),
          ],
        ),
      );

      await tester.pumpWidget(buildTestScreen(fakeService: fake));
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextField), 'Detail check');
      await tester.tap(find.byIcon(Icons.send_rounded));
      await tester.pumpAndSettle();

      // System data header exists
      expect(find.text('System data'), findsOneWidget);
      expect(find.text('(3 items)'), findsOneWidget);

      // Tap to expand System data card
      await tester.tap(find.text('System data'));
      await tester.pumpAndSettle();

      // Check provenance labels
      expect(find.text('Observed'), findsWidgets);
      expect(find.text('Predicted'), findsWidgets);
      expect(find.text('Recommended'), findsWidgets);

      // Check provenance segments
      expect(find.text('Radar volume count: 820 veh/hr'), findsOneWidget);
      expect(find.text('Model forecasts 940 veh/hr by 18:00'), findsOneWidget);
      expect(find.text('Shift phase split +10%'), findsOneWidget);

      // Check tool execution
      expect(find.text('query_sensors'), findsOneWidget);
      expect(find.text('Returned 5 radar units'), findsOneWidget);

      // Check legend
      expect(find.text('Provenance Legend'), findsOneWidget);
      expect(find.text('Real DB & telemetry observations'), findsOneWidget);
      expect(find.text('ML forecast and congestion projections'), findsOneWidget);
      expect(find.text('AI suggestion, not an autonomous command'), findsOneWidget);
    });

    testWidgets('renders suggested followup chips and triggers message on tap', (tester) async {
      final fake = FakeAssistantService(
        cannedResponse: const AssistantResponse(
          answer: 'Initial response with suggestions.',
          conversationId: 'c4',
          suggestedFollowups: [
            'What is the detour?',
            'Check alternative route',
          ],
        ),
      );

      await tester.pumpWidget(buildTestScreen(fakeService: fake));
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextField), 'Give suggestions');
      await tester.tap(find.byIcon(Icons.send_rounded));
      await tester.pumpAndSettle();

      // Followup chips render
      expect(find.text('What is the detour?'), findsOneWidget);
      expect(find.text('Check alternative route'), findsOneWidget);

      // Tapping a followup sends it
      fake.cannedResponse = const AssistantResponse(
        answer: 'Detour is via 2nd Avenue.',
        conversationId: 'c4',
      );

      await tester.tap(find.text('What is the detour?'));
      await tester.pumpAndSettle();

      expect(fake.lastMessageSent, 'What is the detour?');
      expect(find.text('Detour is via 2nd Avenue.'), findsOneWidget);
    });

    testWidgets('renders 401 session expired error with Re-sign In button', (tester) async {
      final fake = FakeAssistantService(
        exceptionToThrow: const AssistantUnauthorizedException(),
      );

      await tester.pumpWidget(buildTestScreen(fakeService: fake));
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextField), 'Test 401');
      await tester.tap(find.byIcon(Icons.send_rounded));
      await tester.pumpAndSettle();

      expect(find.text('Session Expired'), findsOneWidget);
      expect(find.text('Re-sign In'), findsOneWidget);
    });

    testWidgets('renders 403 permission restricted panel naming the role', (tester) async {
      final fake = FakeAssistantService(
        exceptionToThrow: const AssistantForbiddenException(
          role: 'analyst',
        ),
      );

      await tester.pumpWidget(buildTestScreen(fakeService: fake));
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextField), 'Test 403');
      await tester.tap(find.byIcon(Icons.send_rounded));
      await tester.pumpAndSettle();

      expect(find.text('Permission Restricted'), findsOneWidget);
      expect(find.textContaining('analyst'), findsOneWidget);
    });

    testWidgets('renders retryable error with Retry button and succeeds on retry', (tester) async {
      final fake = FakeAssistantService(
        exceptionToThrow: const AssistantServerException(
          message: 'Backend AI engine temporarily unavailable',
        ),
      );

      await tester.pumpWidget(buildTestScreen(fakeService: fake));
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextField), 'Failing query');
      await tester.tap(find.byIcon(Icons.send_rounded));
      await tester.pumpAndSettle();

      expect(find.text('Backend AI engine temporarily unavailable'), findsOneWidget);
      expect(find.text('Retry'), findsOneWidget);

      // Change fake service to succeed and tap Retry
      fake.exceptionToThrow = null;
      fake.cannedResponse = const AssistantResponse(
        answer: 'Recovered successfully on retry.',
        conversationId: 'c5',
      );

      await tester.tap(find.text('Retry'));
      await tester.pumpAndSettle();

      expect(find.text('Recovered successfully on retry.'), findsOneWidget);
    });

    testWidgets('renders smoothly on 360px mobile width without overflow', (tester) async {
      final fake = FakeAssistantService(
        cannedResponse: const AssistantResponse(
          answer: 'Long responsive verification answer with **bold highlights** and `inline_code`.',
          conversationId: 'c6',
          insufficientData: true,
          toolCalls: [
            ToolCall(
              tool: 'query_emergency_corridor_telemetry',
              arguments: {'corridor_id': 1},
              resultSummary: 'Success',
            ),
          ],
          provenance: [
            ProvenanceSegment(
              segment: 'Long segment text testing 360px viewport wrap stability without RenderFlex overflow',
              label: ProvenanceLabel.recommended,
            ),
          ],
          suggestedFollowups: [
            'Followup A that could be long',
            'Followup B',
          ],
        ),
      );

      await tester.pumpWidget(buildTestScreen(
        fakeService: fake,
        viewportSize: const Size(360, 640),
      ));
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextField), '360px test');
      await tester.tap(find.byIcon(Icons.send_rounded));
      await tester.pumpAndSettle();

      // Expand system data card on 360px
      await tester.tap(find.text('System data'));
      await tester.pumpAndSettle();

      // Assert zero exceptions / zero layout overflow
      expect(tester.takeException(), isNull);
    });
  });
}
