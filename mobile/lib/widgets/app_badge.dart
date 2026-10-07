import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../theme/app_tokens.dart';

/// A pill-shaped status or metadata badge.
class AppBadge extends StatelessWidget {
  const AppBadge({
    super.key,
    required this.label,
    required this.color,
    this.icon,
    this.textColor,
    this.padding = const EdgeInsets.symmetric(
      horizontal: AppTokens.spaceSm + 2,
      vertical: AppTokens.space2xs + 1,
    ),
    this.fontSize = 11.0,
  });

  final String label;
  final Color color;
  final IconData? icon;
  final Color? textColor;
  final EdgeInsetsGeometry padding;
  final double fontSize;

  @override
  Widget build(BuildContext context) {
    final effectiveTextColor = textColor ?? color;

    return Container(
      padding: padding,
      decoration: BoxDecoration(
        color: color.withAlpha(35),
        borderRadius: AppTokens.pillBorderRadius,
        border: Border.all(
          color: color.withAlpha(90),
          width: 1,
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          if (icon != null) ...[
            Icon(
              icon,
              size: fontSize + 1,
              color: effectiveTextColor,
            ),
            const SizedBox(width: AppTokens.spaceXs),
          ],
          Text(
            label,
            style: GoogleFonts.inter(
              fontSize: fontSize,
              fontWeight: FontWeight.w600,
              color: effectiveTextColor,
              letterSpacing: 0.3,
            ),
          ),
        ],
      ),
    );
  }
}
