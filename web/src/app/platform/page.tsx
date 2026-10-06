import React from "react";
import Link from "next/link";
import { Navbar } from "@/components/ui/Navbar";
import { Footer } from "@/components/ui/Footer";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

export const metadata = {
  title: "Operations Dashboard Shell | AI TrafficOS",
  description:
    "Placeholder shell and documented extension point for the AI TrafficOS live operations dashboard (scheduled for Phase 6).",
};

export default function PlatformPage() {
  return (
    <div className="flex flex-col min-h-screen bg-ink text-text">
      <Navbar />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-10 sm:py-14">
        {/* Breadcrumb & Header */}
        <div className="mb-8">
          <div className="flex items-center gap-2 text-xs text-muted mb-3">
            <Link
              href="/"
              className="hover:text-text transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent rounded"
            >
              Home
            </Link>
            <span>/</span>
            <span className="text-text">Platform</span>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-3xl sm:text-4xl font-display font-bold text-text tracking-tight">
                  Operations dashboard
                </h1>
                <Badge variant="amber">Phase 6 Extension Point</Badge>
              </div>
              <p className="mt-3 text-sm sm:text-base text-muted max-w-3xl leading-relaxed">
                The live operations dashboard arrives in Phase 6. This page is a placeholder shell with a documented extension point.
              </p>
            </div>

            <Button href="/" variant="secondary" size="sm">
              ← Return Home
            </Button>
          </div>
        </div>

        {/* Extension Point Architecture Notice */}
        <Card className="p-6 mb-8 border-amber/30 bg-amber/5">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-lg bg-amber/20 text-amber flex items-center justify-center shrink-0 mt-0.5">
                <svg
                  className="w-4 h-4 fill-current"
                  viewBox="0 0 20 20"
                  aria-hidden="true"
                >
                  <path
                    fillRule="evenodd"
                    d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z"
                    clipRule="evenodd"
                  />
                </svg>
              </div>
              <div>
                <h2 className="text-sm font-semibold text-text">
                  Honest Architecture Standard (Phase 1)
                </h2>
                <p className="text-xs text-muted mt-1 leading-relaxed">
                  Per the AI TrafficOS development rules, no mock charts, fabricated live telemetry, or fake counters are rendered here. Below is the structural layout contract reserved for the upcoming integration phases.
                </p>
              </div>
            </div>

            <div className="text-xs font-mono text-muted/80 px-3 py-1.5 rounded bg-surface border border-white/10 shrink-0">
              Contract: /src/app/platform
            </div>
          </div>
        </Card>

        {/* Skeleton Layout (Pulse Placeholders) */}
        <div className="space-y-6" aria-label="Operations dashboard skeleton extension points">
          {/* Top Metric Bar Extension Point */}
          <div>
            <div className="flex items-center justify-between text-xs text-muted mb-2 px-1">
              <span className="font-mono text-accent">Extension Point: Metric Bar (Phase 6)</span>
              <span>Target: WebSocket /telemetry stream</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {[
                "Sensor Ingestion Throughput",
                "Active Intersection Controllers",
                "Telemetry Stream Latency",
                "Incident Flag Pipeline",
              ].map((label) => (
                <Card key={label} className="p-4 border-dashed border-white/15 bg-surface/40">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-muted font-medium">{label}</span>
                    <Badge variant="muted" className="text-[10px]">
                      Skeleton
                    </Badge>
                  </div>
                  <div className="mt-3 h-8 rounded-lg bg-surface/80 animate-pulse flex items-center px-3">
                    <span className="text-[11px] font-mono text-muted/60">
                      [Pending Phase 6 Data Ingestion]
                    </span>
                  </div>
                </Card>
              ))}
            </div>
          </div>

          {/* Main Visualizer & Feed Extension Point */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Map Canvas Extension Point */}
            <div className="lg:col-span-2 space-y-2">
              <div className="flex items-center justify-between text-xs text-muted px-1">
                <span className="font-mono text-accent">Extension Point: Geospatial Canvas</span>
                <span>Target: MapLibre / WebGL</span>
              </div>
              <Card className="h-96 p-6 border-dashed border-white/20 bg-surface/30 flex flex-col items-center justify-center text-center relative overflow-hidden">
                <div className="w-16 h-16 rounded-2xl bg-surface/80 border border-white/10 flex items-center justify-center mb-4 text-2xl animate-pulse">
                  🗺️
                </div>
                <h3 className="font-display font-semibold text-text text-base">
                  Interactive Geospatial Grid Extension Point
                </h3>
                <p className="mt-2 text-xs text-muted max-w-md leading-relaxed">
                  Reserved for MapLibre / deck.gl visualization of traffic nodes, signal timings, and camera streams arriving in Phase 6.
                </p>
                <div className="mt-4 flex items-center gap-2">
                  <Badge variant="muted">Map Engine: Phase 6</Badge>
                  <Badge variant="muted">Live Layers: Phase 6</Badge>
                </div>
              </Card>
            </div>

            {/* Event & Alert Feed Extension Point */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs text-muted px-1">
                <span className="font-mono text-accent">Extension Point: Event Stream</span>
                <span>Target: Redis Pub/Sub</span>
              </div>
              <Card className="h-96 p-5 border-dashed border-white/20 bg-surface/30 flex flex-col justify-between">
                <div>
                  <div className="flex items-center justify-between pb-3 border-b border-white/10">
                    <span className="text-xs font-semibold text-text">Dispatch Events</span>
                    <Badge variant="muted" className="text-[10px]">Pending Feed</Badge>
                  </div>
                  <div className="mt-4 space-y-3">
                    {[1, 2, 3, 4].map((i) => (
                      <div
                        key={i}
                        className="p-3 rounded-lg bg-surface/60 border border-white/5 space-y-2 animate-pulse"
                      >
                        <div className="h-3 w-1/3 bg-white/10 rounded" />
                        <div className="h-2 w-4/5 bg-white/5 rounded" />
                      </div>
                    ))}
                  </div>
                </div>

                <div className="pt-3 border-t border-white/5 text-[11px] text-muted/60 text-center font-mono">
                  No synthetic events rendered
                </div>
              </Card>
            </div>
          </div>
        </div>
      </main>

      <Footer />
    </div>
  );
}
