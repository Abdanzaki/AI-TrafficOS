import 'package:flutter/material.dart';

import '../theme/app_tokens.dart';
import 'app_button.dart';

/// Reusable dark-themed error state widget with user-facing messages and retry action.
class ErrorState extends StatelessWidget {
  const ErrorState({
    super.key,
    required this.message,
    this.title = 'Operation Failed',
    this.icon = Icons.error_outline_rounded,
    this.onRetry,
    this.retryLabel = 'Retry',
    this.isRetrying = false,
  });

  final String message;
  final String title;
  final IconData icon;
  final VoidCallback? onRetry;
  final String retryLabel;
  final bool isRetrying;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.spaceLg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Container(
              width: 60,
              height: 60,
              decoration: BoxDecoration(
                color: AppTokens.danger.withAlpha(25),
                shape: BoxShape.circle,
                border: Border.all(
                  color: AppTokens.danger.withAlpha(80),
                  width: 1.5,
                ),
              ),
              child: Icon(
                icon,
                size: 30,
                color: AppTokens.danger,
              ),
            ),
            const SizedBox(height: AppTokens.spaceMd),
            Text(
              title,
              textAlign: TextAlign.center,
              style: theme.textTheme.titleMedium?.copyWith(
                color: AppTokens.textPrimary,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: AppTokens.spaceSm),
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 320),
              child: Text(
                message,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: AppTokens.muted,
                ),
              ),
            ),
            if (onRetry != null) ...[
              const SizedBox(height: AppTokens.spaceLg),
              AppButton(
                text: retryLabel,
                icon: Icons.refresh_rounded,
                variant: AppButtonVariant.outlined,
                isLoading: isRetrying,
                onPressed: onRetry,
              ),
            ],
          ],
        ),
      ),
    );
  }
}
