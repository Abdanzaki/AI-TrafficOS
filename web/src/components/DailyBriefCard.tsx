"use client";

import React, { useState } from "react";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Calendar,
  Clock,
  Flame,
  HelpCircle,
  Minus,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { useApiQuery } from "@/lib/use-api";
import { Card } from "@/components/ui/Card";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ErrorState } from "@/components/ui/ErrorState";
import { formatDateTime } from "@/lib/format";

export interface IncidentBriefSection {
  provenance: "observed";
  has_data: boolean;
  count: number | null;
  total: number | null;
  by_severity: Record<string, number>;
  by_type: Record<string, number>;
  note: string | null;
}

export interface ViolationBriefSection {
  provenance: "observed";
  has_data: boolean;
  count: number | null;
  total: number | null;
  by_type: Record<string, number>;
  note: string | null;
}

export interface HotspotItem {
  intersection_id: number;
  intersection_name: string;
  intersection_code: string | null;
  predicted_congestion: number | null;
  predicted_flow: number | null;
  confidence: number | null;
  predicted_for: string | null;
}

export interface HotspotBriefSection {
  provenance: "predicted";
  has_data: boolean;
  items: HotspotItem[];
  note: string | null;
}

export interface TrendBriefSection {
  provenance: "observed";
  has_sufficient_history: boolean;
  incident_delta: number | null;
  violation_delta: number | null;
  direction: "increased" | "decreased" | "stable" | null;
  note: string | null;
}

export interface DailyBriefData {
  generated_at: string;
  date: string;
  summary_text: string;
  rephrased: boolean;
  incidents: IncidentBriefSection;
  violations: ViolationBriefSection;
  hotspots: HotspotBriefSection;
  trends: TrendBriefSection;
}

export interface DailyBriefCardProps {
  className?: string;
  defaultDate?: string;
}

export const DailyBriefCard: React.FC<DailyBriefCardProps> = ({
  className = "",
  defaultDate,
}) => {
  const [rephrase, setRephrase] = useState<boolean>(false);
  const [showNarrative, setShowNarrative] = useState<boolean>(false);

  const {
    data: brief,
    isLoading,
    isFetching,
    error,
    refetch,
  } = useApiQuery<DailyBriefData>({
    queryKey: ["daily-brief", { rephrase, date: defaultDate }],
    endpoint: "/briefs/daily",
    params: {
      rephrase,
      ...(defaultDate ? { date: defaultDate } : {}),
    },
  });

  if (isLoading) {
    return (
      <Card className={`p-6 sm:p-8 ${className}`}>
        <div className="flex items-center justify-between pb-4 border-b border-line mb-6">
          <div className="flex items-center gap-2">
            <Calendar className="w-5 h-5 text-accent" />
            <h2 className="text-base sm:text-lg font-display font-bold text-text">
              Daily Traffic Operations Brief
            </h2>
          </div>
        </div>
        <div className="flex flex-col items-center justify-center py-12 gap-3 text-muted">
          <LoadingSpinner size="md" />
          <span className="text-xs font-mono">Aggregating morning telemetry & forecast models...</span>
        </div>
      </Card>
    );
  }

  if (error || !brief) {
    return (
      <Card className={`p-6 ${className}`}>
        <ErrorState
          title="Daily Brief Unavailable"
          message={error?.message || "Failed to load morning operations brief."}
          onRetry={() => refetch()}
        />
      </Card>
    );
  }

  return (
    <Card className={`p-6 sm:p-8 space-y-6 ${className}`}>
      {/* Header with Title, Timestamp, Provenance, & Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-line">
        <div>
          <div className="flex items-center gap-2 flex-wrap mb-1.5">
            <Badge variant="signal" dot>
              Morning Brief
            </Badge>
            <span className="text-ink/20">•</span>
            <span className="text-xs text-muted font-mono flex items-center gap-1">
              <Calendar className="w-3.5 h-3.5" />
              Target: {brief.date}
            </span>
            <span className="text-ink/20">•</span>
            <span className="text-[11px] text-muted font-mono flex items-center gap-1">
              <Clock className="w-3 h-3" />
              Generated: {formatDateTime(brief.generated_at)}
            </span>
          </div>

          <h2 className="text-lg sm:text-xl font-display font-bold text-text tracking-tight flex items-center gap-2">
            <span>Daily Traffic Operations Brief</span>
            {brief.rephrased && (
              <Badge variant="amber" className="text-[10px] normal-case tracking-normal">
                <Sparkles className="w-2.5 h-2.5 mr-1 text-amber" />
                Gemini Rephrased
              </Badge>
            )}
          </h2>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={() => setRephrase((prev) => !prev)}
            className={`px-3 py-1.5 rounded-xl text-xs font-medium transition-all flex items-center gap-1.5 cursor-pointer border ${
              rephrase
                ? "bg-amber/15 text-amber border-amber/30 shadow-sm"
                : "bg-surface/80 text-muted hover:text-text border-line"
            }`}
            title="Toggle grounded conversational rendering via GeminiProvider"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>Conversational</span>
          </button>

          <Button
            variant="secondary"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
            className="cursor-pointer"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? "animate-spin" : ""}`} />
            <span className="hidden sm:inline ml-1">Refresh</span>
          </Button>
        </div>
      </div>

      {/* 4 Core Sections Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Section 1: Observed Incidents */}
        <div className="p-4 rounded-xl bg-cream border border-line flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-muted uppercase tracking-wider flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5 text-danger" />
                Observed Incidents
              </span>
              <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-ink/5 text-muted border border-line">
                {brief.incidents.provenance}
              </span>
            </div>

            {brief.incidents.has_data && brief.incidents.count !== null ? (
              <div>
                <div className="text-2xl sm:text-3xl font-display font-bold text-text">
                  {brief.incidents.count}
                </div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {Object.entries(brief.incidents.by_severity).map(([sev, count]) => {
                    const badgeVariant: BadgeVariant =
                      sev === "critical"
                        ? "danger"
                        : sev === "high"
                        ? "amber"
                        : "muted";
                    return (
                      <Badge key={sev} variant={badgeVariant} className="text-[10px] py-0 px-2">
                        {sev}: {count}
                      </Badge>
                    );
                  })}
                </div>
              </div>
            ) : (
              <div className="py-2">
                <div className="text-xs font-medium text-muted/80 italic">
                  {brief.incidents.note || "No incident data recorded"}
                </div>
              </div>
            )}
          </div>

          <div className="mt-3 pt-2 border-t border-line text-[11px] text-muted font-mono">
            Window: Yesterday
          </div>
        </div>

        {/* Section 2: Observed Violations */}
        <div className="p-4 rounded-xl bg-cream border border-line flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-muted uppercase tracking-wider flex items-center gap-1.5">
                <ShieldAlert className="w-3.5 h-3.5 text-amber" />
                Observed Violations
              </span>
              <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-ink/5 text-muted border border-line">
                {brief.violations.provenance}
              </span>
            </div>

            {brief.violations.has_data && brief.violations.count !== null ? (
              <div>
                <div className="text-2xl sm:text-3xl font-display font-bold text-text">
                  {brief.violations.count}
                </div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {Object.entries(brief.violations.by_type).map(([vType, count]) => (
                    <Badge key={vType} variant="amber" className="text-[10px] py-0 px-2">
                      {vType.replace("_", " ")}: {count}
                    </Badge>
                  ))}
                </div>
              </div>
            ) : (
              <div className="py-2">
                <div className="text-xs font-medium text-muted/80 italic">
                  {brief.violations.note || "No violation records found"}
                </div>
              </div>
            )}
          </div>

          <div className="mt-3 pt-2 border-t border-line text-[11px] text-muted font-mono">
            Edge perception query
          </div>
        </div>

        {/* Section 3: Forecasted Hotspots */}
        <div className="p-4 rounded-xl bg-cream border border-line flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-muted uppercase tracking-wider flex items-center gap-1.5">
                <Flame className="w-3.5 h-3.5 text-accent" />
                Forecasted Hotspots
              </span>
              <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-accent/10 text-accent border border-accent/20">
                {brief.hotspots.provenance}
              </span>
            </div>

            {brief.hotspots.has_data && brief.hotspots.items.length > 0 ? (
              <div className="space-y-1.5">
                {brief.hotspots.items.slice(0, 2).map((item) => (
                  <div key={item.intersection_id} className="text-xs">
                    <div className="flex items-center justify-between font-medium text-text truncate">
                      <span className="truncate">{item.intersection_name}</span>
                      <span className="font-mono text-accent shrink-0 ml-1">
                        {item.predicted_congestion !== null
                          ? `${item.predicted_congestion.toFixed(0)}%`
                          : "High"}
                      </span>
                    </div>
                  </div>
                ))}
                {brief.hotspots.items.length > 2 && (
                  <div className="text-[10px] text-muted font-mono">
                    +{brief.hotspots.items.length - 2} more predicted
                  </div>
                )}
              </div>
            ) : (
              <div className="py-2">
                <div className="text-xs font-medium text-muted/80 italic">
                  {brief.hotspots.note || "No forward predictions available"}
                </div>
              </div>
            )}
          </div>

          <div className="mt-3 pt-2 border-t border-line text-[11px] text-muted font-mono">
            Model: AI Forecaster
          </div>
        </div>

        {/* Section 4: Operational Trends & Deltas */}
        <div className="p-4 rounded-xl bg-cream border border-line flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-muted uppercase tracking-wider flex items-center gap-1.5">
                <TrendingUp className="w-3.5 h-3.5 text-accent" />
                Day-over-Day Trends
              </span>
              <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-ink/5 text-muted border border-line">
                {brief.trends.provenance}
              </span>
            </div>

            {brief.trends.has_sufficient_history ? (
              <div className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted">Incidents:</span>
                  <span
                    className={`font-mono font-bold flex items-center gap-0.5 ${
                      (brief.trends.incident_delta ?? 0) > 0
                        ? "text-danger"
                        : (brief.trends.incident_delta ?? 0) < 0
                        ? "text-success"
                        : "text-muted"
                    }`}
                  >
                    {(brief.trends.incident_delta ?? 0) > 0 ? (
                      <ArrowUpRight className="w-3 h-3" />
                    ) : (brief.trends.incident_delta ?? 0) < 0 ? (
                      <ArrowDownRight className="w-3 h-3" />
                    ) : (
                      <Minus className="w-3 h-3" />
                    )}
                    {brief.trends.incident_delta !== null
                      ? `${brief.trends.incident_delta > 0 ? "+" : ""}${brief.trends.incident_delta}`
                      : "—"}
                  </span>
                </div>

                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted">Violations:</span>
                  <span
                    className={`font-mono font-bold flex items-center gap-0.5 ${
                      (brief.trends.violation_delta ?? 0) > 0
                        ? "text-amber"
                        : (brief.trends.violation_delta ?? 0) < 0
                        ? "text-success"
                        : "text-muted"
                    }`}
                  >
                    {(brief.trends.violation_delta ?? 0) > 0 ? (
                      <ArrowUpRight className="w-3 h-3" />
                    ) : (brief.trends.violation_delta ?? 0) < 0 ? (
                      <ArrowDownRight className="w-3 h-3" />
                    ) : (
                      <Minus className="w-3 h-3" />
                    )}
                    {brief.trends.violation_delta !== null
                      ? `${brief.trends.violation_delta > 0 ? "+" : ""}${brief.trends.violation_delta}`
                      : "—"}
                  </span>
                </div>
              </div>
            ) : (
              <div className="py-2">
                <div className="text-xs font-medium text-muted/80 italic flex items-center gap-1">
                  <HelpCircle className="w-3.5 h-3.5 text-muted shrink-0" />
                  <span>{brief.trends.note || "Insufficient history (<2 days of data)"}</span>
                </div>
              </div>
            )}
          </div>

          <div className="mt-3 pt-2 border-t border-line text-[11px] text-muted font-mono">
            History: {brief.trends.has_sufficient_history ? ">= 2 days verified" : "< 2 days recorded"}
          </div>
        </div>
      </div>

      {/* Grounded Brief Narrative Accordion */}
      <div className="pt-2">
        <button
          type="button"
          onClick={() => setShowNarrative((prev) => !prev)}
          className="text-xs font-medium text-accent hover:text-accent/80 transition-colors flex items-center gap-1 cursor-pointer"
        >
          <span>{showNarrative ? "Hide Grounded Brief Narrative" : "View Grounded Brief Narrative"}</span>
        </button>

        {showNarrative && (
          <div className="mt-3 p-4 rounded-xl bg-surface border border-line text-xs text-text/90 font-mono whitespace-pre-wrap leading-relaxed max-h-64 overflow-y-auto">
            {brief.summary_text}
          </div>
        )}
      </div>
    </Card>
  );
};
