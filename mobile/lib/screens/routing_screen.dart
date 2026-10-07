import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/junction.dart';
import '../models/route_result.dart';
import '../services/api_client.dart';
import '../services/junction_service.dart';
import '../services/routing_service.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_card.dart';
import '../widgets/empty_state.dart';
import '../widgets/error_state.dart';
import '../widgets/junction_map.dart';
import '../widgets/loading_state.dart';

/// Dynamic municipal routing screen calculating least-cost paths across the junction network.
class RoutingScreen extends ConsumerStatefulWidget {
  const RoutingScreen({
    super.key,
    this.initialFromId,
    this.initialToId,
  });

  final int? initialFromId;
  final int? initialToId;

  @override
  ConsumerState<RoutingScreen> createState() => _RoutingScreenState();
}

class _RoutingScreenState extends ConsumerState<RoutingScreen> {
  List<Junction> _junctions = [];
  bool _isLoadingJunctions = true;

  int? _fromId;
  int? _toId;
  String _algorithm = 'astar';

  bool _isCalculating = false;
  RouteResult? _routeResult;
  String? _routeError;

  @override
  void initState() {
    super.initState();
    _fromId = widget.initialFromId;
    _toId = widget.initialToId;
    _loadJunctions();
  }

  Future<void> _loadJunctions() async {
    setState(() {
      _isLoadingJunctions = true;
    });

    try {
      final service = ref.read(junctionServiceProvider);
      final paged = await service.getJunctions(perPage: 50);
      if (mounted) {
        setState(() {
          _junctions = paged.items;
          _isLoadingJunctions = false;
          if (_junctions.isNotEmpty) {
            _fromId ??= _junctions.first.id;
            if (_junctions.length > 1) {
              _toId ??= _junctions[1].id;
            } else {
              _toId ??= _junctions.first.id;
            }
          }
        });

        if (_fromId != null && _toId != null && _fromId != _toId) {
          _calculateRoute();
        }
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _isLoadingJunctions = false;
        });
      }
    }
  }

  Future<void> _calculateRoute() async {
    if (_fromId == null || _toId == null) return;

    if (_fromId == _toId) {
      setState(() {
        _routeError = 'Origin and destination must be distinct intersections.';
        _routeResult = null;
      });
      return;
    }

    setState(() {
      _isCalculating = true;
      _routeError = null;
    });

    try {
      final service = ref.read(routingServiceProvider);
      final result = await service.getOptimalRoute(
        fromIntersectionId: _fromId!,
        toIntersectionId: _toId!,
        algorithm: _algorithm,
      );

      if (mounted) {
        setState(() {
          _routeResult = result;
          _isCalculating = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isCalculating = false;
          _routeError = e is ApiException
              ? e.message
              : 'Failed to compute route path: $e';
        });
      }
    }
  }

  void _swapEndpoints() {
    setState(() {
      final tmp = _fromId;
      _fromId = _toId;
      _toId = tmp;
    });
    if (_fromId != null && _toId != null && _fromId != _toId) {
      _calculateRoute();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Municipal Optimal Routing'),
        actions: [
          IconButton(
            tooltip: 'Reload Network Nodes',
            icon: const Icon(Icons.refresh_rounded),
            onPressed: _loadJunctions,
          ),
        ],
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(AppTokens.spaceMd),
          children: [
            _buildSelectorCard(),
            const SizedBox(height: AppTokens.spaceMd),
            _buildResultContent(),
          ],
        ),
      ),
    );
  }

  Widget _buildSelectorCard() {
    if (_isLoadingJunctions) {
      return const AppCard(
        padding: EdgeInsets.all(AppTokens.spaceLg),
        child: Center(
          child: LoadingState(
            compact: true,
            message: 'Loading intersection network topology...',
          ),
        ),
      );
    }

    if (_junctions.isEmpty) {
      return const AppCard(
        padding: EdgeInsets.all(AppTokens.spaceLg),
        child: EmptyState(
          icon: Icons.alt_route_rounded,
          title: 'No Junctions Available',
          message: 'Unable to query network topology intersections for route calculation.',
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
              const Icon(Icons.navigation_rounded, color: AppTokens.teal, size: 20),
              const SizedBox(width: AppTokens.spaceSm),
              const Expanded(
                child: Text(
                  'Route Query Configuration',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: AppTokens.textPrimary,
                  ),
                ),
              ),
              IconButton(
                tooltip: 'Swap Origin & Destination',
                icon: const Icon(Icons.swap_vert_rounded, color: AppTokens.teal),
                onPressed: _swapEndpoints,
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceMd),
          // Origin
          const Text(
            'Origin Intersection',
            style: TextStyle(fontSize: 12, color: AppTokens.muted, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 4),
          DropdownButtonFormField<int>(
            initialValue: _fromId,
            dropdownColor: AppTokens.card,
            decoration: const InputDecoration(
              filled: true,
              fillColor: AppTokens.surface,
              contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            ),
            items: _junctions.map((j) {
              return DropdownMenuItem<int>(
                value: j.id,
                child: Text('${j.name} (${j.code})'),
              );
            }).toList(),
            onChanged: (val) {
              setState(() => _fromId = val);
            },
          ),
          const SizedBox(height: AppTokens.spaceSm),
          // Destination
          const Text(
            'Destination Intersection',
            style: TextStyle(fontSize: 12, color: AppTokens.muted, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 4),
          DropdownButtonFormField<int>(
            initialValue: _toId,
            dropdownColor: AppTokens.card,
            decoration: const InputDecoration(
              filled: true,
              fillColor: AppTokens.surface,
              contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            ),
            items: _junctions.map((j) {
              return DropdownMenuItem<int>(
                value: j.id,
                child: Text('${j.name} (${j.code})'),
              );
            }).toList(),
            onChanged: (val) {
              setState(() => _toId = val);
            },
          ),
          const SizedBox(height: AppTokens.spaceMd),
          Row(
            children: [
              const Text(
                'Algorithm:',
                style: TextStyle(fontSize: 12, color: AppTokens.muted, fontWeight: FontWeight.w600),
              ),
              const SizedBox(width: AppTokens.spaceSm),
              SegmentedButton<String>(
                segments: const [
                  ButtonSegment(value: 'astar', label: Text('A* Search')),
                  ButtonSegment(value: 'dijkstra', label: Text('Dijkstra')),
                ],
                selected: {_algorithm},
                onSelectionChanged: (val) {
                  if (val.isNotEmpty) {
                    setState(() => _algorithm = val.first);
                  }
                },
                style: SegmentedButton.styleFrom(
                  selectedBackgroundColor: AppTokens.teal.withAlpha(40),
                  selectedForegroundColor: AppTokens.teal,
                  foregroundColor: AppTokens.muted,
                  backgroundColor: AppTokens.surface,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceLg),
          SizedBox(
            width: double.infinity,
            height: 46,
            child: ElevatedButton.icon(
              icon: const Icon(Icons.directions_rounded, size: 18),
              label: const Text(
                'Find Optimal Route',
                style: TextStyle(fontWeight: FontWeight.w700),
              ),
              style: ElevatedButton.styleFrom(
                backgroundColor: AppTokens.teal,
                foregroundColor: AppTokens.ink,
              ),
              onPressed: _isCalculating ? null : _calculateRoute,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildResultContent() {
    if (_isCalculating) {
      return const AppCard(
        padding: EdgeInsets.all(AppTokens.spaceXl),
        child: Center(
          child: LoadingState(
            message: 'Calculating minimum impedance path...',
            subtitle: 'Evaluating road hierarchy, congestion delays & topology',
          ),
        ),
      );
    }

    if (_routeError != null) {
      return AppCard(
        padding: const EdgeInsets.all(AppTokens.spaceMd),
        child: ErrorState(
          title: 'Pathfinding Infeasible',
          message: _routeError!,
          onRetry: _calculateRoute,
        ),
      );
    }

    if (_routeResult == null) {
      return const AppCard(
        padding: EdgeInsets.all(AppTokens.spaceXl),
        child: EmptyState(
          icon: Icons.map_rounded,
          title: 'Ready to Plan Route',
          message: 'Select origin and destination intersections above to calculate optimal transit paths.',
        ),
      );
    }

    final route = _routeResult!;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildMetricsGrid(route),
        const SizedBox(height: AppTokens.spaceMd),
        _buildMapCard(route),
        const SizedBox(height: AppTokens.spaceMd),
        _buildWaypointsCard(route),
      ],
    );
  }

  Widget _buildMetricsGrid(RouteResult route) {
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
                title: 'Total Distance',
                value: route.formattedDistance,
                icon: Icons.straighten_rounded,
                color: AppTokens.teal,
              ),
            ),
            SizedBox(
              width: cardWidth,
              child: _buildMetricTile(
                title: 'Estimated Duration',
                value: route.formattedDuration,
                icon: Icons.timer_outlined,
                color: AppTokens.amber,
              ),
            ),
            SizedBox(
              width: cardWidth,
              child: _buildMetricTile(
                title: 'Waypoints',
                value: '${route.waypointCount} Junctions',
                icon: Icons.location_on_outlined,
                color: AppTokens.teal,
              ),
            ),
            SizedBox(
              width: cardWidth,
              child: _buildMetricTile(
                title: 'Path Algorithm',
                value: route.algorithm.toUpperCase(),
                icon: Icons.account_tree_outlined,
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
                style: const TextStyle(color: AppTokens.muted, fontSize: 11),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            value,
            style: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w800,
              color: AppTokens.textPrimary,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMapCard(RouteResult route) {
    final hasCoords = _junctions.any((j) => j.latitude != null && j.longitude != null);

    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.map_rounded, color: AppTokens.teal, size: 18),
              const SizedBox(width: AppTokens.spaceSm),
              const Text(
                'Corridor Path Visualization',
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                  color: AppTokens.textPrimary,
                ),
              ),
              const Spacer(),
              AppBadge(
                label: 'AMBER PATH OVERLAY',
                color: AppTokens.amber,
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceSm),
          if (hasCoords)
            SizedBox(
              height: 240,
              width: double.infinity,
              child: JunctionMapWidget(
                junctions: _junctions,
                highlightedPath: route.path,
              ),
            )
          else
            const Padding(
              padding: EdgeInsets.all(AppTokens.spaceMd),
              child: Text(
                'Spatial map coordinates not registered for current network nodes.',
                style: TextStyle(color: AppTokens.muted, fontSize: 12),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildWaypointsCard(RouteResult route) {
    final junctionMap = {for (final j in _junctions) j.id: j};

    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Traversed Waypoints & Network Edges',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: AppTokens.textPrimary,
            ),
          ),
          const SizedBox(height: AppTokens.spaceMd),
          Wrap(
            spacing: AppTokens.spaceSm,
            runSpacing: AppTokens.spaceSm,
            children: [
              for (int i = 0; i < route.path.length; i++) ...[
                Builder(
                  builder: (_) {
                    final jId = route.path[i];
                    final junction = junctionMap[jId];
                    final name = junction?.name ?? 'Junction #$jId';
                    final isStart = i == 0;
                    final isEnd = i == route.path.length - 1;

                    Color chipColor = AppTokens.surface;
                    Color textColor = AppTokens.textPrimary;
                    if (isStart) {
                      chipColor = AppTokens.teal.withAlpha(30);
                      textColor = AppTokens.teal;
                    } else if (isEnd) {
                      chipColor = AppTokens.amber.withAlpha(30);
                      textColor = AppTokens.amber;
                    }

                    return Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        color: chipColor,
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(
                          color: isStart
                              ? AppTokens.teal.withAlpha(90)
                              : isEnd
                                  ? AppTokens.amber.withAlpha(90)
                                  : AppTokens.borderDark,
                        ),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            '${i + 1}.',
                            style: TextStyle(
                              color: textColor,
                              fontWeight: FontWeight.w800,
                              fontSize: 11,
                            ),
                          ),
                          const SizedBox(width: 4),
                          Text(
                            name,
                            style: TextStyle(
                              color: textColor,
                              fontWeight: FontWeight.w600,
                              fontSize: 12,
                            ),
                          ),
                        ],
                      ),
                    );
                  },
                ),
              ],
            ],
          ),
          if (route.edges.isNotEmpty) ...[
            const SizedBox(height: AppTokens.spaceMd),
            const Divider(color: AppTokens.borderDark),
            const SizedBox(height: AppTokens.spaceSm),
            const Text(
              'Segment Impendence Details:',
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: AppTokens.muted,
              ),
            ),
            const SizedBox(height: 6),
            for (final edge in route.edges) ...[
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(
                  children: [
                    const Icon(Icons.arrow_right_rounded, size: 16, color: AppTokens.teal),
                    Text(
                      'Road #${edge.roadId}: ${edge.fromIntersectionId} -> ${edge.toIntersectionId}',
                      style: const TextStyle(fontSize: 12, color: AppTokens.textPrimary),
                    ),
                    const Spacer(),
                    Text(
                      '${edge.lengthKm.toStringAsFixed(2)} km • ${edge.costMinutes.toStringAsFixed(1)} min',
                      style: const TextStyle(fontSize: 11, color: AppTokens.muted),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ],
      ),
    );
  }
}
