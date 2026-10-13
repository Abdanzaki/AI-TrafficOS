"use client";

import React, { useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Info,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import { useApiQuery } from "@/lib/use-api";
import { Card } from "@/components/ui/Card";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";

export interface SignalHealthFactorItem {
  name: string;
  weight: number;
  raw_value: unknown;
  penalty: number;
  status: "normal" | "warning" | "critical";
  description: string;
}

export interface SignalHealthItem {
  signal_id: number;
  signal_code: string;
  intersection_id: number;
  score: number;
  status_band: "healthy" | "degraded" | "at-risk";
  explanation: string;
  factors: SignalHealthFactorItem[];
  provenance: string;
  evaluated_at: string;
  metrics?: {
    total_penalty?: number;
    rapid_flapping_switches?: number;
    telemetry_age_seconds?: number | null;
    anomalous_dwell_count?: number;
    operating_status?: string;
  };
}

export interface SignalHealthListResponse {
  items: SignalHealthItem[];
  total: number;
  healthy_count: number;
  degraded_count: number;
  at_risk_count: number;
  provenance: string;
}

export interface SignalHealthPanelProps {
  intersectionId?: number;
  className?: string;
}

function getBandBadgeVariant(band: string): BadgeVariant {
  switch (band.toLowerCase()) {
    case "healthy":
      return "success";
    case "degraded":
      return "amber";
    case "at-risk":
    case "at_risk":
      return "danger";
    default:
      return "muted";
  }
}

function getFactorLabel(name: string): string {
  switch (name) {
    case "controller_status":
      return "Hardware Operating Status";
    case "phase_flapping":
      return "Phase-Flapping Cadence";
    case "heartbeat_staleness":
      return "Heartbeat & Telemetry Freshness";
    case "anomalous_dwell":
      return "Dwell Interval Adherence";
    default:
      return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }
}

export const SignalHealthPanel: React.FC<SignalHealthPanelProps> = ({
  intersectionId,
  className = "",
}) => {
  const [expandedSignalId, setExpandedSignalId] = useState<number | null>(null);

  const queryParams = intersectionId ? { intersection_id: intersectionId } : undefined;

  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useApiQuery<SignalHealthListResponse>({
    queryKey: ["signals-health", intersectionId ?? "all"],
    endpoint: "/signals/health",
    params: queryParams,
  });

  const toggleExpand = (signalId: number) => {
    setExpandedSignalId((prev) => (prev === signalId ? null : signalId));
  };

  const items = data?.items ?? [];

  return (
    <Card className={`p-4 sm:p-5 space-y-4 bg-surface/90 border-white/10 ${className}`}>
      {/* --- Panel Header --- */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-white/10 pb-3">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base sm:text-lg font-display font-semibold text-text flex items-center gap-2">
              <Activity className="w-4 h-4 text-accent" />
              Signal Predictive Maintenance & Health
            </h2>
            <Badge variant="teal" dot>
              Heuristic Model
            </Badge>
          </div>
          <p className="text-xs text-muted">
            Heuristic & statistical risk scoring (0–100) evaluating phase-flapping rate, heartbeat staleness, and dwell anomalies. Not a physics failure model.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {data && (
            <div className="hidden md:flex items-center gap-2 text-xs">
              <Badge variant="success">{data.healthy_count} Healthy</Badge>
              <Badge variant="amber">{data.degraded_count} Degraded</Badge>
              <Badge variant="danger">{data.at_risk_count} At-Risk</Badge>
            </div>
          )}
          <Button
            variant="secondary"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
            className="text-xs cursor-pointer"
            title="Refresh signal health evaluations"
          >
            <RefreshCw className={`w-3.5 h-3.5 mr-1 ${isFetching ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* --- Body States --- */}
      {isLoading && (
        <div className="py-8 flex justify-center">
          <LoadingSpinner label="Evaluating signal telemetry health scores..." />
        </div>
      )}

      {isError && (
        <ErrorState
          title="Failed to Load Signal Health"
          message={error?.message || "Could not retrieve signal health evaluations from backend service."}
          onRetry={() => refetch()}
        />
      )}

      {!isLoading && !isError && items.length === 0 && (
        <EmptyState
          title="No Signal Hardware Monitored"
          description={
            intersectionId
              ? `No active signal controllers recorded for junction #${intersectionId}.`
              : "No physical signal controllers currently registered across the network."
          }
        />
      )}

      {!isLoading && !isError && items.length > 0 && (
        <div className="space-y-3">
          {items.map((item) => {
            const isExpanded = expandedSignalId === item.signal_id;
            const badgeVariant = getBandBadgeVariant(item.status_band);

            return (
              <div
                key={item.signal_id}
                className="rounded-xl border border-white/10 bg-surface/50 p-3.5 hover:border-white/20 transition-colors space-y-3"
              >
                {/* --- Row Header --- */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-sm font-semibold text-text">
                      {item.signal_code}
                    </span>
                    <span className="text-xs text-muted">
                      Junction #{item.intersection_id}
                    </span>
                    <Badge variant={badgeVariant} dot>
                      {item.status_band}
                    </Badge>
                  </div>

                  <div className="flex items-center gap-3">
                    <div className="flex items-center gap-1.5 text-xs">
                      <span className="text-muted">Health Score:</span>
                      <span
                        className={`font-mono font-bold text-sm ${
                          item.score >= 80
                            ? "text-success"
                            : item.score >= 50
                            ? "text-amber"
                            : "text-danger"
                        }`}
                      >
                        {item.score} / 100
                      </span>
                    </div>

                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => toggleExpand(item.signal_id)}
                      className="text-xs text-muted hover:text-text cursor-pointer p-1.5 h-auto"
                      aria-expanded={isExpanded}
                      aria-label={`${isExpanded ? "Collapse" : "Expand"} factor breakdown for ${item.signal_code}`}
                    >
                      {isExpanded ? (
                        <>
                          Hide Factors
                          <ChevronUp className="w-3.5 h-3.5 ml-1" />
                        </>
                      ) : (
                        <>
                          View Factors
                          <ChevronDown className="w-3.5 h-3.5 ml-1" />
                        </>
                      )}
                    </Button>
                  </div>
                </div>

                {/* --- Concise Explanation --- */}
                <p className="text-xs text-muted leading-relaxed">
                  {item.explanation}
                </p>

                {/* --- Expandable Factor Breakdown --- */}
                {isExpanded && (
                  <div className="mt-3 pt-3 border-t border-white/10 space-y-2.5 animate-in fade-in duration-200">
                    <div className="flex items-center justify-between text-[11px] text-muted">
                      <span className="font-semibold uppercase tracking-wider">
                        Contributing Risk Factors & Weights
                      </span>
                      <span className="font-mono text-[10px]">
                        Provenance: {item.provenance}
                      </span>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                      {item.factors.map((factor) => {
                        const hasPenalty = factor.penalty > 0;

                        return (
                          <div
                            key={factor.name}
                            className={`p-2.5 rounded-lg border text-xs ${
                              factor.status === "critical"
                                ? "bg-danger/10 border-danger/30 text-danger"
                                : factor.status === "warning"
                                ? "bg-amber/10 border-amber/30 text-amber"
                                : "bg-white/5 border-white/10 text-muted"
                            }`}
                          >
                            <div className="flex items-center justify-between mb-1">
                              <span className="font-semibold text-text">
                                {getFactorLabel(factor.name)}
                              </span>
                              <div className="flex items-center gap-1.5 font-mono text-[11px]">
                                <span>Weight: {Math.round(factor.weight * 100)}%</span>
                                {hasPenalty ? (
                                  <span className="text-danger font-bold">
                                    -{factor.penalty} pts
                                  </span>
                                ) : (
                                  <span className="text-success font-medium">
                                    0 pts
                                  </span>
                                )}
                              </div>
                            </div>
                            <p className="text-[11px] text-muted/90 leading-tight">
                              {factor.description}
                            </p>
                          </div>
                        );
                      })}
                    </div>

                    <div className="flex items-center gap-1.5 text-[10px] text-muted/70 italic pt-1">
                      <Info className="w-3 h-3 text-muted/60" />
                      Rule-based statistical evaluation. Factors contribute deductions from a 100-point healthy baseline.
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
};
