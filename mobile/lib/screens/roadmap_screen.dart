import 'package:flutter/material.dart';

import '../theme/app_tokens.dart';
import '../widgets/app_badge.dart';
import '../widgets/app_card.dart';

class RoadmapScreen extends StatelessWidget {
  const RoadmapScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    final phases = [
      _RoadmapPhase(
        phaseNumber: 'Phase 1',
        title: 'Foundation & Architecture',
        status: 'Active (Current)',
        statusColor: AppTokens.teal,
        isCurrent: true,
        summary:
            'Flutter project scaffolding, design tokens, M3 dark theme, reusable components, and honest backend health check wiring.',
        deliverables: [
          'Design tokens & Material 3 Dark theme (Space Grotesk + Inter)',
          'Pill buttons, badges, and radius 14 surface cards',
          'Real backend health check API client with safe error handling',
          'Documented WebSocket stub for future Phase 9 streaming',
        ],
      ),
      _RoadmapPhase(
        phaseNumber: 'Phase 2',
        title: 'DSA + Traffic Algorithms',
        status: 'Upcoming',
        statusColor: AppTokens.amber,
        summary:
            'Algorithmic foundations for graph representation, pathfinding, and coordinated green wave traffic light sequencing.',
        deliverables: [
          'Directed graph road network modeling with turn restrictions',
          'A* and Dijkstra dynamic routing algorithms',
          'Fixed-time and actuated signal phase state machines',
          'Green wave corridor synchronization algorithms',
        ],
      ),
      _RoadmapPhase(
        phaseNumber: 'Phase 3',
        title: 'Computer Vision AI',
        status: 'Upcoming',
        statusColor: AppTokens.amber,
        summary:
            'Vision intelligence pipeline for edge camera video streams, vehicle detection, and automated signal detection.',
        deliverables: [
          'YOLOv8 vehicle detection, classification, and speed estimation',
          'Multi-lane vehicle counting & density heatmaps',
          'Optical inspection and state verification of physical signals',
          'Camera frame ingestion pipeline & edge inference pipeline',
        ],
      ),
      _RoadmapPhase(
        phaseNumber: 'Phase 4',
        title: 'Predictive AI',
        status: 'Upcoming',
        statusColor: AppTokens.amber,
        summary:
            'Temporal machine learning forecasting models for arterial bottlenecks and incident anticipation.',
        deliverables: [
          'Time-series congestion forecasting (15m, 30m, 60m horizons)',
          'Weather and event-informed volume impact regression',
          'Anomaly detection for unusual congestion patterns',
          'Predictive bottleneck alerting & preventative rerouting',
        ],
      ),
      _RoadmapPhase(
        phaseNumber: 'Phase 5',
        title: 'Intelligent Traffic Control',
        status: 'Upcoming',
        statusColor: AppTokens.amber,
        summary:
            'Autonomous adaptive signal optimization and emergency vehicle priority override algorithms.',
        deliverables: [
          'Multi-agent reinforcement learning for adaptive phase timing',
          'Automated emergency vehicle preemption (green wave clearance)',
          'Pedestrian demand estimation and crosswalk actuation',
          'Corridor throughput maximization with spillback prevention',
        ],
      ),
      _RoadmapPhase(
        phaseNumber: 'Phase 6',
        title: 'Website',
        status: 'Upcoming',
        statusColor: AppTokens.amber,
        summary:
            'Desktop & web operational center portal for traffic engineers and municipal authorities.',
        deliverables: [
          'Interactive GIS map with live vehicle flow and camera overlays',
          'Signal controller override panels & safety interlocks',
          'Historical reporting, KPI dashboards, and analytics exports',
          'Role-based access control and audit logging',
        ],
      ),
      _RoadmapPhase(
        phaseNumber: 'Phase 7',
        title: 'Mobile App Polish',
        status: 'Upcoming',
        statusColor: AppTokens.amber,
        summary:
            'Deep mobile platform integration with native telemetry, offline caching, and responsive UI polish.',
        deliverables: [
          'Full native mobile telemetry views & camera stream player',
          'Push notifications for severe incidents and signal overrides',
          'Offline-first SQLite caching for road network data',
          'Haptic feedback and responsive tablet layout support',
        ],
      ),
      _RoadmapPhase(
        phaseNumber: 'Phase 8',
        title: 'Real-Time + AI Assistant',
        status: 'Upcoming',
        statusColor: AppTokens.amber,
        summary:
            'Conversational LLM assistant for operators and intelligent automated incident mitigation suggestions.',
        deliverables: [
          'AI Traffic Copilot conversational natural language query engine',
          'Automated incident remediation playbooks & scenario simulation',
          'Voice commands for hands-free dispatch operations',
          'Context-aware knowledge base over municipal traffic bylaws',
        ],
      ),
      _RoadmapPhase(
        phaseNumber: 'Phase 9',
        title: 'Real-Time Stream Engine',
        status: 'Upcoming',
        statusColor: AppTokens.amber,
        summary:
            'WebSocket multiplexer and event-driven data streaming engine connecting edge nodes to clients.',
        deliverables: [
          'Full WebSocket telemetry stream replacing the Phase 1 stub',
          'Sub-second vehicle count broadcasts and signal phase switches',
          'Automatic reconnection, exponential backoff, and heartbeat ping',
          'Efficient binary/Protobuf telemetry serialization',
        ],
      ),
      _RoadmapPhase(
        phaseNumber: 'Phase 10',
        title: 'Award-Winning UX + Performance',
        status: 'Upcoming',
        statusColor: AppTokens.amber,
        summary:
            'Sub-100ms UI latency, 60fps micro-animations, accessible high-contrast themes, and fluid visual hierarchy.',
        deliverables: [
          'Optimized 60 FPS animated signal state transitions',
          'High-density telemetry dashboard with zero dropped frames',
          'Full accessibility (WCAG AA) screen reader labeling',
          'Rich interactive telemetry charts with custom renderers',
        ],
      ),
      _RoadmapPhase(
        phaseNumber: 'Phase 11',
        title: 'Testing + Production Hardening',
        status: 'Upcoming',
        statusColor: AppTokens.amber,
        summary:
            'End-to-end stress testing, edge node failover, containerized deployment, and production verification.',
        deliverables: [
          'Comprehensive integration & golden widget test suite',
          '10,000 concurrent simulated detector streams load testing',
          'Fail-safe default states for traffic signals on network partition',
          'CI/CD pipeline with automated release builds and lint gates',
        ],
      ),
    ];

    return Scaffold(
      appBar: AppBar(
        title: Text(
          'Project Roadmap',
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
            // Honest messaging banner
            Container(
              padding: const EdgeInsets.all(AppTokens.spaceMd),
              decoration: BoxDecoration(
                color: AppTokens.amber.withAlpha(25),
                borderRadius: AppTokens.cardBorderRadius,
                border: Border.all(
                  color: AppTokens.amber.withAlpha(100),
                ),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(
                    Icons.campaign_outlined,
                    color: AppTokens.amber,
                    size: 22,
                  ),
                  const SizedBox(width: AppTokens.spaceSm),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Honest Architecture Guarantee',
                          style: theme.textTheme.titleSmall?.copyWith(
                            color: AppTokens.amber,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(height: AppTokens.space2xs),
                        Text(
                          'Planned capabilities — nothing here is live yet. Live telemetry and feature modules will be connected progressively as each phase backend is completed.',
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: AppTokens.textPrimary,
                            height: 1.4,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: AppTokens.spaceLg),
            ...phases.map((phase) => _buildPhaseCard(theme, phase)),
            const SizedBox(height: AppTokens.spaceXl),
          ],
        ),
      ),
    );
  }

  Widget _buildPhaseCard(ThemeData theme, _RoadmapPhase phase) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppTokens.spaceMd),
      child: AppCard(
        borderColor: phase.isCurrent ? AppTokens.teal.withAlpha(120) : null,
        padding: const EdgeInsets.all(AppTokens.spaceMd),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                AppBadge(
                  label: phase.phaseNumber,
                  color: phase.isCurrent ? AppTokens.teal : AppTokens.muted,
                ),
                const SizedBox(width: AppTokens.spaceSm),
                Expanded(
                  child: Text(
                    phase.title,
                    style: theme.textTheme.titleMedium?.copyWith(
                      color: AppTokens.textPrimary,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                AppBadge(
                  label: phase.status,
                  color: phase.statusColor,
                ),
              ],
            ),
            const SizedBox(height: AppTokens.spaceSm),
            Text(
              phase.summary,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: AppTokens.muted,
              ),
            ),
            const SizedBox(height: AppTokens.spaceMd),
            const Divider(color: AppTokens.borderDark),
            const SizedBox(height: AppTokens.spaceSm),
            Text(
              'Planned Deliverables:',
              style: theme.textTheme.labelSmall?.copyWith(
                color: AppTokens.textPrimary,
                fontWeight: FontWeight.w600,
                letterSpacing: 0.5,
              ),
            ),
            const SizedBox(height: AppTokens.spaceSm),
            ...phase.deliverables.map((item) {
              return Padding(
                padding: const EdgeInsets.only(bottom: AppTokens.spaceXs),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Padding(
                      padding: const EdgeInsets.only(top: 6),
                      child: Container(
                        width: 5,
                        height: 5,
                        decoration: BoxDecoration(
                          color: phase.isCurrent
                              ? AppTokens.teal
                              : AppTokens.muted,
                          shape: BoxShape.circle,
                        ),
                      ),
                    ),
                    const SizedBox(width: AppTokens.spaceSm),
                    Expanded(
                      child: Text(
                        item,
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: AppTokens.textPrimary.withAlpha(220),
                        ),
                      ),
                    ),
                  ],
                ),
              );
            }),
          ],
        ),
      ),
    );
  }
}

class _RoadmapPhase {
  const _RoadmapPhase({
    required this.phaseNumber,
    required this.title,
    required this.status,
    required this.statusColor,
    required this.summary,
    required this.deliverables,
    this.isCurrent = false,
  });

  final String phaseNumber;
  final String title;
  final String status;
  final Color statusColor;
  final String summary;
  final List<String> deliverables;
  final bool isCurrent;
}
