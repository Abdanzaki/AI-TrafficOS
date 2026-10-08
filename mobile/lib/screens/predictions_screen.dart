import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/junction.dart';
import '../models/prediction.dart';
import '../providers/realtime_providers.dart';
import '../services/junction_service.dart';
import '../services/prediction_service.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_card.dart';
import '../widgets/empty_state.dart';
import '../widgets/error_state.dart';
import '../widgets/loading_state.dart';
import '../widgets/offline_banner.dart';

/// Screen providing 30-minute machine learning traffic predictions,
/// confidence score visualization, and historical inference telemetry.
class PredictionsScreen extends ConsumerStatefulWidget {
  const PredictionsScreen({super.key, this.initialIntersectionId});

  final int? initialIntersectionId;

  @override
  ConsumerState<PredictionsScreen> createState() => _PredictionsScreenState();
}

class _PredictionsScreenState extends ConsumerState<PredictionsScreen> {
  int? _selectedIntersectionId;
  List<Junction> _junctions = [];
  bool _isLoadingJunctions = true;

  bool _isLoadingPrediction = false;
  String? _predictionError;
  InsufficientDataException? _insufficientDataException;
  PredictionResult? _predictionResult;

  bool _isLoadingRecent = false;
  PaginatedAIPredictions? _recentPredictions;

  @override
  void initState() {
    super.initState();
    _selectedIntersectionId = widget.initialIntersectionId;
    _initJunctions();
  }

  Future<void> _initJunctions() async {
    setState(() => _isLoadingJunctions = true);
    try {
      final junctionService = ref.read(junctionServiceProvider);
      final res = await junctionService.getJunctions(perPage: 50);
      if (mounted) {
        setState(() {
          _junctions = res.items;
          _isLoadingJunctions = false;
          if (_selectedIntersectionId == null && _junctions.isNotEmpty) {
            _selectedIntersectionId = _junctions.first.id;
          }
        });
        if (_selectedIntersectionId != null) {
          _loadData(_selectedIntersectionId!);
        }
      }
    } catch (_) {
      if (mounted) {
        setState(() => _isLoadingJunctions = false);
      }
    }
  }

  Future<void> _loadData(int intersectionId) async {
    await Future.wait([
      _loadPrediction(intersectionId),
      _loadRecentPredictions(intersectionId),
    ]);
  }

  Future<void> _loadPrediction(int intersectionId) async {
    setState(() {
      _isLoadingPrediction = true;
      _predictionError = null;
      _insufficientDataException = null;
      _predictionResult = null;
    });

    try {
      final predictionService = ref.read(predictionServiceProvider);
      final pred = await predictionService.getPrediction(intersectionId);
      if (mounted) {
        setState(() {
          _predictionResult = pred;
          _isLoadingPrediction = false;
        });
      }
    } on InsufficientDataException catch (e) {
      if (mounted) {
        setState(() {
          _insufficientDataException = e;
          _isLoadingPrediction = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _predictionError = e.toString();
          _isLoadingPrediction = false;
        });
      }
    }
  }

  Future<void> _loadRecentPredictions(int intersectionId) async {
    setState(() => _isLoadingRecent = true);
    try {
      final predictionService = ref.read(predictionServiceProvider);
      final recent = await predictionService.getAiPredictions(
        intersectionId: intersectionId,
        perPage: 10,
      );
      if (mounted) {
        setState(() {
          _recentPredictions = recent;
          _isLoadingRecent = false;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() => _isLoadingRecent = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('AI Predictions'),
        actions: [
          if (_selectedIntersectionId != null)
            IconButton(
              icon: const Icon(Icons.refresh_rounded),
              tooltip: 'Refresh Forecast',
              onPressed: () => _loadData(_selectedIntersectionId!),
            ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            if (ref.watch(isOfflineProvider)) const OfflineBanner(),
            _buildJunctionSelectorBar(),
            Expanded(
              child: RefreshIndicator(
                color: AppTokens.teal,
                backgroundColor: theme.colorScheme.surface,
                onRefresh: () async {
                  if (_selectedIntersectionId != null) {
                    await _loadData(_selectedIntersectionId!);
                  }
                },
                child: _buildScrollableBody(theme),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildJunctionSelectorBar() {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppTokens.spaceMd,
        vertical: AppTokens.spaceSm,
      ),
      decoration: BoxDecoration(
        color: AppTokens.surfaceOf(context),
        border: Border(
          bottom: BorderSide(color: AppTokens.borderOf(context)),
        ),
      ),
      child: Row(
        children: [
          const Icon(
            Icons.location_on_rounded,
            color: AppTokens.teal,
            size: 20,
          ),
          const SizedBox(width: AppTokens.spaceSm),
          Expanded(
            child: DropdownButtonHideUnderline(
              child: DropdownButton<int>(
                value: _selectedIntersectionId,
                isExpanded: true,
                dropdownColor: Theme.of(context).colorScheme.surface,
                hint: Text(
                  'Select Junction...',
                  style: TextStyle(
                      color: Theme.of(context).colorScheme.onSurface,
                      fontSize: 13),
                ),
                icon: Icon(
                  Icons.arrow_drop_down_rounded,
                  color: AppTokens.mutedOf(context),
                ),
                items: _junctions.map((j) {
                  return DropdownMenuItem<int>(
                    value: j.id,
                    child: Text(
                      'Junction #${j.id} — ${j.name}',
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.onSurface,
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                      ),
                      overflow: TextOverflow.ellipsis,
                      maxLines: 1,
                    ),
                  );
                }).toList(),
                onChanged: (val) {
                  if (val != null && val != _selectedIntersectionId) {
                    setState(() => _selectedIntersectionId = val);
                    _loadData(val);
                  }
                },
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildScrollableBody(ThemeData theme) {
    if (_isLoadingJunctions) {
      return const LoadingState(message: 'Loading junction registry...');
    }

    if (_junctions.isEmpty) {
      return const EmptyState(
        icon: Icons.alt_route_rounded,
        title: 'No Junctions Available',
        message: 'No physical intersections registered in database.',
      );
    }

    return ListView(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      children: [
        _buildForecastSection(theme),
        const SizedBox(height: AppTokens.spaceLg),
        _buildRecentPredictionsSection(theme),
        const SizedBox(height: AppTokens.spaceXl),
      ],
    );
  }

  Widget _buildForecastSection(ThemeData theme) {
    if (_isLoadingPrediction) {
      return const LoadingState(
        message: 'Generating 30-minute forward traffic forecast...',
      );
    }

    if (_insufficientDataException != null) {
      final exc = _insufficientDataException!;
      return EmptyState(
        icon: Icons.data_array_rounded,
        title: 'Insufficient Telemetry Data',
        message: exc.userFriendlyMessage,
      );
    }

    if (_predictionError != null) {
      return ErrorState(
        message: _predictionError!,
        title: 'Prediction Unavailable',
        onRetry: () {
          if (_selectedIntersectionId != null) {
            _loadPrediction(_selectedIntersectionId!);
          }
        },
      );
    }

    final pred = _predictionResult;
    if (pred == null) {
      return const EmptyState(
        icon: Icons.timeline_rounded,
        title: 'No Forecast Available',
        message: 'Select an intersection to generate predictive insights.',
      );
    }

    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  const Icon(Icons.timeline_rounded, color: AppTokens.teal, size: 22),
                  const SizedBox(width: AppTokens.spaceSm),
                  Text(
                    '30-Min Forward Forecast',
                    style: theme.textTheme.titleSmall?.copyWith(
                      color: theme.colorScheme.onSurface,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
              const AppBadge(
                label: '+30 MIN HORIZON',
                color: AppTokens.teal,
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceSm),
          if (pred.modelVersion != null)
            Text(
              'Model: ${pred.modelVersion}',
              style: TextStyle(color: AppTokens.mutedOf(context), fontSize: 11),
            ),
          const SizedBox(height: AppTokens.spaceMd),
          _buildPredictionMetricCard(
            label: 'Forecast Vehicular Volume',
            value: pred.volume != null
                ? '${pred.volume!.toStringAsFixed(1)} veh/min'
                : 'N/A',
            confidence: pred.volumeConfidence ?? pred.overallConfidence,
            accentColor: AppTokens.teal,
            icon: Icons.directions_car_rounded,
          ),
          const SizedBox(height: AppTokens.spaceMd),
          _buildPredictionMetricCard(
            label: 'Forecast Congestion Index',
            value: pred.congestion != null
                ? '${pred.congestion!.toStringAsFixed(1)}%'
                : 'N/A',
            confidence: pred.congestionConfidence ?? pred.overallConfidence,
            accentColor: (pred.congestion ?? 0) > 65
                ? AppTokens.danger
                : ((pred.congestion ?? 0) > 40
                    ? AppTokens.amber
                    : AppTokens.success),
            icon: Icons.speed_rounded,
          ),
          const SizedBox(height: AppTokens.spaceMd),
          _buildPredictionMetricCard(
            label: 'Forecast Stop-Bar Queue Growth',
            value: pred.queue != null
                ? '${pred.queue! >= 0 ? "+" : ""}${pred.queue!.toStringAsFixed(1)} veh'
                : 'N/A',
            confidence: pred.queueConfidence ?? pred.overallConfidence,
            accentColor: AppTokens.amber,
            icon: Icons.traffic_rounded,
          ),
        ],
      ),
    );
  }

  Widget _buildPredictionMetricCard({
    required String label,
    required String value,
    required double? confidence,
    required Color accentColor,
    required IconData icon,
  }) {
    final confPercent = confidence != null ? (confidence * 100).toInt() : null;

    return Semantics(
      label:
          '$label: $value${confPercent != null ? ", $confPercent% confidence" : ""}',
      button: false,
      child: Container(
        padding: const EdgeInsets.all(AppTokens.spaceMd),
        decoration: BoxDecoration(
          color: AppTokens.surfaceOf(context),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppTokens.borderOf(context)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, color: accentColor, size: 18),
                const SizedBox(width: AppTokens.spaceSm),
                Expanded(
                  child: Text(
                    label,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.onSurface,
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                Text(
                  value,
                  style: TextStyle(
                    color: accentColor,
                    fontWeight: FontWeight.w800,
                    fontSize: 15,
                  ),
                ),
              ],
            ),
            if (confidence != null) ...[
              const SizedBox(height: AppTokens.spaceSm),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    'Inference Confidence',
                    style: TextStyle(
                        color: AppTokens.mutedOf(context), fontSize: 11),
                  ),
                  Text(
                    '$confPercent%',
                    style: TextStyle(
                      color: accentColor,
                      fontWeight: FontWeight.w700,
                      fontSize: 11,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              ClipRRect(
                borderRadius: BorderRadius.circular(3),
                child: LinearProgressIndicator(
                  value: confidence,
                  backgroundColor: AppTokens.cardOf(context),
                  valueColor: AlwaysStoppedAnimation(accentColor),
                  minHeight: 5,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildRecentPredictionsSection(ThemeData theme) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              'Historical AI Predictions',
              style: theme.textTheme.titleSmall?.copyWith(
                color: theme.colorScheme.onSurface,
                fontWeight: FontWeight.w700,
              ),
            ),
            if (_isLoadingRecent)
              const SizedBox(
                width: 14,
                height: 14,
                child: CircularProgressIndicator(strokeWidth: 2, color: AppTokens.teal),
              ),
          ],
        ),
        const SizedBox(height: AppTokens.spaceSm),
        if (_recentPredictions == null || _recentPredictions!.items.isEmpty) ...[
          const AppCard(
            padding: EdgeInsets.all(AppTokens.spaceMd),
            child: EmptyState(
              icon: Icons.history_rounded,
              title: 'No Historical Records',
              message: 'No inference outputs recorded yet for this junction.',
            ),
          ),
        ] else ...[
          ..._recentPredictions!.items.map((pred) {
            final confPercent =
                pred.confidence != null ? (pred.confidence! * 100).toInt() : null;

            return Padding(
              padding: const EdgeInsets.only(bottom: AppTokens.spaceSm),
              child: AppCard(
                padding: const EdgeInsets.symmetric(
                  horizontal: AppTokens.spaceMd,
                  vertical: AppTokens.spaceSm,
                ),
                child: Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.all(8),
                      decoration: BoxDecoration(
                        color: AppTokens.teal.withAlpha(25),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: const Icon(
                        Icons.psychology_rounded,
                        color: AppTokens.teal,
                        size: 20,
                      ),
                    ),
                    const SizedBox(width: AppTokens.spaceMd),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Text(
                                pred.predictionType.toUpperCase(),
                                style: TextStyle(
                                  color: theme.colorScheme.onSurface,
                                  fontWeight: FontWeight.w700,
                                  fontSize: 12,
                                ),
                              ),
                              if (confPercent != null) ...[
                                const SizedBox(width: AppTokens.spaceSm),
                                AppBadge(
                                  label: '$confPercent% CONF',
                                  color: AppTokens.teal,
                                ),
                              ],
                            ],
                          ),
                          const SizedBox(height: 2),
                          Text(
                            'Target: ${pred.predictedFor.toLocal().toString().substring(0, 16)}',
                            style: TextStyle(
                              color: AppTokens.mutedOf(context),
                              fontSize: 11,
                            ),
                          ),
                        ],
                      ),
                    ),
                    Text(
                      pred.modelVersion,
                      style: TextStyle(
                          color: AppTokens.mutedOf(context), fontSize: 11),
                    ),
                  ],
                ),
              ),
            );
          }),
        ],
      ],
    );
  }
}
