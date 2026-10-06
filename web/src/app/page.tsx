"use client";

import React from "react";
import { motion } from "framer-motion";
import { Navbar } from "@/components/ui/Navbar";
import { Footer } from "@/components/ui/Footer";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { SectionHeading } from "@/components/ui/SectionHeading";
import { Stat } from "@/components/ui/Stat";
import { SystemStatus } from "@/components/SystemStatus";

const ROADMAP_FEATURES = [
  {
    name: "Vehicle Detection",
    emoji: "🚗",
    description:
      "Real-time multi-class vehicle identification and volume tracking using computer vision models.",
    badge: "Phase 2+",
  },
  {
    name: "Signal Detection",
    emoji: "🚦",
    description:
      "Automated optical traffic light status monitoring and intersection phase state capture.",
    badge: "Phase 2+",
  },
  {
    name: "Traffic Prediction",
    emoji: "📈",
    description:
      "Spatio-temporal traffic flow and congestion forecasting using recurrent neural networks.",
    badge: "Phase 2+",
  },
  {
    name: "Route Guidance",
    emoji: "🗺️",
    description:
      "Dynamic congestion-aware navigation strategies and alternate arterial routing dispatch.",
    badge: "Phase 2+",
  },
  {
    name: "Emergency Detection",
    emoji: "🚨",
    description:
      "Priority acoustic and visual identification of sirens, police cruisers, and ambulances.",
    badge: "Phase 2+",
  },
  {
    name: "Incident Detection",
    emoji: "⚠️",
    description:
      "Automated anomaly recognition for collisions, breakdown stalls, and lane blockages.",
    badge: "Phase 2+",
  },
  {
    name: "Signal Optimization",
    emoji: "⚡",
    description:
      "Adaptive green-wave cycle timing algorithms trained with reinforcement learning.",
    badge: "Phase 2+",
  },
  {
    name: "Analytics",
    emoji: "📊",
    description:
      "Macro-level metropolitan throughput telemetry, emissions tracking, and bottleneck reports.",
    badge: "Phase 2+",
  },
  {
    name: "AI Assistant",
    emoji: "🤖",
    description:
      "Operator-facing conversational copilot for natural language traffic queries and dispatch.",
    badge: "Phase 2+",
  },
];

const ARCHITECTURE_STACK = [
  {
    name: "Next.js 15",
    role: "Web Application & App Router",
    spec: "React 19, TypeScript, Tailwind CSS v4",
    status: "Active (Phase 1)",
    statusVariant: "teal" as const,
  },
  {
    name: "FastAPI",
    role: "Backend API & Inference Gateway",
    spec: "Python async microservice framework",
    status: "Phase 2 Target",
    statusVariant: "amber" as const,
  },
  {
    name: "PostgreSQL",
    role: "Relational & Spatial Database",
    spec: "ACID storage with PostGIS geographic support",
    status: "Phase 2 Target",
    statusVariant: "amber" as const,
  },
  {
    name: "Redis",
    role: "Cache & Pub/Sub Message Broker",
    spec: "In-memory low-latency state synchronization",
    status: "Phase 3 Target",
    statusVariant: "amber" as const,
  },
  {
    name: "WebSockets",
    role: "Real-time Telemetry Pipeline",
    spec: "Bidirectional high-frequency sensor streams",
    status: "Phase 4 Target",
    statusVariant: "amber" as const,
  },
];

export default function HomePage() {
  const docsUrl = "https://github.com/Abdanzaki/AI-TrafficOS";

  return (
    <div className="flex flex-col min-h-screen bg-ink text-text">
      <Navbar />

      <main className="flex-1">
        {/* HERO SECTION */}
        <section className="relative overflow-hidden pt-20 pb-16 sm:pt-28 sm:pb-24 border-b border-white/5">
          {/* Subtle background glow */}
          <div className="pointer-events-none absolute -top-40 left-1/2 -translate-x-1/2 w-[600px] h-[350px] bg-accent/10 blur-[130px] rounded-full" />
          <div className="pointer-events-none absolute top-1/2 -left-40 w-[400px] h-[400px] bg-surface blur-[140px] rounded-full" />

          <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              className="text-center max-w-3xl mx-auto"
            >
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-surface/90 border border-white/10 text-xs text-muted mb-6">
                <span className="w-2 h-2 rounded-full bg-accent" />
                <span className="text-text font-medium">Phase 1 Foundation</span>
                <span className="text-white/20">•</span>
                <span>Architecture Specification</span>
              </div>

              <h1 className="text-4xl sm:text-5xl lg:text-6xl font-display font-extrabold text-text tracking-tight leading-[1.15]">
                AI TrafficOS
                <span className="block mt-2 text-2xl sm:text-3xl lg:text-4xl font-normal text-muted">
                  The intelligent operating system for urban traffic
                </span>
              </h1>

              <p className="mt-6 text-base sm:text-lg text-muted max-w-2xl mx-auto leading-relaxed">
                An AI-powered intelligent traffic management platform engineered to coordinate multi-modal sensor perception, adaptive signal control, and urban flow optimization.
              </p>

              <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
                <Button href="/platform" variant="primary" size="lg">
                  Explore the Platform
                </Button>
                <Button
                  href={docsUrl}
                  external
                  variant="secondary"
                  size="lg"
                >
                  Read the Docs
                </Button>
              </div>
            </motion.div>

            {/* HONEST STATS STRIP */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.15 }}
              className="mt-16 grid grid-cols-2 md:grid-cols-4 gap-4"
            >
              <Stat
                label="Current Stage"
                value="Phase 1"
                helperText="Foundation & Architecture scaffold verified."
              />
              <Stat
                label="Full Roadmap"
                value="11 Phases"
                helperText="Structured progression from core to deployment."
              />
              <Stat
                label="Frontend Engine"
                value="Next.js 15"
                helperText="React 19 App Router with Tailwind CSS v4."
              />
              <Stat
                label="Integrity"
                value="Zero Mock Data"
                helperText="Strict honesty policy: no fabricated live traffic stats."
              />
            </motion.div>
          </div>
        </section>

        {/* ROADMAP FEATURE GRID */}
        <section className="py-20 sm:py-24 border-b border-white/5 relative">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <SectionHeading
              eyebrow="Capability Roadmap"
              title="Planned Future Capabilities"
              description="The 9 intelligent modules below represent future roadmap milestones planned for Phases 2 through 11. These are architecture specifications, not currently functioning live features in Phase 1."
            />

            <div className="mt-12 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
              {ROADMAP_FEATURES.map((feat, idx) => (
                <motion.div
                  key={feat.name}
                  initial={{ opacity: 0, y: 15 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.35, delay: idx * 0.04 }}
                >
                  <Card
                    interactive
                    className="p-6 h-full flex flex-col justify-between"
                  >
                    <div>
                      <div className="flex items-center justify-between gap-3 mb-4">
                        <div className="w-10 h-10 rounded-xl bg-ink/70 border border-white/10 flex items-center justify-center text-xl">
                          <span role="img" aria-label={feat.name}>
                            {feat.emoji}
                          </span>
                        </div>
                        <Badge variant="teal">{feat.badge}</Badge>
                      </div>
                      <h3 className="font-display font-semibold text-lg text-text">
                        {feat.name}
                      </h3>
                      <p className="mt-2 text-sm text-muted leading-relaxed">
                        {feat.description}
                      </p>
                    </div>

                    <div className="mt-5 pt-4 border-t border-white/5 flex items-center justify-between text-xs text-muted/80">
                      <span>Milestone Target</span>
                      <span className="font-mono text-accent">Phased Integration</span>
                    </div>
                  </Card>
                </motion.div>
              ))}
            </div>
          </div>
        </section>

        {/* ARCHITECTURE STRIP */}
        <section className="py-20 sm:py-24 bg-surface/30 border-b border-white/5">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <SectionHeading
              eyebrow="System Design"
              title="Phase 1 Architecture Foundation"
              description="The technology foundation designed to scale from initial web scaffolding to full-scale traffic perception and neural edge control."
            />

            {/* System Status Banner */}
            <div className="mt-10 flex justify-center">
              <SystemStatus />
            </div>

            <div className="mt-12 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
              {ARCHITECTURE_STACK.map((tech) => (
                <Card
                  key={tech.name}
                  className="p-5 flex flex-col justify-between bg-surface/70"
                >
                  <div>
                    <div className="flex items-center justify-between gap-2 mb-3">
                      <span className="font-display font-bold text-base text-text">
                        {tech.name}
                      </span>
                      <Badge variant={tech.statusVariant} className="text-[10px]">
                        {tech.status}
                      </Badge>
                    </div>
                    <div className="text-xs font-semibold text-accent">
                      {tech.role}
                    </div>
                    <p className="mt-2 text-xs text-muted leading-normal">
                      {tech.spec}
                    </p>
                  </div>

                  <div className="mt-4 pt-3 border-t border-white/5 text-[11px] text-muted/70 font-mono">
                    Tier: Foundation Spec
                  </div>
                </Card>
              ))}
            </div>
          </div>
        </section>

        {/* CTA SECTION */}
        <section className="py-20 sm:py-24 relative overflow-hidden">
          <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
            <Card className="p-8 sm:p-12 relative overflow-hidden border-accent/20 bg-gradient-to-b from-surface to-ink">
              <div className="pointer-events-none absolute -bottom-24 left-1/2 -translate-x-1/2 w-[400px] h-[200px] bg-accent/15 blur-[90px] rounded-full" />

              <h2 className="text-2xl sm:text-3xl lg:text-4xl font-display font-bold text-text">
                Ready to inspect the AI TrafficOS architecture?
              </h2>
              <p className="mt-4 text-sm sm:text-base text-muted max-w-xl mx-auto leading-relaxed">
                Review the operations dashboard shell or check the open-source repository for technical documentation, architectural blueprints, and phase roadmaps.
              </p>

              <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
                <Button href="/platform" variant="primary" size="md">
                  Open Operations Shell
                </Button>
                <Button
                  href={docsUrl}
                  external
                  variant="secondary"
                  size="md"
                >
                  View on GitHub
                </Button>
              </div>
            </Card>
          </div>
        </section>
      </main>

      <Footer />
    </div>
  );
}
