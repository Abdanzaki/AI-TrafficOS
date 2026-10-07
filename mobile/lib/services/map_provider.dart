import 'package:flutter/material.dart';

import '../models/junction.dart';

/// Filter selection for spatial network views.
enum MapFilter {
  all,
  congested,
  incidents,
}

/// Abstract contract for spatial network map providers.
///
/// AI TrafficOS decouples the spatial UI layer from underlying map SDKs.
///
/// Production Integration Architecture:
/// - **Default Provider**: [SchematicJunctionMapProvider] (custom vector CustomPainter
///   with lat/lon normalization, interactive pan/zoom, and coordinate projection).
/// - **MapLibre Native ([maplibre_gl])**:
///   To switch to MapLibre vector tiles:
///   1. Add `maplibre_gl: ^0.16.0` to `pubspec.yaml`.
///   2. Configure Vector Tile Endpoint (e.g., self-hosted Martin or Tegola tile server,
///      or MapTiler key via `AppConfig.mapTileUrl`).
///   3. Implement `MapLibreJunctionMapProvider implements MapProvider` rendering
///      a `MaplibreMap` widget with GeoJSON SymbolLayer / CircleLayer for junctions.
/// - **Google Maps ([google_maps_flutter])**:
///   To switch to Google Maps SDK:
///   1. Add `google_maps_flutter` and register Google Cloud API keys in
///      `android/app/src/main/AndroidManifest.xml` and `ios/Runner/AppDelegate.swift`.
///   2. Implement `GoogleMapsJunctionMapProvider implements MapProvider` rendering
///      `GoogleMap` with `BitmapDescriptor` custom colored markers.
/// - **Projections & Precision**:
///   Coordinates use standard WGS 84 (EPSG:4326). When plotting at city scale,
///   Mercator or local equirectangular projection ensures distortion-free spacing.
abstract class MapProvider {
  const MapProvider();

  /// Human-readable identifier of the map provider.
  String get name;

  /// Builds a map widget displaying the supplied [junctions].
  Widget buildJunctionMap({
    required BuildContext context,
    required List<Junction> junctions,
    Junction? selectedJunction,
    ValueChanged<Junction>? onJunctionTapped,
    MapFilter filter = MapFilter.all,
  });
}
