import 'package:flutter/material.dart';

import '../models/junction.dart';
import '../models/road_segment.dart';
import '../screens/junction_detail_screen.dart';
import '../services/map_provider.dart';
import '../theme/app_tokens.dart';
import 'app_badge.dart';
import 'app_button.dart';
import 'empty_state.dart';

/// Coordinate boundaries for lat/lon viewport normalization.
class MapCoordinateBounds {
  const MapCoordinateBounds({
    required this.minLat,
    required this.maxLat,
    required this.minLon,
    required this.maxLon,
  });

  final double minLat;
  final double maxLat;
  final double minLon;
  final double maxLon;

  static MapCoordinateBounds? fromJunctions(List<Junction> junctions) {
    final valid = junctions
        .where((j) => j.latitude != null && j.longitude != null)
        .toList();
    if (valid.isEmpty) return null;

    double minLat = valid.first.latitude!;
    double maxLat = valid.first.latitude!;
    double minLon = valid.first.longitude!;
    double maxLon = valid.first.longitude!;

    for (final j in valid) {
      if (j.latitude! < minLat) minLat = j.latitude!;
      if (j.latitude! > maxLat) maxLat = j.latitude!;
      if (j.longitude! < minLon) minLon = j.longitude!;
      if (j.longitude! > maxLon) maxLon = j.longitude!;
    }

    if (minLat == maxLat) {
      minLat -= 0.005;
      maxLat += 0.005;
    }
    if (minLon == maxLon) {
      minLon -= 0.005;
      maxLon += 0.005;
    }

    return MapCoordinateBounds(
      minLat: minLat,
      maxLat: maxLat,
      minLon: minLon,
      maxLon: maxLon,
    );
  }

  Offset project(double lat, double lon, Size size, {double padding = 40.0}) {
    final availableWidth = size.width - (padding * 2);
    final availableHeight = size.height - (padding * 2);

    final normalizedX = (lon - minLon) / (maxLon - minLon);
    final normalizedY = (maxLat - lat) / (maxLat - minLat);

    final x = padding + (normalizedX.clamp(0.0, 1.0) * availableWidth);
    final y = padding + (normalizedY.clamp(0.0, 1.0) * availableHeight);

    return Offset(x, y);
  }
}

/// Default schematic map provider rendering normalized vector nodes.
class SchematicJunctionMapProvider extends MapProvider {
  const SchematicJunctionMapProvider();

  @override
  String get name => 'Schematic Spatial View';

  @override
  Widget buildJunctionMap({
    required BuildContext context,
    required List<Junction> junctions,
    List<RoadSegment>? roads,
    Map<int, double>? congestionLevels,
    Junction? selectedJunction,
    ValueChanged<Junction>? onJunctionTapped,
    MapFilter filter = MapFilter.all,
  }) {
    return JunctionMapWidget(
      junctions: junctions,
      roads: roads,
      congestionLevels: congestionLevels,
      selectedJunction: selectedJunction,
      onJunctionTapped: onJunctionTapped,
      filter: filter,
    );
  }
}

/// Interactive schematic vector map widget plotting real junction coordinates.
class JunctionMapWidget extends StatefulWidget {
  const JunctionMapWidget({
    super.key,
    required this.junctions,
    this.roads,
    this.congestionLevels,
    this.selectedJunction,
    this.onJunctionTapped,
    this.filter = MapFilter.all,
    this.highlightedPath,
  });

  final List<Junction> junctions;
  final List<RoadSegment>? roads;
  final Map<int, double>? congestionLevels;
  final Junction? selectedJunction;
  final ValueChanged<Junction>? onJunctionTapped;
  final MapFilter filter;
  final List<int>? highlightedPath;

  @override
  State<JunctionMapWidget> createState() => _JunctionMapWidgetState();
}

class _JunctionMapWidgetState extends State<JunctionMapWidget> {
  Junction? _selected;
  late final TransformationController _transformationController;

  @override
  void initState() {
    super.initState();
    _transformationController = TransformationController();
    _selected = widget.selectedJunction;
  }

  @override
  void dispose() {
    _transformationController.dispose();
    super.dispose();
  }

  void _zoomIn() {
    final matrix = _transformationController.value.clone();
    matrix.scaleByDouble(1.25, 1.25, 1.0, 1.0);
    _transformationController.value = matrix;
  }

  void _zoomOut() {
    final matrix = _transformationController.value.clone();
    matrix.scaleByDouble(0.8, 0.8, 1.0, 1.0);
    _transformationController.value = matrix;
  }

  void _resetZoom() {
    _transformationController.value = Matrix4.identity();
  }

  @override
  void didUpdateWidget(covariant JunctionMapWidget oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.selectedJunction != oldWidget.selectedJunction) {
      _selected = widget.selectedJunction;
    }
  }

  List<Junction> get _filteredJunctions {
    return widget.junctions.where((j) {
      if (j.latitude == null || j.longitude == null) return false;
      switch (widget.filter) {
        case MapFilter.congested:
          return j.status.toLowerCase() != 'active' ||
              j.signals.any((s) => s.status.toLowerCase() != 'active');
        case MapFilter.incidents:
          return j.status.toLowerCase() == 'maintenance' ||
              j.status.toLowerCase() == 'inactive';
        case MapFilter.all:
          return true;
      }
    }).toList();
  }

  void _handleTapUp(TapUpDetails details, Size size, MapCoordinateBounds bounds) {
    const hitRadius = 26.0;
    Junction? nearest;
    double nearestDist = double.infinity;

    // Convert local tap coordinate to scene coordinate
    final scenePoint = _transformationController.toScene(details.localPosition);

    for (final j in _filteredJunctions) {
      final pos = bounds.project(j.latitude!, j.longitude!, size);
      final dist = (scenePoint - pos).distance;
      if (dist <= hitRadius && dist < nearestDist) {
        nearest = j;
        nearestDist = dist;
      }
    }

    if (nearest != null) {
      setState(() {
        _selected = nearest;
      });
      widget.onJunctionTapped?.call(nearest);
      _showJunctionBottomSheet(context, nearest);
    }
  }

  void _showJunctionBottomSheet(BuildContext context, Junction junction) {
    final theme = Theme.of(context);
    final statusColor = _getJunctionColor(junction);

    showModalBottomSheet<void>(
      context: context,
      backgroundColor: theme.colorScheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
        side: BorderSide(color: AppTokens.borderOf(context)),
      ),
      builder: (ctx) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(AppTokens.spaceLg),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Center(
                  child: Container(
                    width: 36,
                    height: 4,
                    decoration: BoxDecoration(
                      color: AppTokens.mutedOf(context).withAlpha(80),
                      borderRadius: BorderRadius.circular(2),
                    ),
                  ),
                ),
                const SizedBox(height: AppTokens.spaceMd),
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(
                        color: statusColor.withAlpha(30),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: statusColor.withAlpha(90)),
                      ),
                      child: Icon(Icons.traffic_rounded, color: statusColor, size: 24),
                    ),
                    const SizedBox(width: AppTokens.spaceMd),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            junction.name,
                            style: theme.textTheme.titleMedium?.copyWith(
                              fontWeight: FontWeight.w700,
                              color: theme.colorScheme.onSurface,
                            ),
                          ),
                          Text(
                            'Code: ${junction.code} • ${junction.city ?? "Municipal"}',
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: AppTokens.mutedOf(context),
                            ),
                          ),
                        ],
                      ),
                    ),
                    AppBadge(
                      label: junction.status.toUpperCase(),
                      color: statusColor,
                    ),
                  ],
                ),
                const SizedBox(height: AppTokens.spaceLg),
                Row(
                  children: [
                    Expanded(
                      child: _buildMetaChip(
                        icon: Icons.traffic_outlined,
                        label: 'Signals',
                        value: '${junction.signals.length} Online',
                      ),
                    ),
                    const SizedBox(width: AppTokens.spaceSm),
                    Expanded(
                      child: _buildMetaChip(
                        icon: Icons.alt_route_outlined,
                        label: 'Lanes',
                        value: '${junction.lanes.length} Lanes',
                      ),
                    ),
                    const SizedBox(width: AppTokens.spaceSm),
                    Expanded(
                      child: _buildMetaChip(
                        icon: Icons.my_location_outlined,
                        label: 'GPS',
                        value: '${junction.latitude?.toStringAsFixed(3)}, ${junction.longitude?.toStringAsFixed(3)}',
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: AppTokens.spaceLg),
                AppButton(
                  text: 'View Junction Details',
                  icon: Icons.arrow_forward_rounded,
                  isFullWidth: true,
                  onPressed: () {
                    Navigator.of(ctx).pop();
                    Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => JunctionDetailScreen(
                          junctionId: junction.id,
                          initialJunction: junction,
                        ),
                      ),
                    );
                  },
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _buildMetaChip({
    required IconData icon,
    required String label,
    required String value,
  }) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTokens.borderOf(context)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 13, color: AppTokens.mutedOf(context)),
              const SizedBox(width: 4),
              Text(
                label,
                style: TextStyle(fontSize: 10, color: AppTokens.mutedOf(context)),
              ),
            ],
          ),
          const SizedBox(height: 2),
          Text(
            value,
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: Theme.of(context).colorScheme.onSurface,
            ),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    );
  }

  Color _getJunctionColor(Junction j) {
    if (j.status.toLowerCase() == 'maintenance') {
      return AppTokens.amber;
    }
    if (j.status.toLowerCase() == 'inactive') {
      return AppTokens.danger;
    }
    return AppTokens.teal;
  }

  @override
  Widget build(BuildContext context) {
    final validJunctions = _filteredJunctions;
    if (validJunctions.isEmpty) {
      return const EmptyState(
        icon: Icons.map_outlined,
        title: 'No Junction Coordinates',
        message: 'No physical junctions with valid latitude/longitude coordinates match the active spatial filter.',
      );
    }

    final bounds = MapCoordinateBounds.fromJunctions(validJunctions);
    if (bounds == null) {
      return const EmptyState(
        icon: Icons.map_outlined,
        title: 'No Coordinate Bounds',
        message: 'Unable to calculate spatial boundaries for current node set.',
      );
    }

    final theme = Theme.of(context);
    return LayoutBuilder(
      builder: (context, constraints) {
        final canvasSize = Size(constraints.maxWidth, constraints.maxHeight);

        return ClipRRect(
          borderRadius: BorderRadius.circular(16),
          child: Stack(
            children: [
              Container(
                color: theme.brightness == Brightness.dark
                    ? AppTokens.ink
                    : const Color(0xFF13192B),
                child: InteractiveViewer(
                  transformationController: _transformationController,
                  minScale: 0.5,
                  maxScale: 5.0,
                  boundaryMargin: const EdgeInsets.all(120),
                  child: GestureDetector(
                    onTapUp: (details) => _handleTapUp(details, canvasSize, bounds),
                    child: Semantics(
                      label:
                          'Schematic junction network map displaying ${validJunctions.length} junctions and road corridors',
                      button: false,
                      child: CustomPaint(
                        size: canvasSize,
                        painter: SchematicMapPainter(
                          junctions: validJunctions,
                          roads: widget.roads,
                          bounds: bounds,
                          selectedId: _selected?.id,
                          highlightedPath: widget.highlightedPath,
                        ),
                      ),
                    ),
                  ),
                ),
              ),
              Positioned(
                top: 12,
                right: 12,
                child: Container(
                  decoration: BoxDecoration(
                    color: (theme.brightness == Brightness.dark
                            ? AppTokens.cardOf(context)
                            : Colors.white)
                        .withAlpha(225),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                      color: theme.colorScheme.outline.withAlpha(70),
                    ),
                    boxShadow: const [
                      BoxShadow(
                        color: Colors.black26,
                        blurRadius: 6,
                        offset: Offset(0, 2),
                      ),
                    ],
                  ),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      IconButton(
                        icon: const Icon(Icons.add_rounded, size: 20),
                        tooltip: 'Zoom In',
                        onPressed: _zoomIn,
                        constraints: const BoxConstraints(minWidth: 44, minHeight: 44),
                        padding: EdgeInsets.zero,
                      ),
                      Divider(
                        height: 1,
                        color: theme.colorScheme.outline.withAlpha(70),
                      ),
                      IconButton(
                        icon: const Icon(Icons.remove_rounded, size: 20),
                        tooltip: 'Zoom Out',
                        onPressed: _zoomOut,
                        constraints: const BoxConstraints(minWidth: 44, minHeight: 44),
                        padding: EdgeInsets.zero,
                      ),
                      Divider(
                        height: 1,
                        color: theme.colorScheme.outline.withAlpha(70),
                      ),
                      IconButton(
                        icon: const Icon(Icons.center_focus_strong_rounded, size: 18),
                        tooltip: 'Reset View',
                        onPressed: _resetZoom,
                        constraints: const BoxConstraints(minWidth: 44, minHeight: 44),
                        padding: EdgeInsets.zero,
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

/// Custom vector painter rendering spatial network grid, links, and nodes.
class SchematicMapPainter extends CustomPainter {
  SchematicMapPainter({
    required this.junctions,
    this.roads,
    required this.bounds,
    this.selectedId,
    this.highlightedPath,
  });

  final List<Junction> junctions;
  final List<RoadSegment>? roads;
  final MapCoordinateBounds bounds;
  final int? selectedId;
  final List<int>? highlightedPath;

  @override
  void paint(Canvas canvas, Size size) {
    final gridPaint = Paint()
      ..color = AppTokens.borderDark.withAlpha(45)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0;

    // Draw background schematic grid
    const gridStep = 40.0;
    for (double x = 0; x < size.width; x += gridStep) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), gridPaint);
    }
    for (double y = 0; y < size.height; y += gridStep) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), gridPaint);
    }

    // Project coordinates
    final points = <int, Offset>{};
    for (final j in junctions) {
      points[j.id] = bounds.project(j.latitude!, j.longitude!, size);
    }

    // Draw real road network links connecting intersections (F-06)
    final linkPaint = Paint()
      ..color = AppTokens.teal.withAlpha(55)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.0;

    if (roads != null && roads!.isNotEmpty) {
      for (final road in roads!) {
        if (road.fromIntersectionId != null && road.toIntersectionId != null) {
          final p1 = points[road.fromIntersectionId];
          final p2 = points[road.toIntersectionId];
          if (p1 != null && p2 != null) {
            canvas.drawLine(p1, p2, linkPaint);
          }
        }
      }
    } else {
      // Topologically nearby proximity links (avoiding cross-city zigzags)
      for (int i = 0; i < junctions.length; i++) {
        final p1 = points[junctions[i].id];
        if (p1 == null) continue;
        for (int k = i + 1; k < junctions.length; k++) {
          final p2 = points[junctions[k].id];
          if (p2 == null) continue;
          if ((p1 - p2).distance < 110) {
            canvas.drawLine(p1, p2, linkPaint);
          }
        }
      }
    }

    // Draw highlighted optimal route path overlay if present
    if (highlightedPath != null && highlightedPath!.length >= 2) {
      final routeGlowPaint = Paint()
        ..color = AppTokens.amber.withAlpha(90)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 6.0
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round;

      final routeLinePaint = Paint()
        ..color = AppTokens.amber
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3.5
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round;

      final pathObj = Path();
      bool first = true;
      for (final id in highlightedPath!) {
        final pt = points[id];
        if (pt != null) {
          if (first) {
            pathObj.moveTo(pt.dx, pt.dy);
            first = false;
          } else {
            pathObj.lineTo(pt.dx, pt.dy);
          }
        }
      }
      if (!first) {
        canvas.drawPath(pathObj, routeGlowPaint);
        canvas.drawPath(pathObj, routeLinePaint);
      }
    }

    // Draw junction markers with distinct glyphs (F-14)
    for (final j in junctions) {
      final pos = points[j.id];
      if (pos == null) continue;

      final isSelected = j.id == selectedId;
      final isPathNode = highlightedPath?.contains(j.id) ?? false;
      final status = j.status.toLowerCase();

      Color nodeColor = isPathNode ? AppTokens.amber : AppTokens.teal;
      if (status == 'maintenance') {
        nodeColor = AppTokens.amber;
      } else if (status == 'inactive') {
        nodeColor = AppTokens.danger;
      }

      final glowPaint = Paint()
        ..color = nodeColor.withAlpha(isSelected ? 90 : 35)
        ..style = PaintingStyle.fill;

      final borderPaint = Paint()
        ..color = isSelected ? Colors.white : nodeColor
        ..style = PaintingStyle.stroke
        ..strokeWidth = isSelected ? 2.5 : 1.8;

      final corePaint = Paint()
        ..color = nodeColor
        ..style = PaintingStyle.fill;

      final outerRadius = isSelected ? 22.0 : 14.0;
      final innerRadius = isSelected ? 12.0 : 8.0;
      final coreRadius = isSelected ? 7.0 : 4.0;

      if (status == 'maintenance') {
        // Glyph: Diamond shape for caution / warning (F-14)
        _drawDiamond(canvas, pos, outerRadius, glowPaint);
        _drawDiamond(canvas, pos, innerRadius, borderPaint);
        _drawDiamond(canvas, pos, coreRadius, corePaint);
      } else if (status == 'inactive') {
        // Glyph: Square shape with cross for critical / inactive (F-14)
        final outerRect = Rect.fromCenter(center: pos, width: outerRadius * 2, height: outerRadius * 2);
        final innerRect = Rect.fromCenter(center: pos, width: innerRadius * 2, height: innerRadius * 2);
        canvas.drawRRect(RRect.fromRectAndRadius(outerRect, const Radius.circular(4)), glowPaint);
        canvas.drawRRect(RRect.fromRectAndRadius(innerRect, const Radius.circular(3)), borderPaint);
        final crossPaint = Paint()
          ..color = Colors.white
          ..strokeWidth = 2.0;
        canvas.drawLine(Offset(pos.dx - 3, pos.dy), Offset(pos.dx + 3, pos.dy), crossPaint);
        canvas.drawLine(Offset(pos.dx, pos.dy - 3), Offset(pos.dx, pos.dy + 3), crossPaint);
      } else {
        // Glyph: Circle shape for active / nominal (F-14)
        canvas.drawCircle(pos, outerRadius, glowPaint);
        canvas.drawCircle(pos, innerRadius, borderPaint);
        canvas.drawCircle(pos, coreRadius, corePaint);
      }

      // Decluttered labels (F-201): Draw label if selected, or if small network <= 8 nodes
      if (isSelected || junctions.length <= 8) {
        final textSpan = TextSpan(
          text: j.name,
          style: TextStyle(
            color: isSelected ? Colors.white : const Color(0xFFEAF0FF),
            fontSize: 10,
            fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
          ),
        );
        final textPainter = TextPainter(
          text: textSpan,
          textDirection: TextDirection.ltr,
        )..layout(maxWidth: 120);

        final labelOffset = Offset(
          pos.dx - (textPainter.width / 2),
          pos.dy + (isSelected ? 16 : 12),
        );

        // Draw pill background behind text for readability
        final bgRect = Rect.fromLTWH(
          labelOffset.dx - 4,
          labelOffset.dy - 2,
          textPainter.width + 8,
          textPainter.height + 4,
        );
        final bgPaint = Paint()
          ..color = Colors.black.withAlpha(isSelected ? 180 : 130)
          ..style = PaintingStyle.fill;
        canvas.drawRRect(RRect.fromRectAndRadius(bgRect, const Radius.circular(4)), bgPaint);

        textPainter.paint(canvas, labelOffset);
      }
    }
  }

  void _drawDiamond(Canvas canvas, Offset center, double radius, Paint paint) {
    final path = Path()
      ..moveTo(center.dx, center.dy - radius)
      ..lineTo(center.dx + radius, center.dy)
      ..lineTo(center.dx, center.dy + radius)
      ..lineTo(center.dx - radius, center.dy)
      ..close();
    canvas.drawPath(path, paint);
  }

  @override
  bool shouldRepaint(covariant SchematicMapPainter oldDelegate) {
    return oldDelegate.junctions != junctions ||
        oldDelegate.roads != roads ||
        oldDelegate.selectedId != selectedId ||
        oldDelegate.bounds != bounds ||
        oldDelegate.highlightedPath != highlightedPath;
  }
}
