"use client";

import React, { useState, useMemo, useEffect } from "react";
import {
  BrainCircuit,
  SlidersHorizontal,
  Filter,
  RefreshCw,
  Clock,
  CheckCircle2,
  AlertTriangle,
  RotateCcw,
  ShieldCheck,
  ChevronRight,
  ChevronLeft,
  X,
  ExternalLink,
  Cpu,
  Layers,
  ArrowRight,
  FileCode,
  AlertOctagon,
  Eye,
  Info,
} from "lucide-react";
import Link from "next/link";
import { useApiQuery } from "@/lib/use-api";
import { Card } from "@/components/ui/Card";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import {
  formatDateTime,
  formatRelativeTime,
  formatNumber,
  formatPercent,
  formatSpeed,
  formatQueueLength,
} from "@/lib/format";

// --- Domain Interfaces matching backend schemas ---

interface TrafficStateSnapshot {
  intersection_id: number;
  vehicle_count: number;
  density: number;
  queue_length: number;
  occupancy: number;
  avg_speed_kmh?: number | null;
  incident_count: number;
  active_emergency: boolean;
  observed_signal_state?: string | null;
  current_phase_name?: string | null;
  current_green_elapsed_s?: number | null;
  telemetry_age_s: number;
  source: string;
}

interface PredictedStateSnapshot {
  congestion: number;
  volume: number;
  queue_growth: number;
  horizon_minutes: number;
  model_version?: string | null;
  confidence?: number | null;
}

interface DecisionPayload {
  confidence?: number | null;
  reason?: string;
  expected_impact?: string;
  affected_signal_ids?: number[];
  affected_route?: Record<string, unknown> | null;
  model_version?: string | null;
  current?: TrafficStateSnapshot;
  predicted?: PredictedStateSnapshot | null;
  is_recommendation?: boolean;
  decided_by_user_id?: number | null;
  action?: string;
  [key: string]: unknown;
}

export interface AIDecisionItem {
  id: number;
  prediction_id?: number | null;
  intersection_id?: number | null;
  decision_type: string;
  payload: DecisionPayload;
  status: "proposed" | "applied" | "reverted" | string;
  applied_by?: number | null;
  applied_at?: string | null;
  rationale?: string | null;
  created_at: string;
  updated_at: string;
}

interface PaginatedAIDecisions {
  items: AIDecisionItem[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

interface JunctionItem {
  id: number;
  name: string;
  code: string;
  status: string;
  city?: string | null;
  zone?: string | null;
}

interface PaginatedJunctions {
  items: JunctionItem[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

// Helpers for badges and formatting

function getDecisionTypeBadge(type: string): {
  variant: BadgeVariant;
  label: string;
} {
  const norm = type.toUpperCase();
  switch (norm) {
    case "PRIORITIZE_EMERGENCY":
      return { variant: "danger", label: "Emergency Preemption" };
    case "ACTIVATE_GREEN_CORRIDOR":
      return { variant: "amber", label: "Green Corridor" };
    case "EXTEND_GREEN":
      return { variant: "teal", label: "Extend Green" };
    case "REDUCE_GREEN":
      return { variant: "teal", label: "Reduce Green" };
    case "CHANGE_PHASE":
      return { variant: "teal", label: "Change Phase" };
    case "REROUTE_TRAFFIC":
      return { variant: "amber", label: "Reroute Traffic" };
    case "NO_ACTION":
      return { variant: "muted", label: "Hold / No Action" };
    case "SIGNAL_TIMING":
      return { variant: "teal", label: "Signal Timing" };
    case "ROUTE_ADVISORY":
      return { variant: "amber", label: "Route Advisory" };
    case "ALERT":
      return { variant: "danger", label: "Safety Alert" };
    default:
      return {
        variant: "muted",
        label: type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      };
  }
}

function getStatusBadge(status: string): {
  variant: BadgeVariant;
  label: string;
} {
  switch (status.toLowerCase()) {
    case "proposed":
      return { variant: "amber", label: "PROPOSED" };
    case "applied":
      return { variant: "success", label: "APPLIED" };
    case "reverted":
      return { variant: "danger", label: "REVERTED" };
    default:
      return { variant: "muted", label: status.toUpperCase() };
  }
}

export default function DecisionsPage() {
  // Query Filters & Pagination State
  const [selectedJunctionId, setSelectedJunctionId] = useState<string>("all");
  const [selectedType, setSelectedType] = useState<string>("all");
  const [selectedStatus, setSelectedStatus] = useState<string>("all");
  const [page, setPage] = useState<number>(1);
  const perPage = 15;

  // Drawer detail view state
  const [selectedDecision, setSelectedDecision] = useState<AIDecisionItem | null>(null);

  // 1. Fetch Junctions for dropdown filter
  const { data: junctionsData } = useApiQuery<PaginatedJunctions>({
    queryKey: ["junctions-list-decisions"],
    endpoint: "/junctions",
    params: { per_page: 100 },
    queryOptions: {
      staleTime: 60000,
    },
  });

  const junctionMap = useMemo(() => {
    const map = new Map<number, JunctionItem>();
    junctionsData?.items?.forEach((j) => map.set(j.id, j));
    return map;
  }, [junctionsData]);

  // Reset to page 1 whenever filters change
  const handleFilterChange = (
    setter: React.Dispatch<React.SetStateAction<string>>,
    value: string
  ) => {
    setter(value);
    setPage(1);
  };

  // 2. Fetch Paginated Decisions
  const queryParams = useMemo(() => {
    const params: Record<string, string | number> = {
      page,
      per_page: perPage,
    };
    if (selectedJunctionId !== "all") {
      params.intersection_id = Number(selectedJunctionId);
    }
    if (selectedType !== "all") {
      params.decision_type = selectedType;
    }
    if (selectedStatus !== "all") {
      params.status = selectedStatus;
    }
    return params;
  }, [page, perPage, selectedJunctionId, selectedType, selectedStatus]);

  const {
    data: decisionsData,
    isLoading: decisionsLoading,
    isError: decisionsIsError,
    error: decisionsError,
    refetch: refetchDecisions,
  } = useApiQuery<PaginatedAIDecisions>({
    queryKey: [
      "ai-decisions-history",
      page,
      perPage,
      selectedJunctionId,
      selectedType,
      selectedStatus,
    ],
    endpoint: "/ai-decisions",
    params: queryParams,
    queryOptions: {
      refetchInterval: 30000,
    },
  });

  // Handle escape key to close drawer
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && selectedDecision) {
        setSelectedDecision(null);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedDecision]);

  // Overall offline handling
  const isNetworkOffline =
    decisionsIsError && !decisionsData && decisionsError?.status === 0;

  if (isNetworkOffline) {
    return (
      <div className="max-w-7xl mx-auto space-y-6">
        <ErrorState
          title="Decision Audit Daemon Unreachable"
          message="Failed to establish a network connection to /api/v1/ai-decisions. Verify backend service availability on port 8000."
          onRetry={() => refetchDecisions()}
          retryText="Retry Connection"
        />
      </div>
    );
  }

  const items = decisionsData?.items || [];
  const totalItems = decisionsData?.total || 0;
  const totalPages = decisionsData?.pages || 1;

  const hasActiveFilters =
    selectedJunctionId !== "all" ||
    selectedType !== "all" ||
    selectedStatus !== "all";

  const handleResetFilters = () => {
    setSelectedJunctionId("all");
    setSelectedType("all");
    setSelectedStatus("all");
    setPage(1);
  };

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5 mb-1.5 flex-wrap">
            <h1 className="text-2xl sm:text-3xl font-display font-bold text-text tracking-tight">
              AI Decision Audit History
            </h1>
            <Badge variant="teal" dot>
              Autonomous Policy Log
            </Badge>
            <Badge variant="muted" className="font-mono text-xs">
              Read-Only
            </Badge>
          </div>
          <p className="text-xs sm:text-sm text-muted max-w-2xl leading-relaxed">
            Supervisory audit log of reinforcement policy proposals, emergency preemption directives,
            signal timing modifications, and route advisories.
          </p>
        </div>

        <div className="flex items-center gap-3 self-start md:self-auto flex-wrap">
          <Button
            href="/control"
            variant="secondary"
            size="sm"
            className="gap-2 border-accent/30 hover:border-accent text-accent"
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
            <span>Traffic Control Center</span>
          </Button>

          <Button
            variant="secondary"
            size="sm"
            onClick={() => refetchDecisions()}
            disabled={decisionsLoading}
            className="gap-1.5"
          >
            <RefreshCw
              className={`w-3.5 h-3.5 ${decisionsLoading ? "animate-spin" : ""}`}
            />
            <span className="hidden sm:inline">Refresh</span>
          </Button>
        </div>
      </div>

      {/* Audit Banner Note */}
      <Card className="p-4 sm:p-5 border-white/10 bg-surface/80 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-xs">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-surface/80 border border-white/10 flex items-center justify-center text-accent flex-shrink-0">
            <ShieldCheck className="w-4 h-4" />
          </div>
          <div>
            <div className="font-semibold text-text">
              Immutable Supervisory Audit Surface
            </div>
            <div className="text-muted text-[11px] mt-0.5">
              This log records all advisory proposals emitted by the policy engine. To approve, apply,
              or revert active proposals in real time, authorized officers must use the{" "}
              <Link href="/control" className="text-accent underline hover:opacity-80">
                Control Center
              </Link>
              .
            </div>
          </div>
        </div>
        <div className="text-right text-[11px] text-muted font-mono flex-shrink-0 self-end sm:self-auto">
          {totalItems} Decisions Indexed
        </div>
      </Card>

      {/* FILTER CONTROLS BAR */}
      <div className="bg-surface/60 p-4 rounded-2xl border border-white/10 flex flex-col md:flex-row md:items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 text-xs font-medium text-muted uppercase tracking-wider">
          <Filter className="w-3.5 h-3.5 text-accent" />
          <span>Filters:</span>
        </div>

        <div className="flex items-center gap-2.5 flex-wrap flex-1 justify-start md:justify-end">
          {/* Junction Filter */}
          <select
            value={selectedJunctionId}
            onChange={(e) => handleFilterChange(setSelectedJunctionId, e.target.value)}
            className="bg-ink/80 border border-white/15 rounded-xl px-3 py-1.5 text-xs font-medium text-text focus:outline-none focus:border-accent"
          >
            <option value="all">All Junctions</option>
            {junctionsData?.items?.map((j) => (
              <option key={j.id} value={j.id}>
                #{j.id} — {j.name}
              </option>
            ))}
          </select>

          {/* Decision Type Filter */}
          <select
            value={selectedType}
            onChange={(e) => handleFilterChange(setSelectedType, e.target.value)}
            className="bg-ink/80 border border-white/15 rounded-xl px-3 py-1.5 text-xs font-medium text-text focus:outline-none focus:border-accent"
          >
            <option value="all">All Decision Types</option>
            <option value="PRIORITIZE_EMERGENCY">Emergency Preemption</option>
            <option value="ACTIVATE_GREEN_CORRIDOR">Green Corridor</option>
            <option value="EXTEND_GREEN">Extend Green</option>
            <option value="REDUCE_GREEN">Reduce Green</option>
            <option value="CHANGE_PHASE">Change Phase</option>
            <option value="REROUTE_TRAFFIC">Reroute Traffic</option>
            <option value="NO_ACTION">Hold / No Action</option>
            <option value="signal_timing">Signal Timing Advisory</option>
            <option value="route_advisory">Route Advisory</option>
          </select>

          {/* Lifecycle Status Filter */}
          <select
            value={selectedStatus}
            onChange={(e) => handleFilterChange(setSelectedStatus, e.target.value)}
            className="bg-ink/80 border border-white/15 rounded-xl px-3 py-1.5 text-xs font-medium text-text focus:outline-none focus:border-accent"
          >
            <option value="all">All Statuses</option>
            <option value="proposed">Proposed (Pending Review)</option>
            <option value="applied">Applied (Executed)</option>
            <option value="reverted">Reverted (Overridden)</option>
          </select>

          {hasActiveFilters && (
            <button
              onClick={handleResetFilters}
              className="text-xs text-muted hover:text-text flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-white/10 hover:bg-white/5 transition-colors cursor-pointer"
            >
              <RotateCcw className="w-3 h-3" />
              <span>Reset</span>
            </button>
          )}
        </div>
      </div>

      {/* DECISION LOG TABLE & LIST */}
      {decisionsLoading && items.length === 0 ? (
        <Card className="p-12 text-center flex flex-col items-center justify-center min-h-[350px]">
          <LoadingSpinner size="lg" label="Loading decision history audit records..." />
        </Card>
      ) : decisionsIsError ? (
        <ErrorState
          title="Failed to Load Decision Log"
          message={decisionsError?.message || "An unexpected error occurred while fetching decision records."}
          onRetry={() => refetchDecisions()}
        />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<BrainCircuit className="w-8 h-8 text-muted" />}
          title="No Decisions Recorded"
          description={
            hasActiveFilters
              ? "No decision records matched your filter criteria. Try clearing filters to view all entries."
              : "No AI decisions have been generated yet by the policy engine."
          }
          action={
            hasActiveFilters
              ? {
                  label: "Clear Filter Criteria",
                  onClick: handleResetFilters,
                }
              : undefined
          }
        />
      ) : (
        <Card className="border-white/10 bg-surface/70 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-white/10 bg-ink/40 text-muted uppercase tracking-wider text-[11px]">
                  <th className="py-3 px-3.5">ID / Timestamp</th>
                  <th className="py-3 px-3.5">Target Junction</th>
                  <th className="py-3 px-3.5">Action Directive</th>
                  <th className="py-3 px-3.5">Status</th>
                  <th className="py-3 px-3.5">Operational Explanation</th>
                  <th className="py-3 px-3.5">Ground-Truth Snapshot</th>
                  <th className="py-3 px-3.5">Confidence</th>
                  <th className="py-3 px-3.5 text-right">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {items.map((decision) => {
                  const typeBadge = getDecisionTypeBadge(decision.decision_type);
                  const statusBadge = getStatusBadge(decision.status);
                  const junc = decision.intersection_id
                    ? junctionMap.get(decision.intersection_id)
                    : null;
                  const currentSnap = decision.payload?.current;
                  const explanation =
                    decision.rationale ||
                    decision.payload?.reason ||
                    "Policy optimization based on observed queue pressure.";

                  const conf =
                    decision.payload?.confidence ??
                    decision.payload?.predicted?.confidence ??
                    null;

                  return (
                    <tr
                      key={decision.id}
                      onClick={() => setSelectedDecision(decision)}
                      className="hover:bg-white/5 transition-colors cursor-pointer group"
                    >
                      {/* ID / Timestamp */}
                      <td className="py-3 px-3.5 align-top">
                        <div className="font-mono font-medium text-text flex items-center gap-1">
                          #{decision.id}
                        </div>
                        <div className="text-[11px] text-muted flex items-center gap-1 mt-0.5">
                          <Clock className="w-3 h-3 text-muted/70 flex-shrink-0" />
                          <span>{formatRelativeTime(decision.created_at)}</span>
                        </div>
                        <div className="text-[10px] text-muted/70 font-mono mt-0.5">
                          {formatDateTime(decision.created_at)}
                        </div>
                      </td>

                      {/* Junction */}
                      <td className="py-3 px-3.5 align-top">
                        {junc ? (
                          <div>
                            <span className="font-medium text-text block">
                              {junc.name}
                            </span>
                            <span className="text-[10px] font-mono text-muted">
                              #{junc.id} • {junc.code}
                            </span>
                          </div>
                        ) : decision.intersection_id ? (
                          <span className="font-mono text-muted">
                            Junction #{decision.intersection_id}
                          </span>
                        ) : (
                          <span className="text-muted">Network Wide</span>
                        )}
                      </td>

                      {/* Decision Type */}
                      <td className="py-3 px-3.5 align-top">
                        <Badge variant={typeBadge.variant} className="text-[10px]">
                          {typeBadge.label}
                        </Badge>
                      </td>

                      {/* Status */}
                      <td className="py-3 px-3.5 align-top">
                        <Badge
                          variant={statusBadge.variant}
                          dot
                          className="text-[10px]"
                        >
                          {statusBadge.label}
                        </Badge>
                      </td>

                      {/* Explanation Snippet */}
                      <td className="py-3 px-3.5 align-top max-w-xs">
                        <p className="text-text line-clamp-2 leading-relaxed">
                          {explanation}
                        </p>
                      </td>

                      {/* Input Snapshot Summary */}
                      <td className="py-3 px-3.5 align-top">
                        {currentSnap ? (
                          <div className="flex flex-wrap gap-1 font-mono text-[10px]">
                            <span className="bg-ink/60 border border-white/5 px-1.5 py-0.5 rounded text-accent">
                              {currentSnap.vehicle_count} veh
                            </span>
                            <span className="bg-ink/60 border border-white/5 px-1.5 py-0.5 rounded text-amber">
                              {formatNumber(currentSnap.queue_length, 1)} q
                            </span>
                            {currentSnap.avg_speed_kmh !== null &&
                              currentSnap.avg_speed_kmh !== undefined && (
                                <span className="bg-ink/60 border border-white/5 px-1.5 py-0.5 rounded text-text">
                                  {Math.round(currentSnap.avg_speed_kmh)} km/h
                                </span>
                              )}
                            {currentSnap.active_emergency && (
                              <span className="bg-danger/20 border border-danger/40 px-1.5 py-0.5 rounded text-danger font-semibold">
                                EMERGENCY
                              </span>
                            )}
                          </div>
                        ) : (
                          <span className="text-muted font-mono text-[11px]">—</span>
                        )}
                      </td>

                      {/* Confidence */}
                      <td className="py-3 px-3.5 align-top font-mono">
                        {conf !== null ? (
                          <span className="text-accent font-semibold">
                            {formatPercent(conf * 100, 0)}
                          </span>
                        ) : (
                          <span className="text-muted">—</span>
                        )}
                      </td>

                      {/* Inspect Button */}
                      <td className="py-3 px-3.5 align-top text-right">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedDecision(decision);
                          }}
                          className="inline-flex items-center gap-1 text-xs text-muted group-hover:text-accent transition-colors font-medium cursor-pointer"
                        >
                          <span>Inspect</span>
                          <ChevronRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination Footer */}
          <div className="p-4 border-t border-white/5 bg-ink/30 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
            <div className="text-muted">
              Showing{" "}
              <span className="font-mono text-text font-medium">
                {(page - 1) * perPage + 1}
              </span>{" "}
              to{" "}
              <span className="font-mono text-text font-medium">
                {Math.min(page * perPage, totalItems)}
              </span>{" "}
              of <span className="font-mono text-text font-medium">{totalItems}</span> decisions
            </div>

            <div className="flex items-center gap-1.5">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="gap-1 px-2.5 py-1"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
                <span>Prev</span>
              </Button>

              <span className="px-3 py-1 font-mono text-text text-xs bg-ink/60 rounded-md border border-white/5">
                Page {page} of {totalPages}
              </span>

              <Button
                variant="secondary"
                size="sm"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="gap-1 px-2.5 py-1"
              >
                <span>Next</span>
                <ChevronRight className="w-3.5 h-3.5" />
              </Button>
            </div>
          </div>
        </Card>
      )}

      {/* CLICK-THROUGH DETAIL SLIDE-OVER DRAWER */}
      {selectedDecision && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 overflow-hidden flex justify-end"
        >
          {/* Backdrop */}
          <div
            onClick={() => setSelectedDecision(null)}
            className="fixed inset-0 bg-black/70 backdrop-blur-sm transition-opacity"
          />

          {/* Drawer Body */}
          <div className="relative w-full max-w-2xl bg-ink border-l border-white/10 shadow-2xl z-10 overflow-y-auto flex flex-col h-full animate-in slide-in-from-right duration-200">
            {/* Drawer Header */}
            <div className="p-5 border-b border-white/10 flex items-center justify-between bg-surface/80 sticky top-0 z-20 backdrop-blur-md">
              <div className="flex items-center gap-2.5 flex-wrap">
                <span className="font-mono font-bold text-text text-lg">
                  Decision #{selectedDecision.id}
                </span>
                <Badge
                  variant={getDecisionTypeBadge(selectedDecision.decision_type).variant}
                  className="text-xs"
                >
                  {getDecisionTypeBadge(selectedDecision.decision_type).label}
                </Badge>
                <Badge
                  variant={getStatusBadge(selectedDecision.status).variant}
                  dot
                  className="text-xs"
                >
                  {getStatusBadge(selectedDecision.status).label}
                </Badge>
              </div>

              <button
                type="button"
                onClick={() => setSelectedDecision(null)}
                className="w-8 h-8 rounded-lg bg-surface hover:bg-white/10 border border-white/10 flex items-center justify-center text-muted hover:text-text transition-colors cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Drawer Content */}
            <div className="p-6 space-y-6 flex-1 text-xs sm:text-sm">
              {/* Section 1: Rationale & Expected Impact */}
              <div className="space-y-3">
                <h3 className="font-display font-semibold text-text text-sm uppercase tracking-wider text-muted">
                  Operational Justification
                </h3>
                <Card className="p-4 border-white/10 bg-surface/60 space-y-3">
                  <div>
                    <div className="text-xs text-muted mb-1 font-medium">
                      Algorithmic Explanation:
                    </div>
                    <p className="text-text leading-relaxed text-sm">
                      {selectedDecision.rationale ||
                        selectedDecision.payload?.reason ||
                        "Autonomous policy evaluation based on stop-bar queue pressure and approach velocity."}
                    </p>
                  </div>

                  {selectedDecision.payload?.expected_impact && (
                    <div className="border-t border-white/5 pt-2.5">
                      <div className="text-xs text-accent font-medium mb-1">
                        Expected Traffic Impact:
                      </div>
                      <p className="text-text/90 leading-relaxed text-xs">
                        {selectedDecision.payload.expected_impact}
                      </p>
                    </div>
                  )}

                  {selectedDecision.payload?.confidence !== undefined &&
                    selectedDecision.payload?.confidence !== null && (
                      <div className="border-t border-white/5 pt-2.5 flex items-center justify-between text-xs">
                        <span className="text-muted">Policy Engine Confidence:</span>
                        <span className="font-mono text-accent font-bold">
                          {formatPercent(selectedDecision.payload.confidence * 100, 1)}
                        </span>
                      </div>
                    )}
                </Card>
              </div>

              {/* Section 2: Input Ground-Truth Snapshot */}
              {selectedDecision.payload?.current && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="font-display font-semibold text-text text-sm uppercase tracking-wider text-muted">
                      Ground-Truth Input Telemetry
                    </h3>
                    <Badge variant="muted" className="text-[10px] font-mono">
                      Source: {selectedDecision.payload.current.source}
                    </Badge>
                  </div>

                  <Card className="p-4 border-white/10 bg-surface/60">
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 font-mono text-xs">
                      <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                        <div className="text-[10px] text-muted uppercase font-sans mb-0.5">
                          Vehicular Count
                        </div>
                        <div className="text-text font-bold text-sm">
                          {selectedDecision.payload.current.vehicle_count} veh
                        </div>
                      </div>

                      <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                        <div className="text-[10px] text-muted uppercase font-sans mb-0.5">
                          Stop-Bar Queue
                        </div>
                        <div className="text-amber font-bold text-sm">
                          {formatNumber(selectedDecision.payload.current.queue_length, 1)} veh
                        </div>
                      </div>

                      <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                        <div className="text-[10px] text-muted uppercase font-sans mb-0.5">
                          Traffic Density
                        </div>
                        <div className="text-text font-bold text-sm">
                          {formatNumber(selectedDecision.payload.current.density, 1)}%
                        </div>
                      </div>

                      <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                        <div className="text-[10px] text-muted uppercase font-sans mb-0.5">
                          Mean Velocity
                        </div>
                        <div className="text-text font-bold text-sm">
                          {formatSpeed(selectedDecision.payload.current.avg_speed_kmh)}
                        </div>
                      </div>

                      <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                        <div className="text-[10px] text-muted uppercase font-sans mb-0.5">
                          Approach Occupancy
                        </div>
                        <div className="text-text font-bold text-sm">
                          {formatPercent(selectedDecision.payload.current.occupancy * 100, 1)}
                        </div>
                      </div>

                      <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                        <div className="text-[10px] text-muted uppercase font-sans mb-0.5">
                          Signal State
                        </div>
                        <div className="text-accent font-bold text-sm capitalize">
                          {selectedDecision.payload.current.observed_signal_state || "Unobserved"}
                        </div>
                      </div>
                    </div>

                    {selectedDecision.payload.current.active_emergency && (
                      <div className="mt-3 p-2.5 rounded-lg bg-danger/15 border border-danger/30 text-danger text-xs flex items-center gap-2 font-sans font-semibold">
                        <AlertOctagon className="w-4 h-4 flex-shrink-0" />
                        <span>Active emergency vehicle transit detected within junction approach buffer.</span>
                      </div>
                    )}
                  </Card>
                </div>
              )}

              {/* Section 3: Predictive Horizon Context (if present) */}
              {selectedDecision.payload?.predicted && (
                <div className="space-y-3">
                  <h3 className="font-display font-semibold text-text text-sm uppercase tracking-wider text-muted">
                    Predictive Model Context
                  </h3>
                  <Card className="p-4 border-white/10 bg-surface/60">
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 font-mono text-xs">
                      <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                        <div className="text-[10px] text-muted uppercase font-sans mb-0.5">
                          Forecast Congestion
                        </div>
                        <div className="text-amber font-bold text-sm">
                          {formatPercent(selectedDecision.payload.predicted.congestion, 1)}
                        </div>
                      </div>

                      <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                        <div className="text-[10px] text-muted uppercase font-sans mb-0.5">
                          Forecast Volume
                        </div>
                        <div className="text-accent font-bold text-sm">
                          {formatNumber(selectedDecision.payload.predicted.volume)} veh
                        </div>
                      </div>

                      <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                        <div className="text-[10px] text-muted uppercase font-sans mb-0.5">
                          Queue Growth
                        </div>
                        <div className="text-text font-bold text-sm">
                          +{formatNumber(selectedDecision.payload.predicted.queue_growth, 1)}
                        </div>
                      </div>

                      <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                        <div className="text-[10px] text-muted uppercase font-sans mb-0.5">
                          Lookahead Horizon
                        </div>
                        <div className="text-text font-bold text-sm">
                          {selectedDecision.payload.predicted.horizon_minutes} mins
                        </div>
                      </div>
                    </div>
                  </Card>
                </div>
              )}

              {/* Section 4: Affected Infrastructure */}
              {selectedDecision.payload?.affected_signal_ids &&
                selectedDecision.payload.affected_signal_ids.length > 0 && (
                  <div className="space-y-2">
                    <h3 className="font-display font-semibold text-text text-sm uppercase tracking-wider text-muted">
                      Target Signal Controllers
                    </h3>
                    <div className="flex flex-wrap gap-2">
                      {selectedDecision.payload.affected_signal_ids.map((id) => (
                        <Badge key={id} variant="teal" className="font-mono text-xs">
                          Signal Controller #{id}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

              {/* Section 5: Audit Lifecycle History */}
              <div className="space-y-3">
                <h3 className="font-display font-semibold text-text text-sm uppercase tracking-wider text-muted">
                  Lifecycle State Audit
                </h3>
                <Card className="p-4 border-white/10 bg-surface/60 space-y-2 text-xs font-mono">
                  <div className="flex items-center justify-between py-1 border-b border-white/5">
                    <span className="text-muted font-sans">Created / Proposed:</span>
                    <span className="text-text">{formatDateTime(selectedDecision.created_at)}</span>
                  </div>

                  <div className="flex items-center justify-between py-1 border-b border-white/5">
                    <span className="text-muted font-sans">Current Status:</span>
                    <Badge variant={getStatusBadge(selectedDecision.status).variant} className="text-[10px]">
                      {selectedDecision.status.toUpperCase()}
                    </Badge>
                  </div>

                  {selectedDecision.applied_at && (
                    <div className="flex items-center justify-between py-1 border-b border-white/5">
                      <span className="text-muted font-sans">Applied At:</span>
                      <span className="text-success">{formatDateTime(selectedDecision.applied_at)}</span>
                    </div>
                  )}

                  {selectedDecision.applied_by && (
                    <div className="flex items-center justify-between py-1 border-b border-white/5">
                      <span className="text-muted font-sans">Approved / Applied By:</span>
                      <span className="text-text font-semibold">Operator User #{selectedDecision.applied_by}</span>
                    </div>
                  )}

                  <div className="flex items-center justify-between py-1">
                    <span className="text-muted font-sans">Advisory Safety Guarantee:</span>
                    <span className="text-accent font-sans">is_recommendation = true</span>
                  </div>
                </Card>
              </div>

              {/* Section 6: Raw JSON Inspection */}
              <div className="space-y-2">
                <details className="group border border-white/10 rounded-xl bg-ink/40 p-3">
                  <summary className="flex items-center justify-between text-xs font-mono text-muted cursor-pointer hover:text-text select-none">
                    <span className="flex items-center gap-1.5">
                      <FileCode className="w-3.5 h-3.5" />
                      <span>Inspect Raw Decision JSON Payload</span>
                    </span>
                    <span className="text-[10px] group-open:rotate-90 transition-transform">▶</span>
                  </summary>
                  <pre className="mt-3 p-3 rounded-lg bg-ink/90 border border-white/5 text-[11px] font-mono text-muted overflow-x-auto leading-relaxed">
                    {JSON.stringify(
                      {
                        id: selectedDecision.id,
                        decision_type: selectedDecision.decision_type,
                        status: selectedDecision.status,
                        intersection_id: selectedDecision.intersection_id,
                        rationale: selectedDecision.rationale,
                        created_at: selectedDecision.created_at,
                        payload: selectedDecision.payload,
                      },
                      null,
                      2
                    )}
                  </pre>
                </details>
              </div>
            </div>

            {/* Drawer Footer */}
            <div className="p-4 border-t border-white/10 bg-surface/80 sticky bottom-0 flex items-center justify-between gap-3 backdrop-blur-md">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setSelectedDecision(null)}
              >
                Close
              </Button>

              <Button
                href="/control"
                variant="primary"
                size="sm"
                className="gap-1.5"
              >
                <span>Navigate to Control Center</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
