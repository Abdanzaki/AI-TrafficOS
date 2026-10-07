import 'package:ai_trafficos/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('AI TrafficOS app smoke test - legacy shell preview',
      (WidgetTester tester) async {
    await tester.pumpWidget(const AiTrafficOsApp(
      initialHome: MainNavigationShell(),
    ));

    // Verify app title appears
    expect(find.text('AI TrafficOS'), findsOneWidget);

    // Verify navigation tabs exist
    expect(find.text('Home'), findsOneWidget);
    expect(find.text('Roadmap'), findsOneWidget);
    expect(find.text('Platform'), findsOneWidget);

    // Verify Phase 1 status message
    expect(
      find.text('Phase 1 foundation — live data arrives in later phases.'),
      findsOneWidget,
    );
  });

  testWidgets('AI TrafficOS app boots to session restore splash or auth gate',
      (WidgetTester tester) async {
    await tester.pumpWidget(const AiTrafficOsApp());

    // Verify root title
    expect(find.text('AI TrafficOS'), findsWidgets);
  });
}
