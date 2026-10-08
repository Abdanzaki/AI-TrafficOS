import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/realtime_providers.dart';
import '../services/realtime_service.dart';
import '../theme/app_tokens.dart';

/// Interactive status pill displaying real-time WebSocket connection telemetry:
/// - LIVE (pulsing green dot, last-event timestamp)
/// - CONNECTING (amber dot)
/// - OFFLINE (red dot)
/// - STALE (amber outline, last-event timestamp)
class ConnectionStatusChip extends ConsumerStatefulWidget {
  const ConnectionStatusChip({
    super.key,
    this.compact = false,
  });

  final bool compact;

  @override
  ConsumerState<ConnectionStatusChip> createState() =>
      _ConnectionStatusChipState();
}

class _ConnectionStatusChipState extends ConsumerState<ConnectionStatusChip>
    with SingleTickerProviderStateMixin {
  late AnimationController _pulseController;
  late Animation<double> _pulseAnimation;
  Timer? _staleCheckTimer;

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat(reverse: true);

    _pulseAnimation = Tween<double>(begin: 0.35, end: 1.0).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );

    // Periodically tick to re-evaluate staleness and last-event elapsed time
    _staleCheckTimer = Timer.periodic(const Duration(seconds: 5), (_) {
      if (mounted) {
        setState(() {});
      }
    });
  }

  @override
  void dispose() {
    _pulseController.dispose();
    _staleCheckTimer?.cancel();
    super.dispose();
  }

  String _formatTime(DateTime dt) {
    final h = dt.hour.toString().padLeft(2, '0');
    final m = dt.minute.toString().padLeft(2, '0');
    final s = dt.second.toString().padLeft(2, '0');
    return '$h:$m:$s';
  }

  @override
  Widget build(BuildContext context) {
    final realtimeService = ref.watch(realtimeServiceProvider);
    // Listen to status and event streams to trigger immediate rebuilds
    final statusAsync = ref.watch(realtimeStatusProvider);
    ref.watch(realtimeEventsProvider);

    final status = statusAsync.valueOrNull ?? realtimeService.status;
    final isStale = realtimeService.isStale;
    final lastEventAt = realtimeService.lastEventAt;

    final Color badgeColor;
    final String label;
    final bool showPulse;
    final bool isStaleOutline;

    switch (status) {
      case RealtimeConnectionStatus.connected:
        if (isStale) {
          badgeColor = AppTokens.amber;
          label = 'STALE';
          showPulse = false;
          isStaleOutline = true;
        } else {
          badgeColor = AppTokens.success;
          label = 'LIVE';
          showPulse = true;
          isStaleOutline = false;
        }
        break;

      case RealtimeConnectionStatus.connecting:
        badgeColor = AppTokens.amber;
        label = 'CONNECTING';
        showPulse = false;
        isStaleOutline = false;
        break;

      case RealtimeConnectionStatus.disconnected:
      case RealtimeConnectionStatus.error:
        badgeColor = AppTokens.danger;
        label = 'OFFLINE';
        showPulse = false;
        isStaleOutline = false;
        break;
    }

    final tooltipMessage = switch (status) {
      RealtimeConnectionStatus.connected => isStale
          ? 'Connected but no events received within threshold. Last event: ${lastEventAt != null ? _formatTime(lastEventAt) : "none"}'
          : 'Live real-time WebSocket connection active',
      RealtimeConnectionStatus.connecting =>
        'Establishing WebSocket stream connection...',
      RealtimeConnectionStatus.disconnected =>
        'Disconnected from WebSocket server. Tap to reconnect.',
      RealtimeConnectionStatus.error =>
        'Real-time connection error. Tap to retry.',
    };

    return Tooltip(
      message: tooltipMessage,
      child: InkWell(
        borderRadius: BorderRadius.circular(AppTokens.pillRadiusValue),
        onTap: () {
          if (status != RealtimeConnectionStatus.connected) {
            realtimeService.reconnect();
          }
        },
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 300),
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          decoration: BoxDecoration(
            color: isStaleOutline
                ? AppTokens.amber.withAlpha(20)
                : badgeColor.withAlpha(25),
            borderRadius: BorderRadius.circular(AppTokens.pillRadiusValue),
            border: Border.all(
              color: isStaleOutline
                  ? AppTokens.amber
                  : badgeColor.withAlpha(90),
              width: isStaleOutline ? 1.5 : 1.0,
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              // Pulse or static dot
              if (showPulse)
                FadeTransition(
                  opacity: _pulseAnimation,
                  child: Container(
                    width: 7,
                    height: 7,
                    decoration: BoxDecoration(
                      color: badgeColor,
                      shape: BoxShape.circle,
                      boxShadow: [
                        BoxShadow(
                          color: badgeColor.withAlpha(150),
                          blurRadius: 4,
                          spreadRadius: 1,
                        ),
                      ],
                    ),
                  ),
                )
              else
                Container(
                  width: 7,
                  height: 7,
                  decoration: BoxDecoration(
                    color: badgeColor,
                    shape: BoxShape.circle,
                  ),
                ),
              const SizedBox(width: 5),
              Text(
                label,
                style: TextStyle(
                  color: badgeColor,
                  fontWeight: FontWeight.w700,
                  fontSize: 10,
                  letterSpacing: 0.4,
                ),
              ),
              if (!widget.compact && lastEventAt != null && status == RealtimeConnectionStatus.connected) ...[
                const SizedBox(width: 4),
                Text(
                  _formatTime(lastEventAt),
                  style: const TextStyle(
                    color: AppTokens.muted,
                    fontSize: 9,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
