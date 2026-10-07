import 'package:flutter/material.dart';

import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_card.dart';
import '../widgets/section_header.dart';

/// Skeleton placeholder screen representing the future Operations Dashboard.
///
/// Follows the strict Phase 1 honest architecture policy:
/// Static skeleton shapes only, zero fake metrics, zero simulated counters.
class PlatformScreen extends StatelessWidget {
  const PlatformScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: Text(
          'Operations Platform',
          style: theme.textTheme.titleLarge?.copyWith(
            fontWeight: FontWeight.w700,
            color: AppTokens.textPrimary,
          ),
        ),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(AppTokens.spaceMd),
          children: [
            _buildNoticeBanner(theme),
            const SizedBox(height: AppTokens.spaceLg),
            const SectionHeader(
              title: 'Live Telemetry Metrics',
              subtitle: 'Corridor vehicle velocity, density, and cycle delays',
            ),
            _buildSkeletonMetricsGrid(),
            const SizedBox(height: AppTokens.spaceLg),
            const SectionHeader(
              title: 'Corridor GIS & Camera Feed',
              subtitle: 'Synchronized intersection video stream and signal phases',
            ),
            _buildSkeletonStreamViewport(theme),
            const SizedBox(height: AppTokens.spaceLg),
            const SectionHeader(
              title: 'Active Incident Feed',
              subtitle: 'Real-time anomalies detected by Computer Vision engine',
            ),
            _buildSkeletonIncidentList(),
            const SizedBox(height: AppTokens.spaceXl),
          ],
        ),
      ),
    );
  }

  Widget _buildNoticeBanner(ThemeData theme) {
    return Container(
      padding: const EdgeInsets.all(AppTokens.spaceMd),
      decoration: BoxDecoration(
        color: AppTokens.surface,
        borderRadius: AppTokens.cardBorderRadius,
        border: Border.all(
          color: AppTokens.borderDark,
          width: 1,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              AppBadge(
                label: 'Phase 1 foundation',
                color: AppTokens.teal,
              ),
              SizedBox(width: AppTokens.spaceSm),
              AppBadge(
                label: 'Placeholder',
                color: AppTokens.muted,
              ),
            ],
          ),
          const SizedBox(height: AppTokens.spaceSm),
          Text(
            'Operations dashboard arrives in later phases',
            style: theme.textTheme.titleSmall?.copyWith(
              color: AppTokens.textPrimary,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: AppTokens.space2xs),
          Text(
            'This layout illustrates planned operational telemetry slots. In adherence to Phase 1 guidelines, no simulated numbers, fake charts, or mock streams are rendered.',
            style: theme.textTheme.bodySmall?.copyWith(
              color: AppTokens.muted,
              height: 1.4,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSkeletonMetricsGrid() {
    return GridView.count(
      crossAxisCount: 2,
      crossAxisSpacing: AppTokens.spaceSm,
      mainAxisSpacing: AppTokens.spaceSm,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      childAspectRatio: 1.8,
      children: List.generate(4, (index) {
        return const AppCard(
          padding: EdgeInsets.all(AppTokens.spaceMd),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              _SkeletonBox(width: 70, height: 10),
              _SkeletonBox(width: 90, height: 22),
            ],
          ),
        );
      }),
    );
  }

  Widget _buildSkeletonStreamViewport(ThemeData theme) {
    return AppCard(
      padding: const EdgeInsets.all(AppTokens.spaceLg),
      child: Column(
        children: [
          Container(
            height: 180,
            width: double.infinity,
            decoration: BoxDecoration(
              color: const Color(0xFF0F1526),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: AppTokens.borderDark),
            ),
            child: Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    Icons.videocam_outlined,
                    size: 36,
                    color: AppTokens.muted.withAlpha(120),
                  ),
                  const SizedBox(height: AppTokens.spaceSm),
                  Text(
                    'Camera Feed Viewport Slot',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: AppTokens.muted,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                  Text(
                    'Awaits Phase 3 CV Pipeline',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: AppTokens.muted.withAlpha(150),
                      fontSize: 10,
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: AppTokens.spaceMd),
          const Row(
            children: [
              _SkeletonBox(width: 100, height: 12),
              Spacer(),
              _SkeletonBox(width: 60, height: 12),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildSkeletonIncidentList() {
    return Column(
      children: List.generate(3, (index) {
        return Padding(
          padding: const EdgeInsets.only(bottom: AppTokens.spaceSm),
          child: AppCard(
            padding: const EdgeInsets.all(AppTokens.spaceMd),
            child: Row(
              children: [
                Container(
                  width: 32,
                  height: 32,
                  decoration: BoxDecoration(
                    color: AppTokens.surface,
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: AppTokens.borderDark),
                  ),
                  child: const Center(
                    child: _SkeletonBox(width: 14, height: 14, radius: 4),
                  ),
                ),
                const SizedBox(width: AppTokens.spaceMd),
                const Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _SkeletonBox(width: 140, height: 12),
                      SizedBox(height: 6),
                      _SkeletonBox(width: 200, height: 10),
                    ],
                  ),
                ),
                const SizedBox(width: AppTokens.spaceSm),
                const _SkeletonBox(width: 48, height: 18, radius: 999),
              ],
            ),
          ),
        );
      }),
    );
  }
}

/// Static skeleton box placeholder without animated tickers or fake numbers.
class _SkeletonBox extends StatelessWidget {
  const _SkeletonBox({
    required this.width,
    required this.height,
    this.radius = 6.0,
  });

  final double width;
  final double height;
  final double radius;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: width,
      height: height,
      decoration: BoxDecoration(
        color: const Color(0xFF202A47),
        borderRadius: BorderRadius.circular(radius),
      ),
    );
  }
}
