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
    with SingleTickerProviderStateMixin, WidgetsBindingObserver {
  late AnimationController _pulseController;
  late Animation<double> _pulseAnimation;
  Timer? _staleCheckTimer;
  bool _isAppActive = true;
  bool _lastKnownIsStale = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    );

    _pulseAnimation = Tween<double>(begin: 0.35, end: 1.0).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final isActive = state == AppLifecycleState.resumed;
    if (_isAppActive != isActive) {
      _isAppActive = isActive;
      if (!isActive) {
        if (_pulseController.isAnimating) {
          _pulseController.stop();
        }
        _staleCheckTimer?.cancel();
        _staleCheckTimer = null;
      } else {
        if (mounted) setState(() {});
      }
    }
  }

  void _updateStaleTimer(bool isConnected) {
    if (isConnected && _isAppActive) {
      if (_staleCheckTimer == null || !_staleCheckTimer!.isActive) {
        _staleCheckTimer = Timer.periodic(const Duration(seconds: 10), (_) {
          if (!mounted) return;
          final currentIsStale = ref.read(realtimeServiceProvider).isStale;
          if (currentIsStale != _lastKnownIsStale) {
            _lastKnownIsStale = currentIsStale;
            setState(() {});
          }
        });
      }
    } else {
      _staleCheckTimer?.cancel();
      _staleCheckTimer = null;
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
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

    // Power optimization: only pulse when live, app is active, and only timer when connected
    if (showPulse && _isAppActive) {
      if (!_pulseController.isAnimating) {
        _pulseController.repeat(reverse: true);
      }
    } else {
      if (_pulseController.isAnimating) {
        _pulseController.stop();
      }
    }
    _updateStaleTimer(status == RealtimeConnectionStatus.connected);

    final isTappable = status != RealtimeConnectionStatus.connected;
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

    final semanticsLabel = 'Connection status: $label.${isTappable ? " Tap to reconnect." : ""}';

    return Semantics(
      label: semanticsLabel,
      button: isTappable,
      enabled: isTappable,
      child: Tooltip(
        message: tooltipMessage,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 44, minWidth: 44),
          child: InkWell(
            borderRadius: BorderRadius.circular(AppTokens.pillRadiusValue),
            onTap: isTappable
                ? () {
                    realtimeService.reconnect();
                  }
                : null,
            child: Center(
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 300),
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
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
                        style: TextStyle(
                          color: AppTokens.mutedOf(context),
                          fontSize: 9,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
