import 'package:flutter/material.dart';

import '../theme/app_tokens.dart';

/// Warning banner displayed when the backend API is unreachable or network connectivity fails.
class OfflineBanner extends StatelessWidget {
  const OfflineBanner({
    super.key,
    this.message =
        'Backend server unreachable. Live telemetry and synchronization paused.',
    this.onRetry,
    this.isRetrying = false,
  });

  final String message;
  final VoidCallback? onRetry;
  final bool isRetrying;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(
        horizontal: AppTokens.spaceMd,
        vertical: AppTokens.spaceSm,
      ),
      decoration: BoxDecoration(
        color: AppTokens.amber.withAlpha(25),
        border: const Border(
          bottom: BorderSide(
            color: AppTokens.amber,
            width: 1,
          ),
        ),
      ),
      child: SafeArea(
        top: false,
        bottom: false,
        child: Row(
          children: [
            const Icon(
              Icons.cloud_off_rounded,
              color: AppTokens.amber,
              size: 18,
            ),
            const SizedBox(width: AppTokens.spaceSm),
            Expanded(
              child: Text(
                message,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: AppTokens.amber,
                  fontWeight: FontWeight.w500,
                  fontSize: 12,
                ),
              ),
            ),
            if (onRetry != null) ...[
              const SizedBox(width: AppTokens.spaceSm),
              if (isRetrying)
                const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    valueColor: AlwaysStoppedAnimation<Color>(AppTokens.amber),
                  ),
                )
              else
                InkWell(
                  onTap: onRetry,
                  borderRadius: BorderRadius.circular(4),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 4,
                    ),
                    child: Text(
                      'Retry',
                      style: theme.textTheme.labelSmall?.copyWith(
                        color: AppTokens.amber,
                        fontWeight: FontWeight.w700,
                        decoration: TextDecoration.underline,
                      ),
                    ),
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }
}
