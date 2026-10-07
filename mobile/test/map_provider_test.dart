import 'package:ai_trafficos/models/junction.dart';
import 'package:ai_trafficos/widgets/empty_state.dart';
import 'package:ai_trafficos/widgets/junction_map.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('Map Coordinate Normalization Math', () {
    test('MapCoordinateBounds returns null on empty list or junctions with null coordinates', () {
      expect(MapCoordinateBounds.fromJunctions([]), isNull);

      final noCoords = [
        const Junction(id: 1, name: 'Node 1', code: 'N1', status: 'active'),
        const Junction(id: 2, name: 'Node 2', code: 'N2', status: 'active'),
      ];
      expect(MapCoordinateBounds.fromJunctions(noCoords), isNull);
    });

    test('MapCoordinateBounds correctly calculates min/max bounds', () {
      final junctions = [
        const Junction(
          id: 1,
          name: 'Southwest Node',
          code: 'SW',
          status: 'active',
          latitude: 37.70,
          longitude: -122.50,
        ),
        const Junction(
          id: 2,
          name: 'Northeast Node',
          code: 'NE',
          status: 'active',
          latitude: 37.80,
          longitude: -122.40,
        ),
      ];

      final bounds = MapCoordinateBounds.fromJunctions(junctions);
      expect(bounds, isNotNull);
      expect(bounds!.minLat, 37.70);
      expect(bounds.maxLat, 37.80);
      expect(bounds.minLon, -122.50);
      expect(bounds.maxLon, -122.40);
    });

    test('MapCoordinateBounds expands bounds for single junction to prevent division by zero', () {
      final junctions = [
        const Junction(
          id: 1,
          name: 'Single Node',
          code: 'SN',
          status: 'active',
          latitude: 40.7128,
          longitude: -74.0060,
        ),
      ];

      final bounds = MapCoordinateBounds.fromJunctions(junctions);
      expect(bounds, isNotNull);
      expect(bounds!.minLat, lessThan(bounds.maxLat));
      expect(bounds.minLon, lessThan(bounds.maxLon));
      expect(bounds.minLat, closeTo(40.7128 - 0.005, 0.0001));
      expect(bounds.maxLat, closeTo(40.7128 + 0.005, 0.0001));
    });

    test('project projects lat/lon to viewport with inverted Y axis for geographic screen space', () {
      const bounds = MapCoordinateBounds(
        minLat: 10.0,
        maxLat: 20.0,
        minLon: 100.0,
        maxLon: 200.0,
      );

      const size = Size(500, 300);
      const padding = 50.0;

      // Available width: 500 - 100 = 400
      // Available height: 300 - 100 = 200

      // Point at Northwest: maxLat (20.0), minLon (100.0) -> Should map to Top-Left: (padding, padding)
      final nw = bounds.project(20.0, 100.0, size, padding: padding);
      expect(nw.dx, closeTo(50.0, 0.001));
      expect(nw.dy, closeTo(50.0, 0.001));

      // Point at Southeast: minLat (10.0), maxLon (200.0) -> Should map to Bottom-Right: (450.0, 250.0)
      final se = bounds.project(10.0, 200.0, size, padding: padding);
      expect(se.dx, closeTo(450.0, 0.001));
      expect(se.dy, closeTo(250.0, 0.001));

      // Center point: lat 15.0, lon 150.0 -> Should map to Center: (250.0, 150.0)
      final center = bounds.project(15.0, 150.0, size, padding: padding);
      expect(center.dx, closeTo(250.0, 0.001));
      expect(center.dy, closeTo(150.0, 0.001));
    });
  });

  group('JunctionMapWidget UI Tests', () {
    testWidgets('renders EmptyState when junction list has no coordinates', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: JunctionMapWidget(
              junctions: [
                Junction(id: 1, name: 'Node 1', code: 'N1', status: 'active'),
              ],
            ),
          ),
        ),
      );

      expect(find.byType(EmptyState), findsOneWidget);
      expect(find.text('No Junction Coordinates'), findsOneWidget);
    });

    testWidgets('renders CustomPaint schematic map when junctions have valid lat/lon', (tester) async {
      final junctions = [
        const Junction(
          id: 1,
          name: 'Intersection Alpha',
          code: 'INT-A',
          status: 'active',
          latitude: 37.77,
          longitude: -122.41,
        ),
        const Junction(
          id: 2,
          name: 'Intersection Beta',
          code: 'INT-B',
          status: 'maintenance',
          latitude: 37.78,
          longitude: -122.40,
        ),
      ];

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 400,
              height: 600,
              child: JunctionMapWidget(junctions: junctions),
            ),
          ),
        ),
      );

      expect(find.byType(CustomPaint), findsWidgets);
      expect(find.byType(EmptyState), findsNothing);
    });

    testWidgets('SchematicJunctionMapProvider builds JunctionMapWidget correctly', (tester) async {
      const provider = SchematicJunctionMapProvider();
      expect(provider.name, 'Schematic Spatial View');

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (context) {
                return provider.buildJunctionMap(
                  context: context,
                  junctions: const [
                    Junction(
                      id: 1,
                      name: 'Node Alpha',
                      code: 'NA',
                      status: 'active',
                      latitude: 10.0,
                      longitude: 20.0,
                    ),
                  ],
                );
              },
            ),
          ),
        ),
      );

      expect(find.byType(JunctionMapWidget), findsOneWidget);
    });
  });
}
