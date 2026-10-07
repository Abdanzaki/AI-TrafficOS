"use client";

import React, { useState, useMemo, useEffect } from "react";
import {
  SlidersHorizontal,
  BrainCircuit,
  ShieldCheck,
  ShieldAlert,
  Activity,
  CheckCircle2,
  AlertTriangle,
  RotateCcw,
  Play,
  Siren,
  Clock,
  RefreshCw,
  Eye,
  ChevronDown,
  Layers,
  Sparkles,
  ArrowRight,
  TrendingDown,
  Timer,
  Check,
  X,
  FileText,
  Zap,
  Cpu,
  BarChart2,
  GitCompare,
  HelpCircle,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth";
import { useApiQuery, useApiMutation } from "@/lib/use-api";
import { Card } from "@/components/ui/Card";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { RequireRole } from "@/components/RequireRole";
import {
  formatDateTime,
  formatSeconds,
  formatPercent,
  formatNumber,
  formatQueueLength,
  formatSpeed,
} from "@/lib/format";

// --- Domain Interfaces Matching Backend Schemas ---

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

interface LatestDecisionSummary {
  id: number | null;
  action: string;
  created_at: string;
  reason: string | null;
}

interface LatestPredictionSummary {
  congestion: number | null;
  model_version: string | null;
  predicted_for: string | null;
  confidence: number | null;
}

interface JunctionControlStatusResponse {
  intersection_id: number;
  latest_telemetry_age_s: number | null;
  current_observed_signal_state: string | null;
  open_incidents_count: number;
  active_emergency: boolean;
  latest_decision: LatestDecisionSummary | null;
  latest_prediction: LatestPredictionSummary | null;
}

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
  model_version?: string | null;
  current?: TrafficStateSnapshot;
  predicted?: PredictedStateSnapshot | null;
  is_recommendation?: boolean;
  [key: string]: unknown;
}

export interface DecisionItemResponse {
  id: number;
  intersection_id: number | null;
  decision_type: string;
  payload: DecisionPayload;
  status: string; // "proposed" | "applied" | "reverted"
  applied_by: number | null;
  applied_at: string | null;
  rationale: string | null;
  created_at: string;
  updated_at: string;
}

interface PaginatedDecisionsResponse {
  items: DecisionItemResponse[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

interface CorridorSignalAction {
  intersection_id: number;
  signal_id: number | null;
  action: string;
  duration_seconds: number;
  reason: string;
}

interface GreenCorridorPlan {
  corridor_id: string;
  path: number[];
  signal_actions: CorridorSignalAction[];
  estimated_minutes: number;
  from_intersection_id: number;
  to_intersection_id: number;
}

interface EmergencyPrioritizeResponse {
  decision_id: number;
  corridor_plan: GreenCorridorPlan;
  affected_intersection_ids: number[];
  is_recommendation: boolean;
}

interface EmergencyRestoreResponse {
  decision_id: number;
  emergency_event_id: number;
  action: string;
  reason: string;
  affected_signal_ids: number[];
  is_recommendation: boolean;
}

interface EmergencyEventItem {
  id: number;
  vehicle_id: string;
  vehicle_type: string;
  priority: number;
  status: string; // "active" | "dispatched" | "on_scene" | "resolved"
  origin_lat?: number | null;
  origin_lon?: number | null;
  dest_lat?: number | null;
  dest_lon?: number | null;
  detected_at: string;
}

interface PaginatedEmergencyEvents {
  items: EmergencyEventItem[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

interface SimulationResultApproach {
  approach_id: string;
  total_wait_veh_min: number;
  avg_queue_veh: number;
  max_queue_veh: number;
  throughput_veh: number;
  residual_queue_veh: number;
}

interface SimulationResultData {
  total_wait_veh_min: number;
  avg_queue_veh: number;
  max_queue_veh: number;
  throughput_veh: number;
  residual_queue_veh: number;
  plan_digest: string;
  horizon_minutes: number;
  notes: string[];
}

interface PlanComparisonResponse {
  current_result: SimulationResultData;
  proposed_result: SimulationResultData;
  delta_wait: number;
  delta_avg_queue: number;
  delta_throughput: number;
  verdict: "proposed_better" | "current_better" | "equivalent" | string;
}

// --- Helper Functions ---

function getDecisionTypeBadge(decisionType: string): {
  badgeVariant: BadgeVariant;
  label: string;
  bgClass: string;
} {
  const norm = decisionType.toUpperCase().trim();
  switch (norm) {
    case "EXTEND_GREEN":
      return {
        badgeVariant: "teal",
        label: "EXTEND GREEN",
        bgClass: "bg-teal-500/15 text-teal-400 border-teal-500/30",
      };
    case "EARLY_GREEN":
      return {
        badgeVariant: "teal",
        label: "EARLY GREEN",
        bgClass: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
      };
    case "HOLD_RED":
      return {
        badgeVariant: "danger",
        label: "HOLD RED",
        bgClass: "bg-rose-500/15 text-rose-400 border-rose-500/30",
      };
    case "TRUNCATE_GREEN":
      return {
        badgeVariant: "amber",
        label: "TRUNCATE GREEN",
        bgClass: "bg-amber-500/15 text-amber-400 border-amber-500/30",
      };
    case "COORDINATE_CORRIDOR":
      return {
        badgeVariant: "teal",
        label: "COORDINATE CORRIDOR",
        bgClass: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
      };
    case "EMERGENCY_PREEMPT":
      return {
        badgeVariant: "danger",
        label: "EMERGENCY PREEMPT",
        bgClass: "bg-rose-600/20 text-rose-300 border-rose-500/40",
      };
    case "CYCLE_SPLIT_OPTIMIZE":
      return {
        badgeVariant: "amber",
        label: "CYCLE SPLIT OPTIMIZE",
        bgClass: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
      };
    case "NO_ACTION":
    default:
      return {
        badgeVariant: "muted",
        label: norm.replace(/_/g, " "),
        bgClass: "bg-white/10 text-muted border-white/15",
      };
  }
}

function getDecisionStatusBadge(status: string): {
  badgeVariant: BadgeVariant;
  label: string;
} {
  const norm = status.toLowerCase().trim();
  switch (norm) {
    case "applied":
      return { badgeVariant: "success", label: "Applied" };
    case "proposed":
      return { badgeVariant: "amber", label: "Proposed" };
    case "reverted":
      return { badgeVariant: "danger", label: "Reverted" };
    default:
      return { badgeVariant: "muted", label: status };
  }
}

export default function ControlPage() {
  const queryClient = useQueryClient();
  const { user, isAdmin, isOfficer } = useAuth();

  // Navigation sub-tab
  const [activeTab, setActiveTab] = useState<"decisions" | "emergency" | "whatif">("decisions");

  // Selected Junction
  const [selectedJunctionId, setSelectedJunctionId] = useState<number | null>(null);

  // Decision filter controls
  const [junctionFilter, setJunctionFilter] = useState<"current" | "all">("all");
  const [statusFilter, setStatusFilter] = useState<"all" | "proposed" | "applied" | "reverted">("all");
  const [selectedDecisionId, setSelectedDecisionId] = useState<number | null>(null);

  // Emergency prioritize trigger form state
  const [emergencyEventId, setEmergencyEventId] = useState<number | null>(null);
  const [destJunctionId, setDestJunctionId] = useState<number | null>(null);
  const [prioritizeResult, setPrioritizeResult] = useState<EmergencyPrioritizeResponse | null>(null);
  const [restoreResult, setRestoreResult] = useState<EmergencyRestoreResponse | null>(null);

  // What-If Simulation State
  const [simHorizon, setSimHorizon] = useState<number>(15);
  const [simDt, setSimDt] = useState<number>(5);
  const [simCurrentGreen, setSimCurrentGreen] = useState<number>(30);
  const [simProposedGreen, setSimProposedGreen] = useState<number>(45);
  const [simResult, setSimResult] = useState<PlanComparisonResponse | null>(null);

  // Feedback notifications
  const [feedbackSuccess, setFeedbackSuccess] = useState<string | null>(null);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);

  // --- 1. Fetch Junctions List ---
  const {
    data: junctionsData,
    isLoading: junctionsLoading,
    isError: junctionsIsError,
    error: junctionsError,
    refetch: refetchJunctions,
  } = useApiQuery<PaginatedJunctions>({
    queryKey: ["junctions-list"],
    endpoint: "/junctions",
    params: { per_page: 100 },
    queryOptions: {
      refetchInterval: 60000,
    },
  });

  // Default selected junction
  useEffect(() => {
    if (!selectedJunctionId && junctionsData?.items && junctionsData.items.length > 0) {
      setSelectedJunctionId(junctionsData.items[0].id);
      setDestJunctionId(junctionsData.items[1]?.id || junctionsData.items[0].id);
    }
  }, [junctionsData, selectedJunctionId]);

  const selectedJunction = useMemo(() => {
    return junctionsData?.items.find((j) => j.id === selectedJunctionId);
  }, [junctionsData, selectedJunctionId]);

  // --- 2. Fetch Real-time Junction Control Status ---
  const {
    data: controlStatus,
    isLoading: statusLoading,
    isError: statusIsError,
    error: statusError,
    refetch: refetchControlStatus,
  } = useApiQuery<JunctionControlStatusResponse>({
    queryKey: ["junction-control-status", selectedJunctionId],
    endpoint: selectedJunctionId
      ? `/control/junctions/${selectedJunctionId}/control-status`
      : "/control/junctions/0/control-status",
    queryOptions: {
      enabled: selectedJunctionId !== null,
      refetchInterval: 10000,
    },
  });

  // --- 3. Fetch Decisions List ---
  const decisionsParams = useMemo(() => {
    const params: Record<string, string | number> = { per_page: 50 };
    if (junctionFilter === "current" && selectedJunctionId) {
      params.intersection_id = selectedJunctionId;
    }
    return params;
  }, [junctionFilter, selectedJunctionId]);

  const {
    data: decisionsData,
    isLoading: decisionsLoading,
    isError: decisionsIsError,
    error: decisionsError,
    refetch: refetchDecisions,
  } = useApiQuery<PaginatedDecisionsResponse>({
    queryKey: ["control-decisions", junctionFilter, selectedJunctionId],
    endpoint: "/control/decisions",
    params: decisionsParams,
    queryOptions: {
      refetchInterval: 10000,
    },
  });

  // Filter decisions by status on client
  const filteredDecisions = useMemo(() => {
    if (!decisionsData?.items) return [];
    if (statusFilter === "all") return decisionsData.items;
    return decisionsData.items.filter((d) => d.status.toLowerCase() === statusFilter);
  }, [decisionsData, statusFilter]);

  // Select first decision by default if none selected
  useEffect(() => {
    if (filteredDecisions.length > 0) {
      const exists = filteredDecisions.some((d) => d.id === selectedDecisionId);
      if (!selectedDecisionId || !exists) {
        setSelectedDecisionId(filteredDecisions[0].id);
      }
    } else {
      setSelectedDecisionId(null);
    }
  }, [filteredDecisions, selectedDecisionId]);

  const selectedDecision = useMemo(() => {
    return filteredDecisions.find((d) => d.id === selectedDecisionId);
  }, [filteredDecisions, selectedDecisionId]);

  // --- 4. Fetch Active Emergency Events (for Preemption trigger) ---
  const {
    data: emergencyEventsData,
    isLoading: emergencyEventsLoading,
    refetch: refetchEmergencyEvents,
  } = useApiQuery<PaginatedEmergencyEvents>({
    queryKey: ["emergency-events-active"],
    endpoint: "/emergency-events",
    params: { status: "active", per_page: 50 },
    queryOptions: {
      refetchInterval: 15000,
    },
  });

  useEffect(() => {
    if (!emergencyEventId && emergencyEventsData?.items && emergencyEventsData.items.length > 0) {
      setEmergencyEventId(emergencyEventsData.items[0].id);
    }
  }, [emergencyEventsData, emergencyEventId]);

  // --- 5. Generate Recommendation On-Demand Mutation ---
  const generateRecMutation = useApiMutation<DecisionItemResponse, { intersection_id: number }>({
    endpoint: "/control/recommendations",
    method: "POST",
    mutationOptions: {
      onSuccess: (data) => {
        setFeedbackError(null);
        setFeedbackSuccess(`New supervisory recommendation formulated for junction #${data.intersection_id}: ${data.decision_type || "PROPOSED"}.`);
        queryClient.invalidateQueries({ queryKey: ["control-decisions"] });
        queryClient.invalidateQueries({ queryKey: ["junction-control-status"] });
        if (data.id) {
          setSelectedDecisionId(data.id);
        }
        setTimeout(() => setFeedbackSuccess(null), 6000);
      },
      onError: (err) => {
        setFeedbackSuccess(null);
        setFeedbackError(err.message || "Failed to formulate supervisory recommendation.");
      },
    },
  });

  // --- 6. Apply Decision Mutation (POST /control/decisions/{id}/apply) ---
  const applyDecisionMutation = useApiMutation<DecisionItemResponse, Record<string, never>>({
    endpoint: selectedDecisionId ? `/control/decisions/${selectedDecisionId}/apply` : "/control/decisions/0/apply",
    method: "POST",
    mutationOptions: {
      onSuccess: (data) => {
        setFeedbackError(null);
        setFeedbackSuccess(`Decision #${data.id} (${data.decision_type}) successfully applied. Hardware actuation advisory confirmed.`);
        queryClient.invalidateQueries({ queryKey: ["control-decisions"] });
        queryClient.invalidateQueries({ queryKey: ["junction-control-status"] });
        setTimeout(() => setFeedbackSuccess(null), 6000);
      },
      onError: (err) => {
        setFeedbackSuccess(null);
        setFeedbackError(err.message || "Failed to apply supervisory decision.");
      },
    },
  });

  // --- 7. Revert Decision Mutation (POST /control/decisions/{id}/revert) ---
  const revertDecisionMutation = useApiMutation<DecisionItemResponse, Record<string, never>>({
    endpoint: selectedDecisionId ? `/control/decisions/${selectedDecisionId}/revert` : "/control/decisions/0/revert",
    method: "POST",
    mutationOptions: {
      onSuccess: (data) => {
        setFeedbackError(null);
        setFeedbackSuccess(`Decision #${data.id} (${data.decision_type}) successfully reverted.`);
        queryClient.invalidateQueries({ queryKey: ["control-decisions"] });
        queryClient.invalidateQueries({ queryKey: ["junction-control-status"] });
        setTimeout(() => setFeedbackSuccess(null), 6000);
      },
      onError: (err) => {
        setFeedbackSuccess(null);
        setFeedbackError(err.message || "Failed to revert supervisory decision.");
      },
    },
  });

  // --- 8. Emergency Prioritize Mutation ---
  const emergencyPrioritizeMutation = useApiMutation<
    EmergencyPrioritizeResponse,
    { emergency_event_id: number; destination_intersection_id: number }
  >({
    endpoint: "/control/emergency/prioritize",
    method: "POST",
    mutationOptions: {
      onSuccess: (data) => {
        setFeedbackError(null);
        setPrioritizeResult(data);
        setRestoreResult(null);
        setFeedbackSuccess(`Advisory green corridor preemption activated (Corridor ID: ${data.corridor_plan.corridor_id}).`);
        queryClient.invalidateQueries({ queryKey: ["control-decisions"] });
        queryClient.invalidateQueries({ queryKey: ["emergency-events-active"] });
        setTimeout(() => setFeedbackSuccess(null), 6000);
      },
      onError: (err) => {
        setFeedbackSuccess(null);
        setFeedbackError(err.message || "Emergency green corridor preemption failed.");
      },
    },
  });

  // --- 9. Emergency Restore Mutation ---
  const emergencyRestoreMutation = useApiMutation<
    EmergencyRestoreResponse,
    { emergency_event_id: number }
  >({
    endpoint: "/control/emergency/restore",
    method: "POST",
    mutationOptions: {
      onSuccess: (data) => {
        setFeedbackError(null);
        setRestoreResult(data);
        setPrioritizeResult(null);
        setFeedbackSuccess(`Emergency preemption concluded. Standard cyclic timing restored for event #${data.emergency_event_id}.`);
        queryClient.invalidateQueries({ queryKey: ["control-decisions"] });
        queryClient.invalidateQueries({ queryKey: ["emergency-events-active"] });
        setTimeout(() => setFeedbackSuccess(null), 6000);
      },
      onError: (err) => {
        setFeedbackSuccess(null);
        setFeedbackError(err.message || "Failed to restore emergency corridor.");
      },
    },
  });

  // --- 10. What-If Simulation Mutation ---
  const simulateMutation = useApiMutation<PlanComparisonResponse, Record<string, unknown>>({
    endpoint: "/control/simulate",
    method: "POST",
    mutationOptions: {
      onSuccess: (data) => {
        setFeedbackError(null);
        setSimResult(data);
        setFeedbackSuccess("Macroscopic simulation completed. Comparative plan metrics evaluated.");
        setTimeout(() => setFeedbackSuccess(null), 6000);
      },
      onError: (err) => {
        setFeedbackSuccess(null);
        setFeedbackError(err.message || "Simulation failed. Check plan timings.");
      },
    },
  });

  // Handlers
  const handleTriggerRecommendation = () => {
    if (!selectedJunctionId) return;
    generateRecMutation.mutate({ intersection_id: selectedJunctionId });
  };

  const handleApplyDecision = () => {
    if (!selectedDecisionId) return;
    applyDecisionMutation.mutate({});
  };

  const handleRevertDecision = () => {
    if (!selectedDecisionId) return;
    revertDecisionMutation.mutate({});
  };

  const handleEmergencyPrioritize = (e: React.FormEvent) => {
    e.preventDefault();
    if (!emergencyEventId || !destJunctionId) {
      setFeedbackError("Please select both an active emergency event and a destination junction.");
      return;
    }
    emergencyPrioritizeMutation.mutate({
      emergency_event_id: emergencyEventId,
      destination_intersection_id: destJunctionId,
    });
  };

  const handleEmergencyRestore = () => {
    if (!emergencyEventId) return;
    emergencyRestoreMutation.mutate({
      emergency_event_id: emergencyEventId,
    });
  };

  const handleRunSimulation = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedJunctionId) return;

    // Construct valid macroscopic point-queue test plan
    const payload = {
      intersection_id: selectedJunctionId,
      horizon_minutes: simHorizon,
      dt_seconds: simDt,
      approaches: [
        {
          approach_id: "APP-N",
          queue_veh: 12.0,
          arrival_rate_veh_per_min: 15.0,
          saturation_flow_veh_per_min: 30.0,
          lane_count: 2,
          name: "Northbound Main Arterial",
        },
        {
          approach_id: "APP-E",
          queue_veh: 6.0,
          arrival_rate_veh_per_min: 8.0,
          saturation_flow_veh_per_min: 25.0,
          lane_count: 1,
          name: "Eastbound Cross Street",
        },
      ],
      current_plan: {
        phases: {
          Phase_N: simCurrentGreen,
          Phase_E: 30.0,
        },
        phase_to_approaches: {
          Phase_N: ["APP-N"],
          Phase_E: ["APP-E"],
        },
        yellow_s: 3.0,
        all_red_s: 2.0,
      },
      proposed_plan: {
        phases: {
          Phase_N: simProposedGreen,
          Phase_E: 30.0,
        },
        phase_to_approaches: {
          Phase_N: ["APP-N"],
          Phase_E: ["APP-E"],
        },
        yellow_s: 3.0,
        all_red_s: 2.0,
      },
    };

    simulateMutation.mutate(payload);
  };

  // Full-page error if junctions fail to load (backend offline)
  if (junctionsIsError) {
    return (
      <div className="max-w-7xl mx-auto p-4 sm:p-6 space-y-6">
        <ErrorState
          title="Supervisory Control Service Offline"
          message={junctionsError?.message || "Failed to establish communication with the traffic control daemon."}
          onRetry={refetchJunctions}
          retryText="Reconnect Service"
        />
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-12">
      {/* --- Page Header --- */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-white/10 pb-5">
        <div>
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <h1 className="text-2xl sm:text-3xl font-display font-bold text-text tracking-tight">
              Signal Optimization & Control Recommendations
            </h1>
            <Badge variant="amber" dot>
              Supervisory Engine
            </Badge>
            <Badge variant={isAdmin() || isOfficer() ? "teal" : "muted"}>
              {isAdmin() || isOfficer() ? "Operator Clearance Active" : "Analyst Read-Only"}
            </Badge>
          </div>
          <p className="text-xs sm:text-sm text-muted">
            Advisory decision lifecycle inspection, Webster-inspired signal split optimization, and emergency green wave preemption.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <Button
            variant="primary"
            size="sm"
            onClick={handleTriggerRecommendation}
            disabled={generateRecMutation.isPending || !selectedJunctionId}
            className="text-xs font-medium"
          >
            {generateRecMutation.isPending ? (
              <LoadingSpinner size="sm" label="Evaluating..." />
            ) : (
              <>
                <Sparkles className="w-3.5 h-3.5 mr-1.5" />
                Formulate Recommendation
              </>
            )}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              refetchDecisions();
              refetchControlStatus();
            }}
            className="text-xs font-mono"
          >
            <RefreshCw className="w-3.5 h-3.5 mr-1" />
            Sync
          </Button>
        </div>
      </div>

      {/* --- Feedback Banners --- */}
      {feedbackSuccess && (
        <div className="p-3.5 rounded-xl bg-success/15 border border-success/30 text-success text-xs sm:text-sm flex items-center justify-between shadow-md">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 shrink-0 text-success" />
            <span>{feedbackSuccess}</span>
          </div>
          <button
            onClick={() => setFeedbackSuccess(null)}
            className="text-success/70 hover:text-success text-xs font-mono ml-3 cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {feedbackError && (
        <div className="p-3.5 rounded-xl bg-danger/15 border border-danger/30 text-danger text-xs sm:text-sm flex items-center justify-between shadow-md">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 text-danger" />
            <span>{feedbackError}</span>
          </div>
          <button
            onClick={() => setFeedbackError(null)}
            className="text-danger/70 hover:text-danger text-xs font-mono ml-3 cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* --- Section 1: Junction Selector & Control Telemetry Status --- */}
      <Card className="p-5 sm:p-6 bg-surface border-white/10 space-y-5">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-white/10 pb-4">
          <div className="flex-1 min-w-0">
            <label
              htmlFor="ctrl-junction-select"
              className="block text-xs font-mono uppercase tracking-wider text-muted mb-1.5"
            >
              Target Intersection
            </label>
            <div className="relative max-w-lg">
              {junctionsLoading ? (
                <div className="h-10 rounded-xl bg-ink/60 border border-white/10 flex items-center px-3 gap-2 text-xs text-muted">
                  <LoadingSpinner size="sm" />
                  <span>Loading junctions...</span>
                </div>
              ) : (
                <div className="relative">
                  <select
                    id="ctrl-junction-select"
                    value={selectedJunctionId ?? ""}
                    onChange={(e) => setSelectedJunctionId(Number(e.target.value))}
                    className="w-full h-11 pl-3.5 pr-10 rounded-xl bg-ink/80 border border-white/15 text-text text-sm font-medium focus:outline-none focus:ring-2 focus:ring-accent appearance-none cursor-pointer"
                  >
                    {junctionsData?.items.map((j) => (
                      <option key={j.id} value={j.id} className="bg-ink text-text">
                        [{j.code}] {j.name} ({j.zone || "Zone Central"})
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="w-4 h-4 text-muted absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 text-xs text-muted">
            <ShieldCheck className="w-4 h-4 text-accent" />
            <span>Advisory Supervisory Mode (Field Direct Actuation Safeguarded)</span>
          </div>
        </div>

        {/* Real-time Status Metric Cards */}
        {statusLoading ? (
          <div className="py-6 flex justify-center">
            <LoadingSpinner size="sm" label="Polling real-time control status..." />
          </div>
        ) : statusIsError ? (
          <div className="p-4 rounded-xl bg-ink/60 border border-danger/30 text-xs text-danger flex items-center justify-between">
            <span>Failed to query control status for junction #{selectedJunctionId}.</span>
            <Button variant="ghost" size="sm" onClick={() => refetchControlStatus()}>
              Retry
            </Button>
          </div>
        ) : controlStatus ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
            {/* 1. Telemetry Freshness */}
            <div className="p-4 rounded-xl bg-ink/60 border border-white/10 space-y-1.5">
              <span className="text-[10px] uppercase font-mono tracking-wider text-muted block">
                Telemetry Freshness
              </span>
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-accent" />
                <span className="text-lg font-mono font-bold text-text">
                  {controlStatus.latest_telemetry_age_s !== null
                    ? `${controlStatus.latest_telemetry_age_s.toFixed(1)}s`
                    : "No Data"}
                </span>
              </div>
              <p className="text-[11px] text-muted font-mono">
                {controlStatus.latest_telemetry_age_s !== null &&
                controlStatus.latest_telemetry_age_s > 300 ? (
                  <span className="text-amber-400 font-semibold">Stale (&gt;300s)</span>
                ) : (
                  <span className="text-emerald-400">Live Streaming</span>
                )}
              </p>
            </div>

            {/* 2. Optical Lamp Indication */}
            <div className="p-4 rounded-xl bg-ink/60 border border-white/10 space-y-1.5">
              <span className="text-[10px] uppercase font-mono tracking-wider text-muted block">
                Camera Optical Lamp
              </span>
              <div className="flex items-center gap-2">
                <Eye className="w-4 h-4 text-accent" />
                <span className="text-lg font-mono font-bold uppercase text-text">
                  {controlStatus.current_observed_signal_state || "Unknown"}
                </span>
              </div>
              <p className="text-[11px] text-muted">
                Observed from roadside CCTV
              </p>
            </div>

            {/* 3. Incidents & Emergency */}
            <div className="p-4 rounded-xl bg-ink/60 border border-white/10 space-y-1.5">
              <span className="text-[10px] uppercase font-mono tracking-wider text-muted block">
                Incidents & Emergency
              </span>
              <div className="flex items-center gap-2">
                {controlStatus.active_emergency ? (
                  <Siren className="w-4 h-4 text-rose-400 animate-bounce" />
                ) : (
                  <Activity className="w-4 h-4 text-accent" />
                )}
                <span className="text-lg font-mono font-bold text-text">
                  {controlStatus.open_incidents_count} Open
                </span>
              </div>
              <p className="text-[11px] font-mono">
                {controlStatus.active_emergency ? (
                  <span className="text-rose-400 font-semibold animate-pulse">
                    EMERGENCY NEARBY
                  </span>
                ) : (
                  <span className="text-muted">Standard Traffic Flow</span>
                )}
              </p>
            </div>

            {/* 4. ML Congestion Forecast & Latest Decision */}
            <div className="p-4 rounded-xl bg-ink/60 border border-white/10 space-y-1.5">
              <span className="text-[10px] uppercase font-mono tracking-wider text-muted block">
                Forecast & Latest Action
              </span>
              <div className="flex items-center gap-2">
                <BrainCircuit className="w-4 h-4 text-accent" />
                <span className="text-lg font-mono font-bold text-text">
                  {controlStatus.latest_prediction?.congestion !== null &&
                  controlStatus.latest_prediction?.congestion !== undefined
                    ? `${controlStatus.latest_prediction.congestion.toFixed(0)}% Cong.`
                    : "Calibrating"}
                </span>
              </div>
              <p className="text-[11px] text-muted truncate font-mono">
                {controlStatus.latest_decision
                  ? `Action: ${controlStatus.latest_decision.action}`
                  : "No prior decisions"}
              </p>
            </div>
          </div>
        ) : null}
      </Card>

      {/* --- Section 2: Sub-navigation Tabs --- */}
      <div className="flex items-center gap-2 border-b border-white/10 pb-2">
        <button
          onClick={() => setActiveTab("decisions")}
          className={`px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold transition-all cursor-pointer flex items-center gap-2 ${
            activeTab === "decisions"
              ? "bg-accent text-ink shadow-md shadow-accent/20"
              : "text-muted hover:text-text hover:bg-white/5"
          }`}
        >
          <BrainCircuit className="w-4 h-4" />
          AI Control Decisions ({filteredDecisions.length})
        </button>

        <button
          onClick={() => setActiveTab("emergency")}
          className={`px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold transition-all cursor-pointer flex items-center gap-2 ${
            activeTab === "emergency"
              ? "bg-rose-500 text-white shadow-md shadow-rose-500/20"
              : "text-muted hover:text-text hover:bg-white/5"
          }`}
        >
          <Siren className="w-4 h-4" />
          Emergency Corridor Preemption
        </button>

        <button
          onClick={() => setActiveTab("whatif")}
          className={`px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold transition-all cursor-pointer flex items-center gap-2 ${
            activeTab === "whatif"
              ? "bg-accent text-ink shadow-md shadow-accent/20"
              : "text-muted hover:text-text hover:bg-white/5"
          }`}
        >
          <GitCompare className="w-4 h-4" />
          What-If Plan Simulation
        </button>
      </div>

      {/* --- TAB 1: AI Control Decisions & Supervisory Actions --- */}
      {activeTab === "decisions" && (
        <div className="space-y-6">
          {/* Decision Filter Bar */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-surface/60 p-3 rounded-xl border border-white/10 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-muted font-mono uppercase text-[11px] mr-1">Scope:</span>
              <button
                onClick={() => setJunctionFilter("all")}
                className={`px-2.5 py-1 rounded-lg font-mono transition-colors cursor-pointer ${
                  junctionFilter === "all"
                    ? "bg-white/15 text-text font-bold"
                    : "text-muted hover:text-text"
                }`}
              >
                All Junctions
              </button>
              <button
                onClick={() => setJunctionFilter("current")}
                className={`px-2.5 py-1 rounded-lg font-mono transition-colors cursor-pointer ${
                  junctionFilter === "current"
                    ? "bg-white/15 text-text font-bold"
                    : "text-muted hover:text-text"
                }`}
              >
                Current Junction (#{selectedJunctionId})
              </button>
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-muted font-mono uppercase text-[11px] mr-1">Status:</span>
              {(["all", "proposed", "applied", "reverted"] as const).map((st) => (
                <button
                  key={st}
                  onClick={() => setStatusFilter(st)}
                  className={`px-2.5 py-1 rounded-lg capitalize font-mono transition-colors cursor-pointer ${
                    statusFilter === st
                      ? "bg-accent/20 text-accent border border-accent/30 font-bold"
                      : "text-muted hover:text-text"
                  }`}
                >
                  {st}
                </button>
              ))}
            </div>
          </div>

          {/* Decisions Split: List on Left (7 cols), Selected Detail on Right (5 cols) */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
            {/* Left Column: Decisions List */}
            <div className="lg:col-span-7 space-y-3">
              {decisionsLoading ? (
                <div className="py-16 flex flex-col items-center justify-center">
                  <LoadingSpinner size="md" label="Loading supervisory decision history..." />
                </div>
              ) : decisionsIsError ? (
                <ErrorState
                  title="Failed to Load AI Decisions"
                  message={decisionsError?.message || "Could not retrieve historical advisory control decisions."}
                  onRetry={refetchDecisions}
                />
              ) : filteredDecisions.length === 0 ? (
                <EmptyState
                  icon={<BrainCircuit className="w-8 h-8 text-muted" />}
                  title="No Supervisory Decisions Found"
                  description="No AI control recommendations match the selected filters. Use 'Formulate Recommendation' above to evaluate live conditions."
                />
              ) : (
                filteredDecisions.map((decision) => {
                  const typeBadge = getDecisionTypeBadge(decision.decision_type);
                  const statusBadge = getDecisionStatusBadge(decision.status);
                  const isSelected = selectedDecisionId === decision.id;
                  const conf = decision.payload?.confidence;
                  const reasonText = decision.rationale || decision.payload?.reason || "No operational justification recorded.";

                  return (
                    <div
                      key={decision.id}
                      onClick={() => setSelectedDecisionId(decision.id)}
                      className={`p-4 sm:p-5 rounded-xl border transition-all cursor-pointer relative ${
                        isSelected
                          ? "bg-surface border-accent shadow-lg shadow-accent/5 ring-1 ring-accent"
                          : "bg-surface/70 border-white/10 hover:border-white/20 hover:bg-surface"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3 mb-2.5">
                        <div className="flex flex-wrap items-center gap-2">
                          <span
                            className={`px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold border ${typeBadge.bgClass}`}
                          >
                            {typeBadge.label}
                          </span>
                          <Badge variant={statusBadge.badgeVariant}>
                            {statusBadge.label}
                          </Badge>
                        </div>

                        {conf !== null && conf !== undefined && (
                          <span className="font-mono text-xs text-accent font-semibold bg-accent/10 px-2 py-0.5 rounded border border-accent/20">
                            {formatPercent(conf * 100, 0)} Conf
                          </span>
                        )}
                      </div>

                      {/* Explanation Snippet */}
                      <p className="text-xs sm:text-sm text-text line-clamp-2 leading-relaxed mb-3">
                        {reasonText}
                      </p>

                      <div className="flex flex-wrap items-center justify-between text-[11px] text-muted font-mono pt-2 border-t border-white/5">
                        <div className="flex items-center gap-3">
                          <span>Decision #{decision.id}</span>
                          <span>•</span>
                          <span>
                            Junction #{decision.intersection_id ?? "All"}
                          </span>
                        </div>
                        <div>
                          {formatDateTime(decision.created_at)}
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            {/* Right Column: Selected Decision Detail & Supervisory Apply/Revert Actions */}
            <div className="lg:col-span-5 space-y-6">
              {!selectedDecision ? (
                <Card className="p-8 text-center border-white/10 text-muted text-xs">
                  Select a supervisory decision from the list to view full telemetry snapshot, algorithmic justification, and execute human-in-the-loop approval.
                </Card>
              ) : (
                <Card className="p-5 sm:p-6 bg-surface border-white/10 space-y-5">
                  {/* Detail Header */}
                  <div className="border-b border-white/10 pb-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-mono text-muted uppercase">
                        Decision Detail #{selectedDecision.id}
                      </span>
                      <Badge
                        variant={getDecisionStatusBadge(selectedDecision.status).badgeVariant}
                      >
                        {selectedDecision.status.toUpperCase()}
                      </Badge>
                    </div>
                    <h3 className="text-lg font-display font-bold text-text">
                      {selectedDecision.decision_type.replace(/_/g, " ")}
                    </h3>
                    <span className="text-xs text-muted font-mono block mt-0.5">
                      Target Intersection: #{selectedDecision.intersection_id ?? "All"}
                    </span>
                  </div>

                  {/* Operational Rationale */}
                  <div className="p-3.5 rounded-xl bg-ink/60 border border-white/10 space-y-1.5">
                    <span className="text-[11px] uppercase font-mono tracking-wider text-accent font-semibold flex items-center gap-1.5">
                      <FileText className="w-3.5 h-3.5" />
                      Algorithmic Explanation
                    </span>
                    <p className="text-xs sm:text-sm text-text leading-relaxed">
                      {selectedDecision.rationale ||
                        selectedDecision.payload?.reason ||
                        "Standard supervisory recommendation generated from telemetry threshold evaluation."}
                    </p>
                  </div>

                  {/* Expected Impact */}
                  {selectedDecision.payload?.expected_impact && (
                    <div className="p-3 rounded-xl bg-accent/5 border border-accent/20 space-y-1">
                      <span className="text-[10px] uppercase font-mono tracking-wider text-accent font-semibold">
                        Expected Operational Impact
                      </span>
                      <p className="text-xs text-text">
                        {String(selectedDecision.payload.expected_impact)}
                      </p>
                    </div>
                  )}

                  {/* Telemetry Snapshot Breakdown */}
                  {selectedDecision.payload?.current && (
                    <div className="space-y-2">
                      <span className="text-xs font-mono uppercase text-muted tracking-wider block">
                        Observed Conditions Snapshot
                      </span>
                      <div className="grid grid-cols-2 gap-2 text-xs">
                        <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                          <span className="text-muted block text-[10px] uppercase font-mono">Volume</span>
                          <span className="font-mono font-semibold text-text">
                            {formatNumber(selectedDecision.payload.current.vehicle_count)} veh
                          </span>
                        </div>
                        <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                          <span className="text-muted block text-[10px] uppercase font-mono">Queue Length</span>
                          <span className="font-mono font-semibold text-text">
                            {formatQueueLength(selectedDecision.payload.current.queue_length)}
                          </span>
                        </div>
                        <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                          <span className="text-muted block text-[10px] uppercase font-mono">Approach Density</span>
                          <span className="font-mono font-semibold text-text">
                            {formatNumber(selectedDecision.payload.current.density, 2)}
                          </span>
                        </div>
                        <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                          <span className="text-muted block text-[10px] uppercase font-mono">Avg Speed</span>
                          <span className="font-mono font-semibold text-text">
                            {formatSpeed(selectedDecision.payload.current.avg_speed_kmh)}
                          </span>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* ML Forecast Snapshot */}
                  {selectedDecision.payload?.predicted && (
                    <div className="space-y-2">
                      <span className="text-xs font-mono uppercase text-muted tracking-wider block">
                        ML Horizon Forecast
                      </span>
                      <div className="grid grid-cols-2 gap-2 text-xs">
                        <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                          <span className="text-muted block text-[10px] uppercase font-mono">Predicted Congestion</span>
                          <span className="font-mono font-semibold text-accent">
                            {selectedDecision.payload.predicted.congestion.toFixed(1)}%
                          </span>
                        </div>
                        <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                          <span className="text-muted block text-[10px] uppercase font-mono">Queue Growth</span>
                          <span className="font-mono font-semibold text-text">
                            {selectedDecision.payload.predicted.queue_growth > 0 ? "+" : ""}
                            {selectedDecision.payload.predicted.queue_growth.toFixed(2)} veh/min
                          </span>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Supervisory Actions (Apply & Revert) */}
                  <div className="border-t border-white/10 pt-4 space-y-4">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-mono uppercase font-semibold text-text">
                        Supervisory Action Controls
                      </span>
                      {selectedDecision.applied_by && (
                        <span className="text-[10px] font-mono text-muted">
                          Applied by User #{selectedDecision.applied_by} at {formatDateTime(selectedDecision.applied_at)}
                        </span>
                      )}
                    </div>

                    <RequireRole
                      allowedRoles={["admin", "traffic_officer"]}
                      fallback={
                        <div className="p-4 rounded-xl bg-ink/60 border border-amber/30 text-xs text-amber space-y-1">
                          <div className="flex items-center gap-1.5 font-semibold">
                            <ShieldAlert className="w-4 h-4 shrink-0" />
                            <span>Read-Only Clearance</span>
                          </div>
                          <p className="text-muted pl-5">
                            Applying or reverting advisory recommendations requires clearance role <span className="font-mono text-text">traffic_officer</span> or <span className="font-mono text-text">admin</span>.
                          </p>
                        </div>
                      }
                    >
                      {/* Audit Note */}
                      <div className="p-3 rounded-xl bg-ink/60 border border-white/10 text-[11px] text-muted space-y-1">
                        <div className="flex items-center gap-1.5 text-accent font-semibold font-mono">
                          <ShieldCheck className="w-3.5 h-3.5" />
                          <span>Audit Trail Enforced</span>
                        </div>
                        <p className="leading-relaxed">
                          Applying or reverting this decision transition records your operator identity (#{user?.id} - {user?.email}) in the tamper-evident audit log.
                        </p>
                      </div>

                      {/* Action Dispatch Buttons */}
                      <div className="grid grid-cols-2 gap-3">
                        <Button
                          variant="primary"
                          size="sm"
                          onClick={handleApplyDecision}
                          disabled={
                            selectedDecision.status === "applied" ||
                            applyDecisionMutation.isPending
                          }
                          className="w-full text-xs"
                        >
                          {applyDecisionMutation.isPending ? (
                            <LoadingSpinner size="sm" label="Applying..." />
                          ) : (
                            <>
                              <Check className="w-3.5 h-3.5 mr-1" />
                              Apply Decision
                            </>
                          )}
                        </Button>

                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={handleRevertDecision}
                          disabled={
                            selectedDecision.status === "reverted" ||
                            revertDecisionMutation.isPending
                          }
                          className="w-full text-xs border-danger/30 text-danger hover:border-danger hover:bg-danger/10"
                        >
                          {revertDecisionMutation.isPending ? (
                            <LoadingSpinner size="sm" label="Reverting..." />
                          ) : (
                            <>
                              <RotateCcw className="w-3.5 h-3.5 mr-1" />
                              Revert Decision
                            </>
                          )}
                        </Button>
                      </div>
                    </RequireRole>
                  </div>
                </Card>
              )}
            </div>
          </div>
        </div>
      )}

      {/* --- TAB 2: Emergency Green Corridor Preemption --- */}
      {activeTab === "emergency" && (
        <div className="space-y-6">
          <Card className="p-5 sm:p-6 bg-surface border-white/10 space-y-6">
            <div className="flex items-start justify-between border-b border-white/10 pb-4">
              <div>
                <div className="flex items-center gap-2">
                  <Siren className="w-6 h-6 text-rose-400" />
                  <h2 className="text-lg font-display font-bold text-text">
                    Emergency Green Wave Corridor Preemption
                  </h2>
                </div>
                <p className="text-xs sm:text-sm text-muted mt-1 leading-relaxed">
                  Advisory green corridor route planning and signal preemption for emergency transit. Conforms to safety clearance intervals.
                </p>
              </div>
              <Badge variant="danger">High Priority Preempt</Badge>
            </div>

            {/* Preemption Dispatch Form */}
            <RequireRole
              allowedRoles={["admin", "traffic_officer"]}
              fallback={
                <div className="p-5 rounded-xl bg-ink/60 border border-amber/30 text-xs text-amber space-y-2">
                  <div className="flex items-center gap-2 font-semibold">
                    <ShieldAlert className="w-5 h-5 shrink-0" />
                    <span>Emergency Clearance Required</span>
                  </div>
                  <p className="text-muted leading-relaxed">
                    Triggering emergency corridor preemption is restricted to Traffic Officers and System Administrators.
                  </p>
                </div>
              }
            >
              <form onSubmit={handleEmergencyPrioritize} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Select Emergency Event */}
                  <div>
                    <label className="block text-xs font-mono uppercase text-muted mb-1.5">
                      Active Emergency Vehicle / Incident
                    </label>
                    {emergencyEventsLoading ? (
                      <div className="h-10 rounded-xl bg-ink/60 border border-white/10 flex items-center px-3 gap-2 text-xs text-muted">
                        <LoadingSpinner size="sm" />
                        <span>Loading emergency incidents...</span>
                      </div>
                    ) : (
                      <select
                        value={emergencyEventId ?? ""}
                        onChange={(e) => setEmergencyEventId(Number(e.target.value))}
                        className="w-full h-11 px-3 rounded-xl bg-ink/80 border border-white/15 text-text text-xs sm:text-sm font-medium focus:ring-2 focus:ring-rose-500 cursor-pointer"
                      >
                        {emergencyEventsData?.items && emergencyEventsData.items.length > 0 ? (
                          emergencyEventsData.items.map((ev) => (
                            <option key={ev.id} value={ev.id}>
                              Event #{ev.id} — {ev.vehicle_type.toUpperCase()} ({ev.vehicle_id}) [Priority {ev.priority}]
                            </option>
                          ))
                        ) : (
                          <option value="">No Active Emergency Vehicles</option>
                        )}
                      </select>
                    )}
                  </div>

                  {/* Select Destination Junction */}
                  <div>
                    <label className="block text-xs font-mono uppercase text-muted mb-1.5">
                      Destination Intersection
                    </label>
                    <select
                      value={destJunctionId ?? ""}
                      onChange={(e) => setDestJunctionId(Number(e.target.value))}
                      className="w-full h-11 px-3 rounded-xl bg-ink/80 border border-white/15 text-text text-xs sm:text-sm font-medium focus:ring-2 focus:ring-rose-500 cursor-pointer"
                    >
                      {junctionsData?.items.map((j) => (
                        <option key={j.id} value={j.id}>
                          [{j.code}] {j.name} ({j.zone || "Central"})
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-3 pt-2">
                  <Button
                    type="submit"
                    variant="primary"
                    disabled={emergencyPrioritizeMutation.isPending || !emergencyEventId}
                    className="bg-rose-500 hover:bg-rose-600 text-white border-rose-500 shadow-rose-500/20"
                  >
                    {emergencyPrioritizeMutation.isPending ? (
                      <LoadingSpinner size="sm" label="Calculating Route..." />
                    ) : (
                      <>
                        <Siren className="w-4 h-4 mr-1.5" />
                        Activate Green Corridor Preemption
                      </>
                    )}
                  </Button>

                  <Button
                    type="button"
                    variant="secondary"
                    onClick={handleEmergencyRestore}
                    disabled={emergencyRestoreMutation.isPending || !emergencyEventId}
                    className="border-white/20 text-text"
                  >
                    {emergencyRestoreMutation.isPending ? (
                      <LoadingSpinner size="sm" label="Restoring..." />
                    ) : (
                      <>
                        <RotateCcw className="w-3.5 h-3.5 mr-1.5" />
                        Restore Standard Signal Plans
                      </>
                    )}
                  </Button>
                </div>
              </form>
            </RequireRole>

            {/* Preemption Corridor Results */}
            {prioritizeResult && (
              <div className="p-5 rounded-xl bg-ink/80 border border-rose-500/40 space-y-4 shadow-lg">
                <div className="flex items-center justify-between border-b border-white/10 pb-3">
                  <div>
                    <span className="text-xs font-mono uppercase text-rose-400 font-bold block">
                      Active Emergency Corridor
                    </span>
                    <h3 className="text-base font-display font-semibold text-text">
                      Corridor ID: {prioritizeResult.corridor_plan.corridor_id}
                    </h3>
                  </div>
                  <Badge variant="danger">
                    ETA {prioritizeResult.corridor_plan.estimated_minutes.toFixed(1)} min
                  </Badge>
                </div>

                {/* Path Overview */}
                <div>
                  <span className="text-xs font-mono text-muted uppercase block mb-1.5">
                    Preemption Route Path ({prioritizeResult.corridor_plan.path.length} Junctions)
                  </span>
                  <div className="flex flex-wrap items-center gap-2">
                    {prioritizeResult.corridor_plan.path.map((jId, idx) => (
                      <React.Fragment key={jId}>
                        <span className="px-2.5 py-1 rounded bg-surface border border-white/15 text-xs font-mono text-text">
                          Junction #{jId}
                        </span>
                        {idx < prioritizeResult.corridor_plan.path.length - 1 && (
                          <ArrowRight className="w-3.5 h-3.5 text-rose-400" />
                        )}
                      </React.Fragment>
                    ))}
                  </div>
                </div>

                {/* Signal Actions Table */}
                <div>
                  <span className="text-xs font-mono text-muted uppercase block mb-2">
                    Actuated Corridor Signal Directives ({prioritizeResult.corridor_plan.signal_actions.length})
                  </span>
                  <div className="space-y-2">
                    {prioritizeResult.corridor_plan.signal_actions.map((act, i) => (
                      <div
                        key={i}
                        className="p-3 rounded-lg bg-surface/70 border border-white/5 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs font-mono"
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-text font-bold">
                            Junction #{act.intersection_id}
                          </span>
                          <span className="text-muted">
                            (Signal #{act.signal_id ?? "All"})
                          </span>
                        </div>
                        <div className="flex items-center gap-3">
                          <span className="text-rose-400 font-semibold uppercase">
                            {act.action} ({act.duration_seconds}s)
                          </span>
                          <span className="text-muted text-[11px] truncate max-w-xs">
                            {act.reason}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {restoreResult && (
              <div className="p-4 rounded-xl bg-emerald-500/15 border border-emerald-500/30 text-xs text-emerald-400 space-y-1">
                <div className="flex items-center gap-2 font-semibold">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  <span>Normal Cyclic Signal Operations Restored</span>
                </div>
                <p className="text-emerald-400/90 pl-6">
                  {restoreResult.reason} ({restoreResult.affected_signal_ids.length} signals returned to standard cycle split).
                </p>
              </div>
            )}
          </Card>
        </div>
      )}

      {/* --- TAB 3: What-If Plan Simulation --- */}
      {activeTab === "whatif" && (
        <div className="space-y-6">
          <Card className="p-5 sm:p-6 bg-surface border-white/10 space-y-6">
            <div className="border-b border-white/10 pb-4">
              <div className="flex items-center gap-2">
                <GitCompare className="w-6 h-6 text-accent" />
                <h2 className="text-lg font-display font-bold text-text">
                  Macroscopic Point-Queue Traffic Simulation
                </h2>
              </div>
              <p className="text-xs sm:text-sm text-muted mt-1 leading-relaxed">
                Evaluates candidate signal timing adjustments against baseline plans. Reports physical wait delay deltas, throughput, and deterministic verdicts. Zero percentage-improvement claims.
              </p>
            </div>

            {/* Simulation Config Form */}
            <form onSubmit={handleRunSimulation} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-xs font-mono">
                <div>
                  <label className="block text-muted uppercase text-[11px] mb-1">
                    Simulation Horizon
                  </label>
                  <select
                    value={simHorizon}
                    onChange={(e) => setSimHorizon(Number(e.target.value))}
                    className="w-full h-10 px-3 rounded-xl bg-ink/80 border border-white/15 text-text"
                  >
                    <option value={10}>10.0 Minutes</option>
                    <option value={15}>15.0 Minutes (Standard)</option>
                    <option value={30}>30.0 Minutes</option>
                  </select>
                </div>

                <div>
                  <label className="block text-muted uppercase text-[11px] mb-1">
                    Discrete Step dt
                  </label>
                  <select
                    value={simDt}
                    onChange={(e) => setSimDt(Number(e.target.value))}
                    className="w-full h-10 px-3 rounded-xl bg-ink/80 border border-white/15 text-text"
                  >
                    <option value={2}>2.0 Seconds</option>
                    <option value={5}>5.0 Seconds (Default)</option>
                    <option value={10}>10.0 Seconds</option>
                  </select>
                </div>

                <div>
                  <label className="block text-muted uppercase text-[11px] mb-1">
                    Baseline Phase N Green
                  </label>
                  <input
                    type="number"
                    min={10}
                    max={120}
                    value={simCurrentGreen}
                    onChange={(e) => setSimCurrentGreen(Number(e.target.value))}
                    className="w-full h-10 px-3 rounded-xl bg-ink/80 border border-white/15 text-text"
                  />
                </div>

                <div>
                  <label className="block text-muted uppercase text-[11px] mb-1">
                    Proposed Phase N Green
                  </label>
                  <input
                    type="number"
                    min={10}
                    max={120}
                    value={simProposedGreen}
                    onChange={(e) => setSimProposedGreen(Number(e.target.value))}
                    className="w-full h-10 px-3 rounded-xl bg-ink/80 border border-white/15 text-text"
                  />
                </div>
              </div>

              <Button
                type="submit"
                variant="primary"
                disabled={simulateMutation.isPending || !selectedJunctionId}
                className="text-xs"
              >
                {simulateMutation.isPending ? (
                  <LoadingSpinner size="sm" label="Executing Simulation..." />
                ) : (
                  <>
                    <Play className="w-3.5 h-3.5 mr-1.5" />
                    Simulate & Compare Plans
                  </>
                )}
              </Button>
            </form>

            {/* Simulation Results Comparison */}
            {simResult && (
              <div className="p-5 rounded-xl bg-ink/70 border border-white/10 space-y-5">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-3">
                  <div>
                    <span className="text-[11px] font-mono uppercase text-muted block">
                      Deterministic Verdict
                    </span>
                    <h3 className="text-base font-display font-bold text-text uppercase">
                      {simResult.verdict === "proposed_better"
                        ? "PROPOSED PLAN SUPERIOR"
                        : simResult.verdict === "current_better"
                        ? "BASELINE PLAN SUPERIOR"
                        : "PLANS OPERATIONALLY EQUIVALENT"}
                    </h3>
                  </div>
                  <Badge
                    variant={
                      simResult.verdict === "proposed_better"
                        ? "success"
                        : simResult.verdict === "current_better"
                        ? "amber"
                        : "muted"
                    }
                  >
                    {simResult.verdict}
                  </Badge>
                </div>

                {/* Deltas Grid */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div className="p-3.5 rounded-xl bg-surface/70 border border-white/10 space-y-1">
                    <span className="text-[10px] font-mono uppercase text-muted block">
                      Delta Total Wait Delay
                    </span>
                    <span
                      className={`text-lg font-mono font-bold ${
                        simResult.delta_wait < 0 ? "text-emerald-400" : "text-rose-400"
                      }`}
                    >
                      {simResult.delta_wait > 0 ? "+" : ""}
                      {simResult.delta_wait.toFixed(2)} veh·min
                    </span>
                    <span className="text-[10px] text-muted block">
                      {simResult.delta_wait < 0 ? "Reduced overall queue delay" : "Increased overall queue delay"}
                    </span>
                  </div>

                  <div className="p-3.5 rounded-xl bg-surface/70 border border-white/10 space-y-1">
                    <span className="text-[10px] font-mono uppercase text-muted block">
                      Delta Average Queue
                    </span>
                    <span
                      className={`text-lg font-mono font-bold ${
                        simResult.delta_avg_queue < 0 ? "text-emerald-400" : "text-rose-400"
                      }`}
                    >
                      {simResult.delta_avg_queue > 0 ? "+" : ""}
                      {simResult.delta_avg_queue.toFixed(2)} veh
                    </span>
                    <span className="text-[10px] text-muted block">
                      Time-averaged queue differential
                    </span>
                  </div>

                  <div className="p-3.5 rounded-xl bg-surface/70 border border-white/10 space-y-1">
                    <span className="text-[10px] font-mono uppercase text-muted block">
                      Delta Vehicle Throughput
                    </span>
                    <span
                      className={`text-lg font-mono font-bold ${
                        simResult.delta_throughput > 0 ? "text-emerald-400" : "text-text"
                      }`}
                    >
                      {simResult.delta_throughput > 0 ? "+" : ""}
                      {simResult.delta_throughput.toFixed(0)} veh
                    </span>
                    <span className="text-[10px] text-muted block">
                      Net departed vehicle capacity
                    </span>
                  </div>
                </div>

                <div className="p-3 rounded-lg bg-surface/40 border border-white/5 text-[11px] text-muted space-y-1 font-mono">
                  <div>Baseline Digest: {simResult.current_result.plan_digest.slice(0, 16)}...</div>
                  <div>Proposed Digest: {simResult.proposed_result.plan_digest.slice(0, 16)}...</div>
                </div>
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
