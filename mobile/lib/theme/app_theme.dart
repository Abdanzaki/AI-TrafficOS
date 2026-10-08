import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import 'app_tokens.dart';

/// Application theme configurations for AI TrafficOS.
///
/// Features a dark-first Material 3 theme with custom typography
/// (Space Grotesk for display/headings and Inter for body), custom cards,
/// and pill-shaped action buttons.
class AppTheme {
  AppTheme._();

  /// Reactive notifier for the app's current theme mode. Defaults to [ThemeMode.dark].
  static final ValueNotifier<ThemeMode> themeModeNotifier =
      ValueNotifier<ThemeMode>(ThemeMode.dark);

  /// Default theme mode for the application.
  static const ThemeMode defaultThemeMode = ThemeMode.dark;

  /// Helper to toggle or set theme mode.
  static void setThemeMode(ThemeMode mode) {
    themeModeNotifier.value = mode;
  }

  /// Builds custom TextTheme combining Space Grotesk (headings) and Inter (body).
  static TextTheme _buildTextTheme({
    required Color primaryTextColor,
    required Color mutedTextColor,
  }) {
    final baseInter = GoogleFonts.interTextTheme();
    final baseSpaceGrotesk = GoogleFonts.spaceGroteskTextTheme();

    return baseInter.copyWith(
      // Display: Space Grotesk
      displayLarge: baseSpaceGrotesk.displayLarge?.copyWith(
        color: primaryTextColor,
        fontWeight: FontWeight.w700,
        letterSpacing: -1.0,
      ),
      displayMedium: baseSpaceGrotesk.displayMedium?.copyWith(
        color: primaryTextColor,
        fontWeight: FontWeight.w700,
        letterSpacing: -0.5,
      ),
      displaySmall: baseSpaceGrotesk.displaySmall?.copyWith(
        color: primaryTextColor,
        fontWeight: FontWeight.w600,
      ),

      // Headline: Space Grotesk
      headlineLarge: baseSpaceGrotesk.headlineLarge?.copyWith(
        color: primaryTextColor,
        fontWeight: FontWeight.w700,
      ),
      headlineMedium: baseSpaceGrotesk.headlineMedium?.copyWith(
        color: primaryTextColor,
        fontWeight: FontWeight.w600,
      ),
      headlineSmall: baseSpaceGrotesk.headlineSmall?.copyWith(
        color: primaryTextColor,
        fontWeight: FontWeight.w600,
      ),

      // Title: Space Grotesk
      titleLarge: baseSpaceGrotesk.titleLarge?.copyWith(
        color: primaryTextColor,
        fontWeight: FontWeight.w600,
      ),
      titleMedium: baseSpaceGrotesk.titleMedium?.copyWith(
        color: primaryTextColor,
        fontWeight: FontWeight.w500,
      ),
      titleSmall: baseSpaceGrotesk.titleSmall?.copyWith(
        color: mutedTextColor,
        fontWeight: FontWeight.w500,
      ),

      // Body: Inter
      bodyLarge: baseInter.bodyLarge?.copyWith(
        color: primaryTextColor,
        fontSize: 16,
        height: 1.5,
      ),
      bodyMedium: baseInter.bodyMedium?.copyWith(
        color: primaryTextColor,
        fontSize: 14,
        height: 1.4,
      ),
      bodySmall: baseInter.bodySmall?.copyWith(
        color: mutedTextColor,
        fontSize: 12,
        height: 1.3,
      ),

      // Labels: Inter
      labelLarge: baseInter.labelLarge?.copyWith(
        color: primaryTextColor,
        fontWeight: FontWeight.w600,
        fontSize: 14,
      ),
      labelMedium: baseInter.labelMedium?.copyWith(
        color: mutedTextColor,
        fontWeight: FontWeight.w500,
        fontSize: 12,
      ),
      labelSmall: baseInter.labelSmall?.copyWith(
        color: mutedTextColor,
        fontWeight: FontWeight.w500,
        fontSize: 10,
        letterSpacing: 0.5,
      ),
    );
  }

  /// Dark Theme (DEFAULT)
  static ThemeData get darkTheme {
    final textTheme = _buildTextTheme(
      primaryTextColor: AppTokens.textPrimary,
      mutedTextColor: AppTokens.muted,
    );

    final colorScheme = const ColorScheme.dark(
      primary: AppTokens.teal,
      onPrimary: AppTokens.ink,
      primaryContainer: AppTokens.card,
      onPrimaryContainer: AppTokens.teal,
      secondary: AppTokens.teal,
      onSecondary: AppTokens.ink,
      surface: AppTokens.surface,
      onSurface: AppTokens.textPrimary,
      error: AppTokens.danger,
      onError: Colors.white,
      outline: AppTokens.borderDark,
    );

    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      scaffoldBackgroundColor: AppTokens.ink,
      colorScheme: colorScheme,
      textTheme: textTheme,
      cardTheme: CardThemeData(
        color: AppTokens.card,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: AppTokens.cardBorderRadius,
          side: const BorderSide(color: AppTokens.borderDark, width: 1),
        ),
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.transparent,
        scrolledUnderElevation: 0,
        elevation: 0,
        foregroundColor: AppTokens.textPrimary,
        centerTitle: false,
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: AppTokens.teal,
          foregroundColor: AppTokens.ink,
          elevation: 0,
          shape: const StadiumBorder(),
          textStyle: GoogleFonts.inter(
            fontWeight: FontWeight.w600,
            fontSize: 14,
          ),
          padding: const EdgeInsets.symmetric(
            horizontal: AppTokens.spaceLg,
            vertical: AppTokens.spaceMd,
          ),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AppTokens.teal,
          foregroundColor: AppTokens.ink,
          elevation: 0,
          shape: const StadiumBorder(),
          textStyle: GoogleFonts.inter(
            fontWeight: FontWeight.w600,
            fontSize: 14,
          ),
          padding: const EdgeInsets.symmetric(
            horizontal: AppTokens.spaceLg,
            vertical: AppTokens.spaceMd,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: AppTokens.teal,
          side: const BorderSide(color: AppTokens.teal, width: 1.5),
          shape: const StadiumBorder(),
          textStyle: GoogleFonts.inter(
            fontWeight: FontWeight.w600,
            fontSize: 14,
          ),
          padding: const EdgeInsets.symmetric(
            horizontal: AppTokens.spaceLg,
            vertical: AppTokens.spaceMd,
          ),
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: AppTokens.surface,
        indicatorColor: AppTokens.teal.withAlpha(40),
        elevation: 0,
        labelTextStyle: WidgetStateProperty.resolveWith((states) {
          final isSelected = states.contains(WidgetState.selected);
          return GoogleFonts.inter(
            fontSize: 12,
            fontWeight: isSelected ? FontWeight.w600 : FontWeight.w400,
            color: isSelected ? AppTokens.teal : AppTokens.muted,
          );
        }),
        iconTheme: WidgetStateProperty.resolveWith((states) {
          final isSelected = states.contains(WidgetState.selected);
          return IconThemeData(
            color: isSelected ? AppTokens.teal : AppTokens.muted,
            size: 22,
          );
        }),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: AppTokens.card,
        shape: RoundedRectangleBorder(
          borderRadius: AppTokens.cardBorderRadius,
          side: const BorderSide(color: AppTokens.borderDark, width: 1),
        ),
      ),
      bottomSheetTheme: const BottomSheetThemeData(
        backgroundColor: AppTokens.surface,
        surfaceTintColor: Colors.transparent,
      ),
      dividerTheme: const DividerThemeData(
        color: AppTokens.borderDark,
        thickness: 1,
      ),
    );
  }

  /// Light Theme variant
  static ThemeData get lightTheme {
    final textTheme = _buildTextTheme(
      primaryTextColor: AppTokens.textPrimaryLight,
      mutedTextColor: AppTokens.mutedLight,
    );

    final colorScheme = const ColorScheme.light(
      primary: AppTokens.teal,
      onPrimary: Colors.white,
      primaryContainer: AppTokens.inkLight,
      onPrimaryContainer: AppTokens.teal,
      secondary: AppTokens.teal,
      onSecondary: Colors.white,
      surface: AppTokens.surfaceLight,
      onSurface: AppTokens.textPrimaryLight,
      error: AppTokens.danger,
      onError: Colors.white,
      outline: AppTokens.borderLight,
    );

    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      scaffoldBackgroundColor: AppTokens.inkLight,
      colorScheme: colorScheme,
      textTheme: textTheme,
      cardTheme: CardThemeData(
        color: AppTokens.cardLight,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: AppTokens.cardBorderRadius,
          side: const BorderSide(color: AppTokens.borderLight, width: 1),
        ),
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.transparent,
        scrolledUnderElevation: 0,
        elevation: 0,
        foregroundColor: AppTokens.textPrimaryLight,
        centerTitle: false,
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: AppTokens.teal,
          foregroundColor: AppTokens.ink,
          elevation: 0,
          shape: const StadiumBorder(),
          textStyle: GoogleFonts.inter(
            fontWeight: FontWeight.w600,
            fontSize: 14,
          ),
          padding: const EdgeInsets.symmetric(
            horizontal: AppTokens.spaceLg,
            vertical: AppTokens.spaceMd,
          ),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AppTokens.teal,
          foregroundColor: AppTokens.ink,
          elevation: 0,
          shape: const StadiumBorder(),
          textStyle: GoogleFonts.inter(
            fontWeight: FontWeight.w600,
            fontSize: 14,
          ),
          padding: const EdgeInsets.symmetric(
            horizontal: AppTokens.spaceLg,
            vertical: AppTokens.spaceMd,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: AppTokens.teal,
          side: const BorderSide(color: AppTokens.teal, width: 1.5),
          shape: const StadiumBorder(),
          textStyle: GoogleFonts.inter(
            fontWeight: FontWeight.w600,
            fontSize: 14,
          ),
          padding: const EdgeInsets.symmetric(
            horizontal: AppTokens.spaceLg,
            vertical: AppTokens.spaceMd,
          ),
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: AppTokens.surfaceLight,
        indicatorColor: AppTokens.teal.withAlpha(30),
        elevation: 0,
        labelTextStyle: WidgetStateProperty.resolveWith((states) {
          final isSelected = states.contains(WidgetState.selected);
          return GoogleFonts.inter(
            fontSize: 12,
            fontWeight: isSelected ? FontWeight.w600 : FontWeight.w400,
            color: isSelected ? AppTokens.teal : AppTokens.mutedLight,
          );
        }),
        iconTheme: WidgetStateProperty.resolveWith((states) {
          final isSelected = states.contains(WidgetState.selected);
          return IconThemeData(
            color: isSelected ? AppTokens.teal : AppTokens.mutedLight,
            size: 22,
          );
        }),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: AppTokens.cardLight,
        shape: RoundedRectangleBorder(
          borderRadius: AppTokens.cardBorderRadius,
          side: const BorderSide(color: AppTokens.borderLight, width: 1),
        ),
      ),
      bottomSheetTheme: const BottomSheetThemeData(
        backgroundColor: AppTokens.surfaceLight,
        surfaceTintColor: Colors.transparent,
      ),
      dividerTheme: const DividerThemeData(
        color: AppTokens.borderLight,
        thickness: 1,
      ),
    );
  }
}
