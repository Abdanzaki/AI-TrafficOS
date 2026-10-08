import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../services/auth_service.dart';
import '../services/realtime_protocol.dart';
import '../services/realtime_service.dart';

/// Provider for the singleton [RealtimeService] instance.
final Provider<RealtimeService> realtimeServiceProvider =
    Provider<RealtimeService>((ref) {
  final service = RealtimeService(
    onAuthFailure: () {
      ref.read(authStateProvider.notifier).logout();
    },
  );

  ref.onDispose(service.dispose);
  return service;
});

/// Stream provider for reactive [RealtimeConnectionStatus] changes.
final StreamProvider<RealtimeConnectionStatus> realtimeStatusProvider =
    StreamProvider<RealtimeConnectionStatus>((ref) {
  final service = ref.watch(realtimeServiceProvider);
  return service.statusStream;
});

/// Stream provider of all incoming [RealtimeEvent] envelopes.
final StreamProvider<RealtimeEvent> realtimeEventsProvider =
    StreamProvider<RealtimeEvent>((ref) {
  final service = ref.watch(realtimeServiceProvider);
  return service.events;
});

/// Family provider exposing real-time events for a specific [topic].
final StreamProviderFamily<RealtimeEvent, String> realtimeTopicEventProvider =
    StreamProvider.family<RealtimeEvent, String>((ref, topic) {
  final service = ref.watch(realtimeServiceProvider);
  return service.streamFor(topic);
});

/// Exposes the latest received [RealtimeEvent] for a topic or null if none received yet.
final ProviderFamily<RealtimeEvent?, String> latestTopicEventProvider =
    Provider.family<RealtimeEvent?, String>((ref, topic) {
  final eventAsync = ref.watch(realtimeTopicEventProvider(topic));
  return eventAsync.asData?.value;
});

/// Lifecycle watcher that connects to the real-time stream when the user is authenticated,
/// subscribes to authorized topics according to their role, and disconnects on sign-out.
final Provider<void> realtimeLifecycleProvider = Provider<void>((ref) {
  final authState = ref.watch(authStateProvider);
  final realtimeService = ref.watch(realtimeServiceProvider);

  if (authState is AuthAuthenticated) {
    final user = authState.user;
    final topics = topicsForRole(user.role);

    Future.microtask(() async {
      final token = await realtimeService.getStoredToken();
      if (token != null && token.isNotEmpty) {
        await realtimeService.connect(
          jwt: token,
          topics: topics,
        );
      }
    });
  } else if (authState is AuthUnauthenticated) {
    realtimeService.disconnect();
  }
});

/// Reactive provider indicating whether the backend WebSocket connection is offline.
final Provider<bool> isOfflineProvider = Provider<bool>((ref) {
  final statusAsync = ref.watch(realtimeStatusProvider);
  final service = ref.watch(realtimeServiceProvider);
  final currentStatus = statusAsync.valueOrNull ?? service.status;
  return currentStatus == RealtimeConnectionStatus.disconnected ||
      currentStatus == RealtimeConnectionStatus.error;
});

