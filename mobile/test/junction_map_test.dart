import 'package:ai_trafficos/models/junction.dart';
import 'package:ai_trafficos/models/road_segment.dart';
import 'package:ai_trafficos/theme/app_tokens.dart';
import 'package:ai_trafficos/widgets/junction_map.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

bool sameColor(Color a, Color b) => a.toARGB32() == b.toARGB32();

/// Test canvas spy capturing drawn paths and lines to inspect road network rendering.
class SpyCanvas implements Canvas {
  final List<Path> drawnPaths = [];
  final List<Paint> pathPaints = [];
  final List<(Offset, Offset, Paint)> drawnLines = [];

  @override
  void drawPath(Path path, Paint paint) {
    drawnPaths.add(path);
    pathPaints.add(Paint()
      ..color = paint.color
      ..strokeWidth = paint.strokeWidth
      ..style = paint.style);
  }

  @override
  void drawLine(Offset p1, Offset p2, Paint paint) {
    drawnLines.add((
      p1,
      p2,
      Paint()
        ..color = paint.color
        ..strokeWidth = paint.strokeWidth
        ..style = paint.style,
    ));
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

void main() {
  const junctions = [
    Junction(
      id: 1,
      name: 'Junction North',
      code: 'JN-01',
      status: 'active',
      latitude: 28.70,
      longitude: 77.10,
    ),
    Junction(
      id: 2,
      name: 'Junction South',
      code: 'JS-02',
      status: 'active',
      latitude: 28.60,
      longitude: 77.20,
    ),
  ];

  final bounds = MapCoordinateBounds.fromJunctions(junctions)!;

  group('Congestion Color Mapping Boundaries', () {
    test('returns teal at alpha 55 for null or NaN congestion level without inventing data', () {
      expect(
        SchematicMapPainter.congestionColor(null),
        equals(AppTokens.teal.withAlpha(55)),
      );
      expect(
        SchematicMapPainter.congestionColor(double.nan),
        equals(AppTokens.teal.withAlpha(55)),
      );
      expect(
        SchematicMapPainter.roadColorForCongestion(null),
        equals(AppTokens.teal.withAlpha(55)),
      );
    });

    test('returns success (green) for level < 0.33', () {
      expect(SchematicMapPainter.congestionColor(0.0), equals(AppTokens.success));
      expect(SchematicMapPainter.congestionColor(0.15), equals(AppTokens.success));
      expect(SchematicMapPainter.congestionColor(0.32), equals(AppTokens.success));
      expect(SchematicMapPainter.congestionColor(0.3299), equals(AppTokens.success));
    });

    test('returns amber for boundary 0.33 up to and including 0.66', () {
      expect(SchematicMapPainter.congestionColor(0.33), equals(AppTokens.amber));
      expect(SchematicMapPainter.congestionColor(0.45), equals(AppTokens.amber));
      expect(SchematicMapPainter.congestionColor(0.66), equals(AppTokens.amber));
    });

    test('returns danger (red) for level > 0.66', () {
      expect(SchematicMapPainter.congestionColor(0.6601), equals(AppTokens.danger));
      expect(SchematicMapPainter.congestionColor(0.75), equals(AppTokens.danger));
      expect(SchematicMapPainter.congestionColor(1.0), equals(AppTokens.danger));
    });
  });

  group('GeoJSON Coordinate Parsing', () {
    test('parses JSON array of [lon, lat] pairs', () {
      const geo = '[[77.10, 28.70], [77.15, 28.65], [77.20, 28.60]]';
      final coords = SchematicMapPainter.parseCoordinates(geo);
      expect(coords, isNotNull);
      expect(coords!.length, equals(3));
      expect(coords[0].lat, equals(28.70));
      expect(coords[0].lon, equals(77.10));
      expect(coords[1].lat, equals(28.65));
      expect(coords[1].lon, equals(77.15));
      expect(coords[2].lat, equals(28.60));
      expect(coords[2].lon, equals(77.20));
    });

    test('parses object with coordinates property', () {
      const geo = '{"coordinates": [[77.10, 28.70], [77.20, 28.60]]}';
      final coords = SchematicMapPainter.parseCoordinates(geo);
      expect(coords, isNotNull);
      expect(coords!.length, equals(2));
      expect(coords[0].lat, equals(28.70));
      expect(coords[0].lon, equals(77.10));
      expect(coords[1].lat, equals(28.60));
      expect(coords[1].lon, equals(77.20));
    });

    test('parses GeoJSON LineString and Feature formats', () {
      const lineString =
          '{"type": "LineString", "coordinates": [[77.10, 28.70], [77.20, 28.60]]}';
      final c1 = SchematicMapPainter.parseCoordinates(lineString);
      expect(c1, isNotNull);
      expect(c1!.length, equals(2));

      const feature =
          '{"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[77.10, 28.70], [77.20, 28.60]]}}';
      final c2 = SchematicMapPainter.parseCoordinates(feature);
      expect(c2, isNotNull);
      expect(c2!.length, equals(2));
    });

    test('returns null for geometry with fewer than 2 valid points or malformed coordinates', () {
      expect(SchematicMapPainter.parseCoordinates(null), isNull);
      expect(SchematicMapPainter.parseCoordinates(''), isNull);
      expect(SchematicMapPainter.parseCoordinates('   '), isNull);
      expect(SchematicMapPainter.parseCoordinates('{not json'), isNull);
      expect(SchematicMapPainter.parseCoordinates('123'), isNull);
      expect(SchematicMapPainter.parseCoordinates('[]'), isNull);
      expect(SchematicMapPainter.parseCoordinates('[[77.10]]'), isNull);
      expect(SchematicMapPainter.parseCoordinates('[[77.10, 28.70]]'), isNull);
      expect(SchematicMapPainter.parseCoordinates('[[77.10, 28.70], ["bad", 28.60]]'), isNull);
      expect(SchematicMapPainter.parseCoordinates('{"coordinates": "not-list"}'), isNull);
      expect(SchematicMapPainter.parseCoordinates('{"coordinates": []}'), isNull);
      expect(SchematicMapPainter.parseCoordinates('{"coordinates": [[77.10, 28.70]]}'), isNull);
    });
  });

  group('GeoJSON Polyline Rendering Path', () {
    test('renders polyline via drawPath using projected coordinates and congestion colors', () {
      final roads = [
        const RoadSegment(
          id: 101,
          name: 'Green Arterial Corridor',
          roadType: 'arterial',
          geometry: '[[77.10, 28.70], [77.15, 28.65], [77.20, 28.60]]',
          fromIntersectionId: 1,
          toIntersectionId: 2,
        ),
        const RoadSegment(
          id: 102,
          name: 'Amber Highway Corridor',
          roadType: 'highway',
          geometry: '{"coordinates": [[77.10, 28.70], [77.20, 28.60]]}',
          fromIntersectionId: 1,
          toIntersectionId: 2,
        ),
        const RoadSegment(
          id: 103,
          name: 'Danger Bottleneck Corridor',
          roadType: 'arterial',
          geometry: '[[77.10, 28.70], [77.20, 28.60]]',
          fromIntersectionId: 1,
          toIntersectionId: 2,
        ),
      ];

      final congestionLevels = <int, double>{
        101: 0.15, // green (< 0.33)
        102: 0.50, // amber (0.33 - 0.66)
        103: 0.85, // danger (> 0.66)
      };

      final painter = SchematicMapPainter(
        junctions: junctions,
        roads: roads,
        congestionLevels: congestionLevels,
        bounds: bounds,
      );

      final canvas = SpyCanvas();
      painter.paint(canvas, const Size(400, 400));

      // 3 roads with valid geometry should be rendered as paths
      expect(canvas.drawnPaths.length, equals(3));
      expect(canvas.pathPaints.length, equals(3));

      // Check colors corresponding to congestion
      expect(sameColor(canvas.pathPaints[0].color, AppTokens.success), isTrue);
      expect(sameColor(canvas.pathPaints[1].color, AppTokens.amber), isTrue);
      expect(sameColor(canvas.pathPaints[2].color, AppTokens.danger), isTrue);

      // Visual identity checks
      expect(canvas.pathPaints[0].strokeWidth, equals(2.0));
      expect(canvas.pathPaints[0].style, equals(PaintingStyle.stroke));
      expect(canvas.pathPaints[1].strokeWidth, equals(2.0));
      expect(canvas.pathPaints[2].strokeWidth, equals(2.0));
    });

    test('renders polyline with default teal at alpha 55 when road id is not in congestionLevels', () {
      final roads = [
        const RoadSegment(
          id: 201,
          name: 'Unmonitored Corridor',
          roadType: 'arterial',
          geometry: '[[77.10, 28.70], [77.20, 28.60]]',
          fromIntersectionId: 1,
          toIntersectionId: 2,
        ),
      ];

      final painter = SchematicMapPainter(
        junctions: junctions,
        roads: roads,
        congestionLevels: const {}, // empty, no congestion for id 201
        bounds: bounds,
      );

      final canvas = SpyCanvas();
      painter.paint(canvas, const Size(400, 400));

      expect(canvas.drawnPaths.length, equals(1));
      expect(sameColor(canvas.pathPaints[0].color, AppTokens.teal.withAlpha(55)), isTrue);
    });
  });

  group('Fallback to Straight Line on Bad Geometry', () {
    test('falls back to straight line between from/to intersections when geometry is null', () {
      final roads = [
        const RoadSegment(
          id: 301,
          name: 'Null Geometry Road',
          roadType: 'arterial',
          geometry: null,
          fromIntersectionId: 1,
          toIntersectionId: 2,
        ),
      ];

      final painter = SchematicMapPainter(
        junctions: junctions,
        roads: roads,
        congestionLevels: {301: 0.20}, // success
        bounds: bounds,
      );

      final canvas = SpyCanvas();
      painter.paint(canvas, const Size(400, 400));

      expect(canvas.drawnPaths, isEmpty);
      // Background grid lines are drawn, and the road fallback line is drawn
      final roadLines = canvas.drawnLines
          .where((line) => sameColor(line.$3.color, AppTokens.success))
          .toList();
      expect(roadLines.length, equals(1));
      expect(roadLines[0].$3.strokeWidth, equals(2.0));
    });

    test('falls back to straight line on malformed geometry strings without crashing', () {
      const badGeometries = [
        '{not json',
        '123',
        '[]',
        '[[77.10, 28.70]]', // single point
        '[[77.10, 28.70], ["bad", 28.60]]',
        '{"coordinates": "not-list"}',
        '{"coordinates": []}',
      ];

      for (int i = 0; i < badGeometries.length; i++) {
        final road = RoadSegment(
          id: 400 + i,
          name: 'Bad Geometry Road $i',
          roadType: 'arterial',
          geometry: badGeometries[i],
          fromIntersectionId: 1,
          toIntersectionId: 2,
        );

        final painter = SchematicMapPainter(
          junctions: junctions,
          roads: [road],
          congestionLevels: {road.id: 0.80}, // danger
          bounds: bounds,
        );

        final canvas = SpyCanvas();
        expect(
          () => painter.paint(canvas, const Size(400, 400)),
          returnsNormally,
          reason: 'Must not crash on bad geometry: ${badGeometries[i]}',
        );

        expect(canvas.drawnPaths, isEmpty);
        final roadLines = canvas.drawnLines
            .where((line) => sameColor(line.$3.color, AppTokens.danger))
            .toList();
        expect(roadLines.length, equals(1));
      }
    });

    test('does not draw and does not crash when geometry is bad and intersection ids are null', () {
      const road = RoadSegment(
        id: 501,
        name: 'Orphan Bad Geometry Road',
        roadType: 'arterial',
        geometry: '{invalid',
        fromIntersectionId: null,
        toIntersectionId: null,
      );

      final painter = SchematicMapPainter(
        junctions: junctions,
        roads: const [road],
        congestionLevels: {501: 0.5},
        bounds: bounds,
      );

      final canvas = SpyCanvas();
      expect(() => painter.paint(canvas, const Size(400, 400)), returnsNormally);
      expect(canvas.drawnPaths, isEmpty);
      final roadLines = canvas.drawnLines
          .where((line) => sameColor(line.$3.color, AppTokens.amber))
          .toList();
      expect(roadLines, isEmpty);
    });
  });

  group('Null Congestion Levels (No Crash)', () {
    test('renders cleanly with null congestionLevels for both polylines and straight lines', () {
      final roads = [
        const RoadSegment(
          id: 601,
          name: 'Polyline Road',
          roadType: 'arterial',
          geometry: '[[77.10, 28.70], [77.20, 28.60]]',
          fromIntersectionId: 1,
          toIntersectionId: 2,
        ),
        const RoadSegment(
          id: 602,
          name: 'Straight Line Road',
          roadType: 'collector',
          geometry: null,
          fromIntersectionId: 1,
          toIntersectionId: 2,
        ),
      ];

      final painter = SchematicMapPainter(
        junctions: junctions,
        roads: roads,
        congestionLevels: null, // explicitly null
        bounds: bounds,
      );

      final canvas = SpyCanvas();
      expect(() => painter.paint(canvas, const Size(400, 400)), returnsNormally);

      // Polyline drawn with teal at alpha 55
      expect(canvas.drawnPaths.length, equals(1));
      expect(sameColor(canvas.pathPaints[0].color, AppTokens.teal.withAlpha(55)), isTrue);

      // Straight line drawn with teal at alpha 55
      final roadLines = canvas.drawnLines
          .where((line) => sameColor(line.$3.color, AppTokens.teal.withAlpha(55)))
          .toList();
      expect(roadLines.length, equals(1));
    });

    testWidgets('JunctionMapWidget passes congestionLevels and renders without crashing when null', (tester) async {
      final roads = [
        const RoadSegment(
          id: 701,
          name: 'Polyline Road',
          roadType: 'arterial',
          geometry: '[[77.10, 28.70], [77.20, 28.60]]',
          fromIntersectionId: 1,
          toIntersectionId: 2,
        ),
        const RoadSegment(
          id: 702,
          name: 'Straight Road',
          roadType: 'arterial',
          geometry: null,
          fromIntersectionId: 1,
          toIntersectionId: 2,
        ),
      ];

      // Pump widget with congestionLevels == null
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 500,
              height: 500,
              child: JunctionMapWidget(
                junctions: junctions,
                roads: roads,
                congestionLevels: null,
              ),
            ),
          ),
        ),
      );

      await tester.pumpAndSettle();

      final customPaintFinder = find.byType(CustomPaint);
      expect(customPaintFinder, findsWidgets);

      final customPaint = tester.widget<CustomPaint>(
        find.descendant(
          of: find.byType(InteractiveViewer),
          matching: find.byType(CustomPaint),
        ),
      );
      final painter = customPaint.painter as SchematicMapPainter;
      expect(painter.congestionLevels, isNull);
      expect(painter.roads, equals(roads));
    });

    testWidgets('JunctionMapWidget correctly passes congestionLevels to painter', (tester) async {
      final roads = [
        const RoadSegment(
          id: 801,
          name: 'Monitored Polyline',
          roadType: 'arterial',
          geometry: '[[77.10, 28.70], [77.20, 28.60]]',
          fromIntersectionId: 1,
          toIntersectionId: 2,
        ),
      ];
      final congestionLevels = <int, double>{801: 0.72};

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 500,
              height: 500,
              child: JunctionMapWidget(
                junctions: junctions,
                roads: roads,
                congestionLevels: congestionLevels,
              ),
            ),
          ),
        ),
      );

      await tester.pumpAndSettle();

      final customPaint = tester.widget<CustomPaint>(
        find.descendant(
          of: find.byType(InteractiveViewer),
          matching: find.byType(CustomPaint),
        ),
      );
      final painter = customPaint.painter as SchematicMapPainter;
      expect(painter.congestionLevels, equals(congestionLevels));
    });
  });

  group('SchematicMapPainter shouldRepaint Extension', () {
    test('returns true when congestionLevels reference changes', () {
      final painter1 = SchematicMapPainter(
        junctions: junctions,
        bounds: bounds,
        congestionLevels: const {1: 0.1},
      );
      final painter2 = SchematicMapPainter(
        junctions: junctions,
        bounds: bounds,
        congestionLevels: const {1: 0.8},
      );

      expect(painter1.shouldRepaint(painter2), isTrue);
    });

    test('returns false when all painter properties are identical', () {
      const congestion = {1: 0.5};
      final painter1 = SchematicMapPainter(
        junctions: junctions,
        bounds: bounds,
        congestionLevels: congestion,
      );
      final painter2 = SchematicMapPainter(
        junctions: junctions,
        bounds: bounds,
        congestionLevels: congestion,
      );

      expect(painter1.shouldRepaint(painter2), isFalse);
    });
  });
}
