import 'dart:async';

import 'package:ai_trafficos/providers/realtime_providers.dart';
import 'package:ai_trafficos/services/realtime_service.dart';
import 'package:ai_trafficos/widgets/connection_status_chip.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class StubRealtimeService extends RealtimeService {
  StubRealtimeService({
    RealtimeConnectionStatus initialStatus = RealtimeConnectionStatus.disconnected,
    bool isStaleValue = false,
    DateTime? lastEventAtValue,
  })  : _stubStatus = initialStatus,
        _stubIsStale = isStaleValue,
        _stubLastEventAt = lastEventAtValue,
        super(enableJitter: false);

  final RealtimeConnectionStatus _stubStatus;
  final bool _stubIsStale;
  final DateTime? _stubLastEventAt;

  @override
  RealtimeConnectionStatus get status => _stubStatus;

  @override
  bool get isStale => _stubIsStale;

  @override
  DateTime? get lastEventAt => _stubLastEventAt;

  @override
  Stream<RealtimeConnectionStatus> get statusStream =>
      Stream.value(_stubStatus);
}

void main() {
  Widget buildTestWidget(RealtimeService service) {
    return ProviderScope(
      overrides: [
        realtimeServiceProvider.overrideWithValue(service),
      ],
      child: const MaterialApp(
        home: Scaffold(
          appBar: PreferredSize(
            preferredSize: Size.fromHeight(56),
            child: ConnectionStatusChip(),
          ),
        ),
      ),
    );
  }

  testWidgets('renders OFFLINE when disconnected', (tester) async {
    final stub = StubRealtimeService(
      initialStatus: RealtimeConnectionStatus.disconnected,
    );

    await tester.pumpWidget(buildTestWidget(stub));
    await tester.pump();

    expect(find.text('OFFLINE'), findsOneWidget);
  });

  testWidgets('renders CONNECTING when status is connecting', (tester) async {
    final stub = StubRealtimeService(
      initialStatus: RealtimeConnectionStatus.connecting,
    );

    await tester.pumpWidget(buildTestWidget(stub));
    await tester.pump();

    expect(find.text('CONNECTING'), findsOneWidget);
  });

  testWidgets('renders LIVE when connected and fresh', (tester) async {
    final stub = StubRealtimeService(
      initialStatus: RealtimeConnectionStatus.connected,
      isStaleValue: false,
      lastEventAtValue: DateTime(2026, 10, 8, 14, 25, 30),
    );

    await tester.pumpWidget(buildTestWidget(stub));
    await tester.pump();

    expect(find.text('LIVE'), findsOneWidget);
    expect(find.text('14:25:30'), findsOneWidget);
  });

  testWidgets('renders STALE when connected but past heartbeat threshold', (tester) async {
    final stub = StubRealtimeService(
      initialStatus: RealtimeConnectionStatus.connected,
      isStaleValue: true,
      lastEventAtValue: DateTime(2026, 10, 8, 14, 25, 30),
    );

    await tester.pumpWidget(buildTestWidget(stub));
    await tester.pump();

    expect(find.text('STALE'), findsOneWidget);
  });
}
