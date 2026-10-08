import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/traffic_summary.dart';
import '../models/vehicle_event.dart';
import '../providers/realtime_providers.dart';
import '../services/api_client.dart';
import '../services/realtime_protocol.dart';
import '../services/traffic_service.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_card.dart';
import '../widgets/empty_state.dart';
import '../widgets/error_state.dart';
import '../widgets/loading_state.dart';
import '../widgets/volume_trend_chart.dart';

/// Live Traffic Telemetry screen featuring volume charts, corridor metrics,
/// and an infinite-scrolling vehicle perception event feed.
class TrafficScreen extends ConsumerStatefulWidget {
  const TrafficScreen({super.key});

  @override
  ConsumerState<TrafficScreen> createState() => _TrafficScreenState();
}

class _TrafficScreenState extends ConsumerState<TrafficScreen> {
  String _selectedBucket = 'hour';
  bool _isLoadingSummary = true;
  String? _summaryError;
  List<TrafficSummaryBucket> _summaryBuckets = [];

  // Vehicle events pagination
  final ScrollController _scrollController = ScrollController();
  final List<VehicleEvent> _vehicleEvents = [];
  bool _isLoadingEvents = true;
  bool _isLoadingMoreEvents = false;
  String? _eventsError;
  int _eventPage = 1;
  int _eventTotalPages = 1;

  Timer? _wsDebounceTimer;
  bool _isSyncing = false;

  @override
  void initState() {
    super.initState();
    _loadSummary();
    _loadInitialEvents();
    _scrollController.addListener(_onScroll);
  }

  @override
  void dispose() {
    _wsDebounceTimer?.cancel();
    _scrollController.removeListener(_onScroll);
    _scrollController.dispose();
    super.dispose();
  }

  void _scheduleDebouncedRefresh() {
    _wsDebounceTimer?.cancel();
    _wsDebounceTimer = Timer(const Duration(milliseconds: 1500), () async {
      if (mounted && !_isSyncing) {
        _isSyncing = true;
        try {
          await Future.wait([
            _loadSummary(isBackgroundRefresh: true),
            _loadInitialEvents(isBackgroundRefresh: true),
          ]);
        } finally {
          _isSyncing = false;
        }
      }
    });
  }

  void _onScroll() {
    if (_scrollController.position.pixels >=
            _scrollController.position.maxScrollExtent - 200 &&
        !_isLoadingMoreEvents &&
        _eventPage < _eventTotalPages) {
      _loadMoreEvents();
    }
  }

  Future<void> _loadSummary({bool isBackgroundRefresh = false}) async {
    if (!isBackgroundRefresh) {
      setState(() {
        _isLoadingSummary = true;
        _summaryError = null;
      });
    }

    try {
      final service = ref.read(trafficServiceProvider);
      final buckets = await service.getTrafficSummary(bucket: _selectedBucket);
      if (mounted) {
        setState(() {
          _summaryBuckets = buckets;
          _isLoadingSummary = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoadingSummary = false;
          _summaryError = e is ApiException ? e.message : 'Telemetry load failed: $e';
        });
      }
    }
  }

  Future<void> _loadInitialEvents({bool isBackgroundRefresh = false}) async {
    if (!isBackgroundRefresh) {
      setState(() {
        _eventPage = 1;
        _isLoadingEvents = true;
        _eventsError = null;
      });
    }

    try {
      final service = ref.read(trafficServiceProvider);
      final paged = await service.getVehicleEvents(page: 1, perPage: 20);
      if (mounted) {
        setState(() {
          _eventPage = 1;
          _vehicleEvents.clear();
          _vehicleEvents.addAll(paged.items);
          _eventTotalPages = paged.pages;
          _isLoadingEvents = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoadingEvents = false;
          _eventsError = e is ApiException ? e.message : 'Events feed failed: $e';
        });
      }
    }
  }

  Future<void> _loadMoreEvents() async {
    if (_isLoadingMoreEvents) return;
    setState(() {
      _isLoadingMoreEvents = true;
    });

    try {
      final service = ref.read(trafficServiceProvider);
      final nextPage = _eventPage + 1;
      final paged = await service.getVehicleEvents(page: nextPage, perPage: 20);
      if (mounted) {
        setState(() {
          _eventPage = nextPage;
          _vehicleEvents.addAll(paged.items);
          _eventTotalPages = paged.pages;
          _isLoadingMoreEvents = false;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _isLoadingMoreEvents = false;
        });
      }
    }
  }

  Future<void> _refreshAll() async {
    await Future.wait([
      _loadSummary(),
      _loadInitialEvents(),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    // Real-time WebSocket invalidation: debounced on burst events
    for (final topic in const [
      RealtimeTopics.trafficUpdate,
      RealtimeTopics.congestionChange,
    ]) {
      ref.listen(realtimeTopicEventProvider(topic), (_, next) {
        if (next.hasValue) {
          _scheduleDebouncedRefresh();
        }
      });
    }

    final theme = Theme.of(context);

    return RefreshIndicator(
      onRefresh: _refreshAll,
      color: AppTokens.teal,
      backgroundColor: theme.cardTheme.color ?? AppTokens.cardOf(context),
      child: CustomScrollView(
        controller: _scrollController,
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.all(AppTokens.spaceMd),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _buildHeaderAndBucketSelector(theme),
                  const SizedBox(height: AppTokens.spaceMd),
                  _buildChartCard(theme),
                  const SizedBox(height: AppTokens.spaceMd),
                  _buildStatsGrid(theme),
                  const SizedBox(height: AppTokens.spaceLg),
                  Row(
                    children: [
                      const Icon(Icons.stream_rounded, color: AppTokens.teal, size: 20),
                      const SizedBox(width: AppTokens.spaceSm),
                      Text(
                        'Live Vehicle Detections',
                        style: theme.textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.w700,
                          color: theme.colorScheme.onSurface,
                        ),
                      ),
                      const Spacer(),
                      AppBadge(
                        label: '${_vehicleEvents.length} Captured',
                        color: AppTokens.teal,
                      ),
                    ],
                  ),
                  const SizedBox(height: AppTokens.spaceSm),
                ],
              ),
            ),
          ),
          _buildEventsFeedSliver(theme),
        ],
      ),
    );
  }

  Widget _buildHeaderAndBucketSelector(ThemeData theme) {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Traffic Flow & Volume',
                  style: theme.textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: theme.colorScheme.onSurface,
                  ),
                ),
                Text(
                  'Telemetry aggregation window',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: AppTokens.mutedOf(context),
                  ),
                ),
              ],
            ),
          ),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(
                value: 'hour',
                label: Text('Hour'),
                icon: Icon(Icons.schedule_rounded, size: 14),
              ),
              ButtonSegment(
                value: 'day',
                label: Text('Day'),
                icon: Icon(Icons.calendar_today_rounded, size: 14),
              ),
            ],
            selected: {_selectedBucket},
            onSelectionChanged: (val) {
              if (val.isNotEmpty && val.first != _selectedBucket) {
                setState(() {
                  _selectedBucket = val.first;
                });
                _loadSummary();
              }
            },
            style: SegmentedButton.styleFrom(
              selectedBackgroundColor: AppTokens.teal.withAlpha(40),
              selectedForegroundColor: AppTokens.teal,
              foregroundColor: AppTokens.mutedOf(context),
              backgroundColor: Theme.of(context).colorScheme.surface,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildChartCard(ThemeData theme) {
    if (_isLoadingSummary) {
      return const AppCard(
        padding: EdgeInsets.all(AppTokens.spaceXl),
        child: Center(
          child: LoadingState(
            compact: true,
            message: 'Plotting volume aggregation trend...',
          ),
        ),
      );
    }

    if (_summaryError != null) {
      return AppCard(
        padding: const EdgeInsets.all(AppTokens.spaceMd),
        child: ErrorState(
          title: 'Volume Telemetry Error',
          message: _summaryError!,
          onRetry: _loadSummary,
        ),
      );
    }

    if (_summaryBuckets.isEmpty) {
      return AppCard(
        padding: const EdgeInsets.all(AppTokens.spaceXl),
        child: Center(
          child: Text(
            'No telemetry buckets recorded for the selected window',
            style: TextStyle(color: AppTokens.mutedOf(context)),
          ),
        ),
      );
    }

    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                'Volume Trend & Congestion Level',
                style: theme.textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                  color: theme.colorScheme.onSurface,
                ),
              ),
              const Spacer(),
              Row(
                children: [
                  Container(width: 8, height: 8, color: AppTokens.teal),
                  const SizedBox(width: 4),
                  Text('Volume', style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 11)),
                  const SizedBox(width: 10),
                  Container(width: 8, height: 8, color: AppTokens.amber),
                  const SizedBox(width: 4),
                  Text('Congestion %', style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 11)),
                ],
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceMd),
          VolumeTrendChart(
            buckets: _summaryBuckets,
            isHourly: _selectedBucket == 'hour',
            height: 180,
          ),
        ],
      ),
    );
  }

  Widget _buildStatsGrid(ThemeData theme) {
    double avgVehicles = 0.0;
    double avgSpeed = 0.0;
    double maxCongestion = 0.0;
    int totalObservations = 0;

    if (_summaryBuckets.isNotEmpty) {
      double totalV = 0.0;
      double totalS = 0.0;
      int speedSamples = 0;
      for (final b in _summaryBuckets) {
        totalV += b.avgVehicleCount;
        if (b.avgSpeed != null) {
          totalS += b.avgSpeed!;
          speedSamples++;
        }
        if (b.avgCongestion > maxCongestion) {
          maxCongestion = b.avgCongestion;
        }
        totalObservations += b.recordCount;
      }
      avgVehicles = totalV / _summaryBuckets.length;
      avgSpeed = speedSamples > 0 ? (totalS / speedSamples) : 0.0;
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final cardWidth = (constraints.maxWidth - AppTokens.spaceSm) / 2;

        return Wrap(
          spacing: AppTokens.spaceSm,
          runSpacing: AppTokens.spaceSm,
          children: [
            SizedBox(
              width: cardWidth,
              child: _buildMetricTile(
                title: 'Flow Density',
                value: '${avgVehicles.toStringAsFixed(0)} veh/bkt',
                icon: Icons.directions_car_rounded,
                color: AppTokens.teal,
              ),
            ),
            SizedBox(
              width: cardWidth,
              child: _buildMetricTile(
                title: 'Corridor Speed',
                value: avgSpeed > 0 ? '${avgSpeed.toStringAsFixed(1)} km/h' : '--',
                icon: Icons.speed_rounded,
                color: AppTokens.teal,
              ),
            ),
            SizedBox(
              width: cardWidth,
              child: _buildMetricTile(
                title: 'Peak Congestion',
                value: '${maxCongestion.toStringAsFixed(0)}%',
                icon: Icons.warning_rounded,
                color: maxCongestion > 70 ? AppTokens.danger : AppTokens.amber,
              ),
            ),
            SizedBox(
              width: cardWidth,
              child: _buildMetricTile(
                title: 'Sensor Ingested',
                value: '$totalObservations obs',
                icon: Icons.sensors_rounded,
                color: AppTokens.teal,
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _buildMetricTile({
    required String title,
    required String value,
    required IconData icon,
    required Color color,
  }) {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: color, size: 16),
              const SizedBox(width: 6),
              Text(
                title,
                style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 11),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            value,
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w800,
              color: Theme.of(context).colorScheme.onSurface,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildEventsFeedSliver(ThemeData theme) {
    if (_isLoadingEvents) {
      return const SliverToBoxAdapter(
        child: Padding(
          padding: EdgeInsets.all(AppTokens.spaceXl),
          child: LoadingState(
            message: 'Streaming vehicle detections...',
            subtitle: 'Ingesting computer vision telemetry events',
          ),
        ),
      );
    }

    if (_eventsError != null && _vehicleEvents.isEmpty) {
      return SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.all(AppTokens.spaceMd),
          child: ErrorState(
            title: 'Detections Unavailable',
            message: _eventsError!,
            onRetry: _loadInitialEvents,
          ),
        ),
      );
    }

    if (_vehicleEvents.isEmpty) {
      return const SliverToBoxAdapter(
        child: Padding(
          padding: EdgeInsets.all(AppTokens.spaceMd),
          child: EmptyState(
            icon: Icons.directions_car_filled_outlined,
            title: 'No Vehicle Events Detected',
            message: 'Camera inference pipelines are active. Detections will populate automatically.',
          ),
        ),
      );
    }

    return SliverPadding(
      padding: const EdgeInsets.symmetric(horizontal: AppTokens.spaceMd),
      sliver: SliverList(
        delegate: SliverChildBuilderDelegate(
          (context, index) {
            if (index == _vehicleEvents.length) {
              if (_isLoadingMoreEvents) {
                return const Padding(
                  padding: EdgeInsets.symmetric(vertical: AppTokens.spaceMd),
                  child: Center(
                    child: SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        valueColor: AlwaysStoppedAnimation(AppTokens.teal),
                      ),
                    ),
                  ),
                );
              }
              return const SizedBox.shrink();
            }

            final event = _vehicleEvents[index];
            return Padding(
              padding: const EdgeInsets.only(bottom: AppTokens.spaceSm),
              child: _buildEventItem(event),
            );
          },
          childCount: _vehicleEvents.length + (_isLoadingMoreEvents ? 1 : 0),
        ),
      ),
    );
  }

  Widget _buildEventItem(VehicleEvent event) {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      child: Row(
        children: [
          Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              color: AppTokens.teal.withAlpha(25),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: AppTokens.teal.withAlpha(70)),
            ),
            child: Icon(event.icon, color: AppTokens.teal, size: 20),
          ),
          const SizedBox(width: AppTokens.spaceMd),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      event.vehicleType.toUpperCase(),
                      style: TextStyle(
                        fontWeight: FontWeight.w700,
                        color: Theme.of(context).colorScheme.onSurface,
                        fontSize: 13,
                      ),
                    ),
                    if (event.direction != null) ...[
                      const SizedBox(width: 6),
                      Text(
                        '• ${event.direction!}',
                        style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 12),
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  'Node #${event.intersectionId ?? "--"} • Lane #${event.laneId ?? "--"}',
                  style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 11),
                ),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                event.speedKmh != null
                    ? '${event.speedKmh!.toStringAsFixed(1)} km/h'
                    : '--',
                style: const TextStyle(
                  fontWeight: FontWeight.w700,
                  color: AppTokens.teal,
                  fontSize: 13,
                ),
              ),
              if (event.confidence != null)
                Text(
                  '${(event.confidence! * 100).toStringAsFixed(0)}% conf',
                  style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 10),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

