import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/junction.dart';
import '../services/api_client.dart';
import '../services/junction_service.dart';
import '../services/map_provider.dart';
import '../theme/app_tokens.dart';
import '../widgets/app_card.dart';
import '../widgets/empty_state.dart';
import '../widgets/error_state.dart';
import '../widgets/junction_map.dart';
import '../widgets/loading_state.dart';

/// Spatial Network Map screen presenting real-time physical junction nodes,
/// status color coding, and filter selectors.
class MapScreen extends ConsumerStatefulWidget {
  const MapScreen({super.key});

  @override
  ConsumerState<MapScreen> createState() => _MapScreenState();
}

class _MapScreenState extends ConsumerState<MapScreen> {
  MapFilter _activeFilter = MapFilter.all;
  bool _isLoading = true;
  String? _errorMessage;
  List<Junction> _junctions = [];

  // Default spatial provider
  final MapProvider _mapProvider = const SchematicJunctionMapProvider();

  @override
  void initState() {
    super.initState();
    _loadJunctions();
  }

  Future<void> _loadJunctions() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final service = ref.read(junctionServiceProvider);
      final paged = await service.getJunctions(page: 1, perPage: 100);
      if (mounted) {
        setState(() {
          _junctions = paged.items;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoading = false;
          _errorMessage = e is ApiException ? e.message : 'Failed to load spatial network: $e';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppTokens.spaceMd),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _buildTopBar(theme),
              const SizedBox(height: AppTokens.spaceSm),
              _buildFilterChips(),
              const SizedBox(height: AppTokens.spaceSm),
              Expanded(
                child: _buildMapArea(context),
              ),
              const SizedBox(height: AppTokens.spaceSm),
              _buildLegendBar(theme),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildTopBar(ThemeData theme) {
    return AppCard(
      padding: const EdgeInsets.symmetric(
        horizontal: AppTokens.spaceMd,
        vertical: AppTokens.spaceSm,
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(6),
            decoration: BoxDecoration(
              color: AppTokens.teal.withAlpha(25),
              borderRadius: BorderRadius.circular(8),
            ),
            child: const Icon(Icons.hub_rounded, color: AppTokens.teal, size: 20),
          ),
          const SizedBox(width: AppTokens.spaceSm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  'Spatial Network Topology',
                  style: theme.textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: AppTokens.textPrimary,
                  ),
                ),
                Text(
                  'Provider: ${_mapProvider.name} (WGS 84 Projection)',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: AppTokens.muted,
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ),
          IconButton(
            tooltip: 'Reload Nodes',
            icon: const Icon(Icons.refresh_rounded, color: AppTokens.teal, size: 20),
            onPressed: _loadJunctions,
          ),
        ],
      ),
    );
  }

  Widget _buildFilterChips() {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          _buildFilterChip(MapFilter.all, 'All Nodes (${_junctions.length})'),
          const SizedBox(width: AppTokens.spaceSm),
          _buildFilterChip(MapFilter.congested, 'Congested / Warning'),
          const SizedBox(width: AppTokens.spaceSm),
          _buildFilterChip(MapFilter.incidents, 'Incidents / Offline'),
        ],
      ),
    );
  }

  Widget _buildFilterChip(MapFilter filter, String label) {
    final isSelected = _activeFilter == filter;
    return ChoiceChip(
      label: Text(label),
      selected: isSelected,
      onSelected: (val) {
        if (val) {
          setState(() {
            _activeFilter = filter;
          });
        }
      },
      selectedColor: AppTokens.teal.withAlpha(35),
      backgroundColor: AppTokens.surface,
      labelStyle: TextStyle(
        color: isSelected ? AppTokens.teal : AppTokens.muted,
        fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
        fontSize: 12,
      ),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: BorderSide(
          color: isSelected ? AppTokens.teal.withAlpha(90) : AppTokens.borderDark,
        ),
      ),
    );
  }

  Widget _buildMapArea(BuildContext context) {
    if (_isLoading) {
      return const Center(
        child: LoadingState(
          message: 'Projecting spatial junction coordinates...',
          subtitle: 'Retrieving physical node grid from municipal registry',
        ),
      );
    }

    if (_errorMessage != null) {
      return Center(
        child: ErrorState(
          title: 'Spatial Grid Offline',
          message: _errorMessage!,
          onRetry: _loadJunctions,
        ),
      );
    }

    if (_junctions.isEmpty) {
      return const Center(
        child: EmptyState(
          icon: Icons.map_rounded,
          title: 'No Junctions Found',
          message: 'No physical municipal intersections registered in the database.',
        ),
      );
    }

    return _mapProvider.buildJunctionMap(
      context: context,
      junctions: _junctions,
      filter: _activeFilter,
    );
  }

  Widget _buildLegendBar(ThemeData theme) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: AppTokens.surface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTokens.borderDark),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceAround,
        children: [
          _buildLegendItem(AppTokens.teal, 'Active / Fluid'),
          _buildLegendItem(AppTokens.amber, 'Maintenance / Congested'),
          _buildLegendItem(AppTokens.danger, 'Offline / Incident'),
        ],
      ),
    );
  }

  Widget _buildLegendItem(Color color, String label) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(
            color: color,
            shape: BoxShape.circle,
            boxShadow: [
              BoxShadow(
                color: color.withAlpha(80),
                blurRadius: 4,
                spreadRadius: 1,
              ),
            ],
          ),
        ),
        const SizedBox(width: 6),
        Text(
          label,
          style: const TextStyle(
            color: AppTokens.muted,
            fontSize: 11,
            fontWeight: FontWeight.w500,
          ),
        ),
      ],
    );
  }
}
