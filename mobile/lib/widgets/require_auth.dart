import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../screens/auth/login_screen.dart';
import '../services/auth_service.dart';
import 'loading_state.dart';

/// Authentication route guard widget.
///
/// Ensures the user is logged in before rendering [child].
/// If the authentication state is still initializing, renders [LoadingState].
/// If unauthenticated, displays [LoginScreen].
class RequireAuth extends ConsumerWidget {
  const RequireAuth({
    super.key,
    required this.child,
    this.loadingMessage = 'Verifying secure session...',
  });

  final Widget child;
  final String loadingMessage;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authStateProvider);

    return switch (authState) {
      AuthAuthenticated() => child,
      AuthAuthenticating(message: final msg) => Scaffold(
          body: LoadingState(
            message: msg ?? loadingMessage,
            subtitle: 'AI TrafficOS Municipal Gateway',
          ),
        ),
      AuthUnauthenticated() => const LoginScreen(),
    };
  }
}
