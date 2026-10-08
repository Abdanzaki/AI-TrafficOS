import 'package:flutter/material.dart';

import '../models/junction.dart';
import '../models/road_segment.dart';

/// Filter selection for spatial network views.
enum MapFilter {
  all,
  congested,
  incidents,
}

/// Abstract contract for spatial network map providers.
abstract class MapProvider {
  const MapProvider();

  /// Human-readable identifier of the map provider.
  String get name;

  /// Builds a map widget displaying the supplied [junctions].
  Widget buildJunctionMap({
    required BuildContext context,
    required List<Junction> junctions,
    List<RoadSegment>? roads,
    Junction? selectedJunction,
    ValueChanged<Junction>? onJunctionTapped,
    MapFilter filter = MapFilter.all,
  });
}
