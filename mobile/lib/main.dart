import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'screens/auth/login_screen.dart';
import 'screens/home_screen.dart';
import 'screens/platform_screen.dart';
import 'screens/roadmap_screen.dart';
import 'screens/shell_screen.dart';
import 'services/auth_service.dart';
import 'services/session.dart';
import 'theme/app_theme.dart';
import 'theme/app_tokens.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const AiTrafficOsApp());
}

/// Root application widget for AI TrafficOS.
class AiTrafficOsApp extends StatelessWidget {
  const AiTrafficOsApp({
    super.key,
    this.initialHome,
  });

  /// Optional override for initial screen (useful for legacy tests and previews).
  final Widget? initialHome;

  @override
  Widget build(BuildContext context) {
    return ProviderScope(
      child: ValueListenableBuilder<ThemeMode>(
        valueListenable: AppTheme.themeModeNotifier,
        builder: (context, themeMode, _) {
          return MaterialApp(
            title: 'AI TrafficOS',
            debugShowCheckedModeBanner: false,
            theme: AppTheme.lightTheme,
            darkTheme: AppTheme.darkTheme,
            themeMode: themeMode,
            home: initialHome ?? const AppAuthGate(),
          );
        },
      ),
    );
  }
}

/// Dynamic root gate routing between Splash/Session Restore, Login, and Shell.
class AppAuthGate extends ConsumerWidget {
  const AppAuthGate({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Triggers session restore on app start
    ref.watch(sessionRestoreProvider);
    final authState = ref.watch(authStateProvider);

    return switch (authState) {
      AuthAuthenticated() => const ShellScreen(),
      AuthAuthenticating(message: final msg) => _SplashScreen(
          statusMessage: msg ?? 'Initializing secure session...',
        ),
      AuthUnauthenticated() => const LoginScreen(),
    };
  }
}

/// Branded splash screen displayed during initial session restore.
class _SplashScreen extends StatelessWidget {
  const _SplashScreen({required this.statusMessage});

  final String statusMessage;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      backgroundColor: AppTokens.ink,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 72,
              height: 72,
              decoration: BoxDecoration(
                color: AppTokens.teal.withAlpha(30),
                borderRadius: BorderRadius.circular(20),
                border: Border.all(
                  color: AppTokens.teal.withAlpha(90),
                  width: 2,
                ),
                boxShadow: const [
                  BoxShadow(
                    color: Color(0x3300D9A8),
                    blurRadius: 28,
                    spreadRadius: 4,
                  ),
                ],
              ),
              child: const Center(
                child: Icon(
                  Icons.traffic_rounded,
                  color: AppTokens.teal,
                  size: 40,
                ),
              ),
            ),
            const SizedBox(height: AppTokens.spaceLg),
            Text(
              'AI TrafficOS',
              style: theme.textTheme.headlineMedium?.copyWith(
                color: AppTokens.textPrimary,
                fontWeight: FontWeight.w800,
                letterSpacing: -0.5,
              ),
            ),
            const SizedBox(height: AppTokens.spaceXs),
            Text(
              'Municipal Autonomous Traffic Platform',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: AppTokens.muted,
              ),
            ),
            const SizedBox(height: AppTokens.space2xl),
            const SizedBox(
              width: 24,
              height: 24,
              child: CircularProgressIndicator(
                strokeWidth: 2.5,
                valueColor: AlwaysStoppedAnimation<Color>(AppTokens.teal),
              ),
            ),
            const SizedBox(height: AppTokens.spaceMd),
            Text(
              statusMessage,
              style: theme.textTheme.bodySmall?.copyWith(
                color: AppTokens.muted,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Navigation shell providing legacy bottom bar navigation between Home, Roadmap, and Platform.
///
/// Preserved for backwards compatibility with earlier phase screens and tests.
class MainNavigationShell extends StatefulWidget {
  const MainNavigationShell({super.key});

  @override
  State<MainNavigationShell> createState() => _MainNavigationShellState();
}

class _MainNavigationShellState extends State<MainNavigationShell> {
  int _currentIndex = 0;

  void _onTabSelected(int index) {
    setState(() {
      _currentIndex = index;
    });
  }

  @override
  Widget build(BuildContext context) {
    final screens = [
      HomeScreen(
        onNavigateTab: _onTabSelected,
      ),
      const RoadmapScreen(),
      const PlatformScreen(),
    ];

    return Scaffold(
      body: IndexedStack(
        index: _currentIndex,
        children: screens,
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex,
        onDestinationSelected: _onTabSelected,
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.home_outlined),
            selectedIcon: Icon(Icons.home_rounded),
            label: 'Home',
          ),
          NavigationDestination(
            icon: Icon(Icons.alt_route_outlined),
            selectedIcon: Icon(Icons.alt_route_rounded),
            label: 'Roadmap',
          ),
          NavigationDestination(
            icon: Icon(Icons.dashboard_outlined),
            selectedIcon: Icon(Icons.dashboard_rounded),
            label: 'Platform',
          ),
        ],
      ),
    );
  }
}
