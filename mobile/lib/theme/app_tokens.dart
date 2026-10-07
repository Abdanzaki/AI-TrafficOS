import 'package:flutter/material.dart';

/// Design tokens for AI TrafficOS.
///
/// Contains the core color palette, radii, spacing, and typography scales
/// used across the mobile application.
abstract final class AppTokens {
  // --- Core Colors ---
  static const Color ink = Color(0xFF0B1020);
  static const Color surface = Color(0xFF131A2E);
  static const Color card = Color(0xFF18213A);
  static const Color teal = Color(0xFF00D9A8);
  static const Color amber = Color(0xFFFFB800);
  static const Color danger = Color(0xFFFF4D6D);
  static const Color success = Color(0xFF22C55E);
  static const Color textPrimary = Color(0xFFEAF0FF);
  static const Color muted = Color(0xFF8B93B0);

  // --- Light Theme Support Variants ---
  static const Color inkLight = Color(0xFFF4F6FB);
  static const Color surfaceLight = Color(0xFFFFFFFF);
  static const Color cardLight = Color(0xFFFFFFFF);
  static const Color textPrimaryLight = Color(0xFF0B1020);
  static const Color mutedLight = Color(0xFF64748B);
  static const Color borderLight = Color(0xFFE2E8F0);

  // --- Additional Semantic Tokens ---
  static const Color borderDark = Color(0xFF232D4B);
  static const Color glowTeal = Color(0x3300D9A8);

  // --- Radius Tokens ---
  static const double cardRadiusValue = 14.0;
  static const Radius cardRadius = Radius.circular(cardRadiusValue);
  static const BorderRadius cardBorderRadius = BorderRadius.all(cardRadius);

  static const double pillRadiusValue = 999.0;
  static const Radius pillRadius = Radius.circular(pillRadiusValue);
  static const BorderRadius pillBorderRadius = BorderRadius.all(pillRadius);

  // --- Spacing Scale ---
  static const double space2xs = 2.0;
  static const double spaceXs = 4.0;
  static const double spaceSm = 8.0;
  static const double spaceMd = 16.0;
  static const double spaceLg = 24.0;
  static const double spaceXl = 32.0;
  static const double space2xl = 48.0;
  static const double space3xl = 64.0;
}
