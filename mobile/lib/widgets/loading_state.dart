import 'package:flutter/material.dart';

import '../theme/app_tokens.dart';

/// Reusable dark-themed loading state widget with customizable message and branding.
class LoadingState extends StatelessWidget {
  const LoadingState({
    super.key,
    this.message = 'Loading data...',
    this.subtitle,
    this.compact = false,
  });

  final String message;
  final String? subtitle;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    if (compact) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(AppTokens.spaceMd),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  valueColor: AlwaysStoppedAnimation<Color>(AppTokens.teal),
                ),
              ),
              const SizedBox(width: AppTokens.spaceSm),
              Text(
                message,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: AppTokens.mutedOf(context),
                ),
              ),
            ],
          ),
        ),
      );
    }

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.spaceXl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Container(
              width: 56,
              height: 56,
              decoration: BoxDecoration(
                color: theme.colorScheme.surface,
                shape: BoxShape.circle,
                border: Border.all(
                  color: AppTokens.teal.withAlpha(60),
                  width: 1.5,
                ),
                boxShadow: const [
                  BoxShadow(
                    color: Color(0x2600D9A8),
                    blurRadius: 16,
                    spreadRadius: 2,
                  ),
                ],
              ),
              child: const Center(
                child: SizedBox(
                  width: 26,
                  height: 26,
                  child: CircularProgressIndicator(
                    strokeWidth: 2.5,
                    valueColor: AlwaysStoppedAnimation<Color>(AppTokens.teal),
                  ),
                ),
              ),
            ),
            const SizedBox(height: AppTokens.spaceLg),
            Text(
              message,
              textAlign: TextAlign.center,
              style: theme.textTheme.titleMedium?.copyWith(
                color: theme.colorScheme.onSurface,
                fontWeight: FontWeight.w600,
              ),
            ),
            if (subtitle != null) ...[
              const SizedBox(height: AppTokens.spaceXs),
              Text(
                subtitle!,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: AppTokens.mutedOf(context),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
