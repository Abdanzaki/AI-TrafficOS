import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../theme/app_tokens.dart';

enum AppButtonVariant {
  primary,
  outlined,
}

/// A pill-shaped action button following AI TrafficOS design system.
///
/// Supports [AppButtonVariant.primary] (solid teal accent) and
/// [AppButtonVariant.outlined] (teal border) variants.
class AppButton extends StatelessWidget {
  const AppButton({
    super.key,
    required this.text,
    this.onPressed,
    this.variant = AppButtonVariant.primary,
    this.icon,
    this.isLoading = false,
    this.isFullWidth = false,
    this.height = 48.0,
  });

  final String text;
  final VoidCallback? onPressed;
  final AppButtonVariant variant;
  final IconData? icon;
  final bool isLoading;
  final bool isFullWidth;
  final double height;

  @override
  Widget build(BuildContext context) {
    final isPrimary = variant == AppButtonVariant.primary;
    final isEnabled = onPressed != null && !isLoading;

    final baseForeground = isPrimary ? AppTokens.ink : AppTokens.teal;
    final foregroundColor = isEnabled ? baseForeground : AppTokens.mutedOf(context);

    final content = Row(
      mainAxisSize: isFullWidth ? MainAxisSize.max : MainAxisSize.min,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        if (isLoading) ...[
          SizedBox(
            width: 18,
            height: 18,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              valueColor: AlwaysStoppedAnimation<Color>(foregroundColor),
            ),
          ),
          const SizedBox(width: AppTokens.spaceSm),
        ] else if (icon != null) ...[
          Icon(icon, size: 18, color: foregroundColor),
          const SizedBox(width: AppTokens.spaceSm),
        ],
        Text(
          text,
          style: GoogleFonts.inter(
            fontSize: 14,
            fontWeight: FontWeight.w600,
            color: foregroundColor,
            letterSpacing: 0.2,
          ),
        ),
      ],
    );

    final buttonStyle = ButtonStyle(
      shape: WidgetStateProperty.all(const StadiumBorder()),
      padding: WidgetStateProperty.all(
        const EdgeInsets.symmetric(
          horizontal: AppTokens.spaceLg,
          vertical: AppTokens.spaceSm,
        ),
      ),
      minimumSize: WidgetStateProperty.all(
        Size(isFullWidth ? double.infinity : 80, height),
      ),
    );

    if (isPrimary) {
      return ElevatedButton(
        onPressed: isEnabled ? onPressed : null,
        style: buttonStyle.copyWith(
          backgroundColor: WidgetStateProperty.resolveWith((states) {
            if (states.contains(WidgetState.disabled)) {
              return AppTokens.surfaceOf(context);
            }
            return AppTokens.teal;
          }),
          foregroundColor: WidgetStateProperty.all(AppTokens.ink),
          elevation: WidgetStateProperty.all(0),
        ),
        child: content,
      );
    } else {
      return OutlinedButton(
        onPressed: isEnabled ? onPressed : null,
        style: buttonStyle.copyWith(
          side: WidgetStateProperty.resolveWith((states) {
            if (states.contains(WidgetState.disabled)) {
              return BorderSide(color: AppTokens.borderOf(context), width: 1.5);
            }
            return const BorderSide(color: AppTokens.teal, width: 1.5);
          }),
          backgroundColor: WidgetStateProperty.all(Colors.transparent),
        ),
        child: content,
      );
    }
  }
}
