import 'package:ai_trafficos/models/user.dart';
import 'package:ai_trafficos/services/auth_service.dart';
import 'package:ai_trafficos/widgets/require_role.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('RequireRole Guard', () {
    testWidgets('renders child when user possesses allowed write role',
        (tester) async {
      const officer = User(
        id: 1,
        email: 'officer@trafficos.ai',
        fullName: 'Traffic Officer',
        role: User.roleTrafficOfficer,
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            currentUserProvider.overrideWithValue(officer),
          ],
          child: const MaterialApp(
            home: Scaffold(
              body: RequireRole(
                allowedRoles: [User.roleAdmin, User.roleTrafficOfficer],
                child: Text('Protected Traffic Override Screen'),
              ),
            ),
          ),
        ),
      );

      expect(find.text('Protected Traffic Override Screen'), findsOneWidget);
      expect(find.text('Read-Only Role Restricted'), findsNothing);
    });

    testWidgets('blocks analyst from write screen with clear read-only message',
        (tester) async {
      const analyst = User(
        id: 2,
        email: 'analyst@trafficos.ai',
        fullName: 'Municipal Analyst',
        role: User.roleAnalyst,
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            currentUserProvider.overrideWithValue(analyst),
          ],
          child: const MaterialApp(
            home: Scaffold(
              body: RequireRole(
                allowedRoles: [User.roleAdmin, User.roleTrafficOfficer],
                screenTitle: 'Manual Signal Phase Control',
                child: Text('Protected Traffic Override Screen'),
              ),
            ),
          ),
        ),
      );

      // Verify protected screen is blocked
      expect(find.text('Protected Traffic Override Screen'), findsNothing);

      // Verify clear read-only message and title are displayed
      expect(find.text('Read-Only Role Restricted'), findsOneWidget);
      expect(find.text('Manual Signal Phase Control'), findsOneWidget);
      expect(
        find.textContaining("assigned the 'Analyst' role, which has read-only access"),
        findsOneWidget,
      );
    });
  });
}
