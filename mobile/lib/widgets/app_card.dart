import 'package:flutter/material.dart';

import '../theme/app_tokens.dart';

/// A styled surface card with radius 14 conforming to AI TrafficOS design.
class AppCard extends StatelessWidget {
  const AppCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(AppTokens.spaceMd),
    this.margin,
    this.color,
    this.borderColor,
    this.borderRadius,
    this.onTap,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final EdgeInsetsGeometry? margin;
  final Color? color;
  final Color? borderColor;
  final BorderRadius? borderRadius;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final effectiveRadius = borderRadius ?? AppTokens.cardBorderRadius;
    final effectiveColor = color ?? theme.cardTheme.color ?? AppTokens.cardOf(context);
    final effectiveBorder = borderColor ??
        (theme.brightness == Brightness.dark
            ? AppTokens.borderDark
            : AppTokens.borderLight);

    final cardWidget = Container(
      margin: margin,
      decoration: BoxDecoration(
        color: effectiveColor,
        borderRadius: effectiveRadius,
        border: Border.all(color: effectiveBorder, width: 1),
      ),
      child: Material(
        color: Colors.transparent,
        borderRadius: effectiveRadius,
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          borderRadius: effectiveRadius,
          child: Padding(
            padding: padding,
            child: child,
          ),
        ),
      ),
    );

    return cardWidget;
  }
}
