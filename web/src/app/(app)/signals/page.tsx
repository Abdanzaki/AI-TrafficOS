"use client";

import React, { useState, useMemo, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import {
  Radio,
  Sliders,
  Eye,
  RefreshCw,
  AlertTriangle,
  CheckCircle2,
  Clock,
  ShieldAlert,
  Layers,
  Settings2,
  Activity,
  Check,
  ChevronDown,
  Zap,
  Info,
  Timer,
  Camera,
  AlertOctagon,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth";
import { useApiQuery, useApiMutation } from "@/lib/use-api";
import { useTopic } from "@/lib/realtime";
import { Card } from "@/components/ui/Card";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { RequireRole } from "@/components/RequireRole";
import { Pagination } from "@/components/ui/Pagination";
import { formatDateTime, formatSeconds, formatPercent } from "@/lib/format";

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

export interface SignalPhaseItem {
  id: number;
  signal_id: number;
  intersection_id?: number | null;
  name: string;
  phase_order: number;
  duration_seconds: number;
  state: string; // "red" | "yellow" | "green"
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SignalItem {
  id: number;
  intersection_id: number;
  code: string;
  status: string;
  observed_state?: string | null;
  observed_confidence?: number | null;
  observed_at?: string | null;
  created_at: string;
  updated_at: string;
  phases?: SignalPhaseItem[] | null;
}

interface PaginatedSignals {
  items: SignalItem[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface SignalObservationItem {
  signal_id: number;
  intersection_id: number;
  intersection_name?: string | null;
  intersection_code?: string | null;
  signal_code: string;
  status: string;
  observed_state: string; // "red" | "yellow" | "green" | "unknown"
  observed_confidence: number;
  observed_at?: string | null;
  created_at: string;
  updated_at: string;
}

interface PaginatedSignalObservations {
  items: SignalObservationItem[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

interface SignalPhaseUpdatePayload {
  name?: string;
  phase_order?: number;
  duration_seconds?: number;
  state?: string;
  is_active?: boolean;
}

interface SignalOverridePayload {
  phase_id?: number;
  state?: string;
  is_active?: boolean;
  reason?: string;
}

// --- Helper Utilities ---

function getPhaseColorStyles(state: string) {
  const norm = state.toLowerCase().trim();
  switch (norm) {
    case "green":
      return {
        pill: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30 ring-emerald-500/20",
        dot: "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]",
        badgeVariant: "success" as BadgeVariant,
        text: "Green Phase",
      };
    case "yellow":
    case "amber":
      return {
        pill: "bg-amber-500/15 text-amber-400 border-amber-500/30 ring-amber-500/20",
        dot: "bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.8)]",
        badgeVariant: "amber" as BadgeVariant,
        text: "Yellow Change",
      };
    case "red":
      return {
        pill: "bg-rose-500/15 text-rose-400 border-rose-500/30 ring-rose-500/20",
        dot: "bg-rose-400 shadow-[0_0_8px_rgba(244,63,94,0.8)]",
        badgeVariant: "danger" as BadgeVariant,
        text: "Red Clearance",
      };
    default:
      return {
        pill: "bg-white/10 text-muted border-white/15 ring-white/10",
        dot: "bg-muted",
        badgeVariant: "muted" as BadgeVariant,
        text: "Unknown",
      };
  }
}

function SignalsPageContent() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const { user, isAdmin, isOfficer } = useAuth();

  // Selected Junction ID
  const [selectedJunctionId, setSelectedJunctionId] = useState<number | null>(null);

  // Selected Signal Controller ID
  const [selectedSignalId, setSelectedSignalId] = useState<number | null>(null);

  // Selected Phase for manual update modal/panel
  const [selectedPhaseId, setSelectedPhaseId] = useState<number | null>(null);

  // Optical observations pagination
  const [visionPage, setVisionPage] = useState<number>(1);

  // Form State for Manual Phase Update (PATCH)
  const [editDuration, setEditDuration] = useState<number>(30);
  const [editState, setEditState] = useState<string>("green");
  const [editIsActive, setEditIsActive] = useState<boolean>(true);

  // Form State for Signal Override (POST)
  const [overrideState, setOverrideState] = useState<string>("green");
  const [overrideReason, setOverrideReason] = useState<string>("");
  const [overridePhaseId, setOverridePhaseId] = useState<number | "all">("all");

  // Feedback notifications
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Real-time invalidations: signal.change updates signal states, phases, and vision observations
  useTopic("signal.change", () => {
    queryClient.invalidateQueries({ queryKey: ["signals-for-junction"] });
    queryClient.invalidateQueries({ queryKey: ["signal-detail"] });
    queryClient.invalidateQueries({ queryKey: ["vision-observations"] });
  });

  // --- 1. Fetch Junctions List ---
  // No WS topic for junctions-list; polling retained intentionally
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

  // Automatically select the junction from searchParams or default to first
  useEffect(() => {
    const junctionParam = searchParams.get("junction");
    if (junctionParam) {
      const parsed = parseInt(junctionParam, 10);
      if (!isNaN(parsed)) {
        setSelectedJunctionId(parsed);
        return;
      }
    }
    if (!selectedJunctionId && junctionsData?.items && junctionsData.items.length > 0) {
      setSelectedJunctionId(junctionsData.items[0].id);
    }
  }, [junctionsData, selectedJunctionId, searchParams]);

  const selectedJunction = useMemo(() => {
    return junctionsData?.items.find((j) => j.id === selectedJunctionId);
  }, [junctionsData, selectedJunctionId]);

  // --- 2. Fetch Signals for Selected Junction ---
  const {
    data: signalsData,
    isLoading: signalsLoading,
    isError: signalsIsError,
    error: signalsError,
    refetch: refetchSignals,
  } = useApiQuery<PaginatedSignals>({
    queryKey: ["signals-for-junction", selectedJunctionId],
    endpoint: "/signals",
    params: selectedJunctionId ? { intersection_id: selectedJunctionId, per_page: 50 } : undefined,
    queryOptions: {
      enabled: selectedJunctionId !== null,
    },
  });

  // Automatically select first signal controller when junction signals load
  useEffect(() => {
    if (signalsData?.items && signalsData.items.length > 0) {
      const exists = signalsData.items.some((s) => s.id === selectedSignalId);
      if (!selectedSignalId || !exists) {
        setSelectedSignalId(signalsData.items[0].id);
      }
    } else {
      setSelectedSignalId(null);
    }
  }, [signalsData, selectedSignalId]);

  // --- 3. Fetch Full Signal Detail (includes loaded and sorted phases) ---
  const {
    data: signalDetail,
    isLoading: detailLoading,
    isError: detailIsError,
    error: detailError,
    refetch: refetchDetail,
  } = useApiQuery<SignalItem>({
    queryKey: ["signal-detail", selectedSignalId],
    endpoint: selectedSignalId ? `/signals/${selectedSignalId}` : "/signals/0",
    queryOptions: {
      enabled: selectedSignalId !== null,
    },
  });

  // When signal detail phases load, default active phase edit values
  const activePhases = useMemo(() => {
    return signalDetail?.phases ?? [];
  }, [signalDetail]);

  useEffect(() => {
    if (activePhases.length > 0) {
      const targetPhase =
        activePhases.find((p) => p.id === selectedPhaseId) ||
        activePhases.find((p) => p.is_active) ||
        activePhases[0];

      if (targetPhase && selectedPhaseId !== targetPhase.id) {
        setSelectedPhaseId(targetPhase.id);
        setEditDuration(targetPhase.duration_seconds);
        setEditState(targetPhase.state);
        setEditIsActive(targetPhase.is_active);
      }
    } else {
      setSelectedPhaseId(null);
    }
  }, [activePhases, selectedPhaseId]);

  // --- 4. Fetch Vision Signal Observations ---
  const {
    data: visionObservations,
    isLoading: visionLoading,
    isError: visionIsError,
    error: visionError,
    refetch: refetchVision,
  } = useApiQuery<PaginatedSignalObservations>({
    queryKey: ["vision-observations", selectedJunctionId, visionPage],
    endpoint: "/vision/signal-observations",
    params: selectedJunctionId ? { intersection_id: selectedJunctionId, page: visionPage, per_page: 20 } : undefined,
    queryOptions: {
      enabled: selectedJunctionId !== null,
    },
  });

  // --- 5. Phase Update Mutation (PATCH) ---
  const patchPhaseMutation = useApiMutation<SignalPhaseItem, SignalPhaseUpdatePayload>({
    endpoint: `/signals/${selectedSignalId}/phases/${selectedPhaseId}`,
    method: "PATCH",
    mutationOptions: {
      onSuccess: (updated) => {
        setActionError(null);
        setActionSuccess(`Phase '${updated.name}' updated successfully: ${updated.state.toUpperCase()} (${updated.duration_seconds}s).`);
        queryClient.invalidateQueries({ queryKey: ["signal-detail", selectedSignalId] });
        queryClient.invalidateQueries({ queryKey: ["signals-for-junction", selectedJunctionId] });
        setTimeout(() => setActionSuccess(null), 6000);
      },
      onError: (err) => {
        setActionSuccess(null);
        setActionError(err.message || "Failed to update signal phase interval.");
      },
    },
  });

  // --- 6. Manual Override Mutation (POST) ---
  const overrideMutation = useApiMutation<SignalItem, SignalOverridePayload>({
    endpoint: `/signals/${selectedSignalId}/override`,
    method: "POST",
    mutationOptions: {
      onSuccess: (sig) => {
        setActionError(null);
        setActionSuccess(`Manual override applied to controller ${sig.code}. New state activated.`);
        setOverrideReason("");
        queryClient.invalidateQueries({ queryKey: ["signal-detail", selectedSignalId] });
        queryClient.invalidateQueries({ queryKey: ["signals-for-junction", selectedJunctionId] });
        setTimeout(() => setActionSuccess(null), 6000);
      },
      onError: (err) => {
        setActionSuccess(null);
        setActionError(err.message || "Failed to execute manual signal override.");
      },
    },
  });

  // Handlers
  const handleRefreshAll = () => {
    refetchJunctions();
    if (selectedJunctionId) {
      refetchSignals();
      refetchVision();
    }
    if (selectedSignalId) {
      refetchDetail();
    }
  };

  const handlePhaseSelect = (phase: SignalPhaseItem) => {
    setSelectedPhaseId(phase.id);
    setEditDuration(phase.duration_seconds);
    setEditState(phase.state);
    setEditIsActive(phase.is_active);
  };

  const handleApplyPhaseUpdate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedSignalId || !selectedPhaseId) return;
    patchPhaseMutation.mutate({
      duration_seconds: editDuration,
      state: editState,
      is_active: editIsActive,
    });
  };

  const handleExecuteOverride = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedSignalId) return;
    if (!overrideReason.trim()) {
      setActionError("An operational reason is required for auditing manual overrides.");
      return;
    }
    const payload: SignalOverridePayload = {
      state: overrideState,
      reason: overrideReason.trim(),
    };
    if (overridePhaseId !== "all") {
      payload.phase_id = overridePhaseId;
    }
    overrideMutation.mutate(payload);
  };

  // Calculate cycle timing breakdown
  const cycleTotalSeconds = useMemo(() => {
    return activePhases.reduce((acc, p) => acc + (p.duration_seconds || 0), 0);
  }, [activePhases]);

  const activePhase = useMemo(() => {
    return activePhases.find((p) => p.is_active);
  }, [activePhases]);

  // Cross-check camera observation with controller state
  const cvDiscrepancy = useMemo(() => {
    if (!visionObservations?.items || visionObservations.items.length === 0 || !activePhase) {
      return null;
    }
    const latestObs = visionObservations.items[0];
    if (latestObs.observed_state && activePhase.state) {
      const obsNorm = latestObs.observed_state.toLowerCase();
      const ctrlNorm = activePhase.state.toLowerCase();
      if (obsNorm !== "unknown" && obsNorm !== ctrlNorm) {
        return {
          cameraState: obsNorm,
          cameraConf: latestObs.observed_confidence,
          controllerState: ctrlNorm,
          signalCode: latestObs.signal_code,
        };
      }
    }
    return null;
  }, [visionObservations, activePhase]);

  // Full-page error if junctions fail to load (e.g. backend down)
  if (junctionsIsError) {
    return (
      <div className="max-w-7xl mx-auto p-4 sm:p-6 space-y-6">
        <ErrorState
          title="Failed to Connect to Traffic Signal Service"
          message={junctionsError?.message || "Unable to reach junction telemetry API. Verify backend daemon connectivity."}
          onRetry={refetchJunctions}
          retryText="Retry Connection"
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
              Signal Status & Control
            </h1>
            <Badge variant="teal" dot>
              Live Telemetry
            </Badge>
            <Badge variant="muted">NTCIP 1202</Badge>
          </div>
          <p className="text-xs sm:text-sm text-muted">
            Hardware controller phase status, optical camera validation, and supervisory manual override.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <Button
            variant="secondary"
            size="sm"
            onClick={handleRefreshAll}
            className="text-xs font-mono"
          >
            <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
            Sync Hardware
          </Button>
        </div>
      </div>

      {/* --- Feedback Banners --- */}
      {actionSuccess && (
        <div className="p-3.5 rounded-xl bg-success/15 border border-success/30 text-success text-xs sm:text-sm flex items-center justify-between shadow-md">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 shrink-0 text-success" />
            <span>{actionSuccess}</span>
          </div>
          <button
            onClick={() => setActionSuccess(null)}
            className="text-success/70 hover:text-success text-xs font-mono ml-3 cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {actionError && (
        <div className="p-3.5 rounded-xl bg-danger/15 border border-danger/30 text-danger text-xs sm:text-sm flex items-center justify-between shadow-md">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 text-danger" />
            <span>{actionError}</span>
          </div>
          <button
            onClick={() => setActionError(null)}
            className="text-danger/70 hover:text-danger text-xs font-mono ml-3 cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* --- Junction Selector & Telemetry Bar --- */}
      <Card className="p-4 sm:p-5 bg-surface/90 border-white/10">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex-1 min-w-0">
            <label
              htmlFor="junction-select"
              className="block text-xs font-medium text-muted uppercase tracking-wider mb-1.5 font-mono"
            >
              Select Operational Junction
            </label>
            <div className="relative max-w-xl">
              {junctionsLoading ? (
                <div className="h-10 rounded-xl bg-ink/60 border border-white/10 flex items-center px-3 gap-2 text-xs text-muted">
                  <LoadingSpinner size="sm" />
                  <span>Loading network junctions...</span>
                </div>
              ) : (
                <div className="relative">
                  <select
                    id="junction-select"
                    value={selectedJunctionId ?? ""}
                    onChange={(e) => {
                      const id = Number(e.target.value);
                      setSelectedJunctionId(id);
                      setSelectedPhaseId(null);
                    }}
                    className="w-full h-11 pl-3.5 pr-10 rounded-xl bg-ink/80 border border-white/15 text-text text-sm font-medium focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent appearance-none transition-colors cursor-pointer"
                  >
                    {junctionsData?.items.map((j) => (
                      <option key={j.id} value={j.id} className="bg-ink text-text">
                        [{j.code}] {j.name} {j.zone ? `— ${j.zone}` : ""} ({j.status})
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="w-4 h-4 text-muted absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                </div>
              )}
            </div>
          </div>

          {selectedJunction && (
            <div className="flex flex-wrap items-center gap-3 pt-2 md:pt-0 border-t md:border-t-0 border-white/10 text-xs">
              <div className="px-3 py-1.5 rounded-lg bg-ink/50 border border-white/5">
                <span className="text-muted block text-[10px] uppercase font-mono">Status</span>
                <span className="font-semibold text-text capitalize">{selectedJunction.status}</span>
              </div>
              <div className="px-3 py-1.5 rounded-lg bg-ink/50 border border-white/5">
                <span className="text-muted block text-[10px] uppercase font-mono">Zone</span>
                <span className="font-semibold text-text">{selectedJunction.zone || "Central"}</span>
              </div>
              <div className="px-3 py-1.5 rounded-lg bg-ink/50 border border-white/5">
                <span className="text-muted block text-[10px] uppercase font-mono">City</span>
                <span className="font-semibold text-text">{selectedJunction.city || "Metropolis"}</span>
              </div>
              <div className="px-3 py-1.5 rounded-lg bg-ink/50 border border-white/5">
                <span className="text-muted block text-[10px] uppercase font-mono">Controllers</span>
                <span className="font-semibold text-accent font-mono">
                  {signalsData?.items.length ?? 0} Unit(s)
                </span>
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* --- Main Content Split: Signal Telemetry & Controls vs CV Observations --- */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column (8 cols): Hardware Controllers, Live Phases, and Manual Controls */}
        <div className="lg:col-span-8 space-y-6">
          {/* Signal Controller Selection & Overview */}
          <Card className="p-5 sm:p-6 bg-surface border-white/10">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-white/10 pb-4 mb-5">
              <div>
                <div className="flex items-center gap-2">
                  <Radio className="w-5 h-5 text-accent" />
                  <h2 className="text-base sm:text-lg font-display font-semibold text-text">
                    Hardware Signal Controller
                  </h2>
                </div>
                <p className="text-xs text-muted mt-0.5">
                  NTCIP actuated field cabinet phase sequences and ring interval timers.
                </p>
              </div>

              {/* Multiple Controller Switcher if junction has > 1 */}
              {signalsData?.items && signalsData.items.length > 1 && (
                <div className="flex items-center gap-1.5 bg-ink/60 p-1 rounded-xl border border-white/10">
                  {signalsData.items.map((sig) => (
                    <button
                      key={sig.id}
                      onClick={() => setSelectedSignalId(sig.id)}
                      className={`px-2.5 py-1 rounded-lg text-xs font-mono font-medium transition-colors cursor-pointer ${
                        selectedSignalId === sig.id
                          ? "bg-accent text-ink"
                          : "text-muted hover:text-text hover:bg-white/5"
                      }`}
                    >
                      {sig.code}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {signalsLoading || detailLoading ? (
              <div className="py-12 flex flex-col items-center justify-center">
                <LoadingSpinner size="md" label="Polling signal controller telemetry..." />
              </div>
            ) : signalsIsError ? (
              <ErrorState
                title="Signal Hardware Communication Failure"
                message={signalsError?.message || "Could not retrieve signal controller telemetry."}
                onRetry={refetchSignals}
              />
            ) : !signalsData?.items || signalsData.items.length === 0 ? (
              <EmptyState
                icon={<Radio className="w-8 h-8 text-muted" />}
                title="No Signal Controllers Configured"
                description={`No physical traffic signal controller hardware registered for junction #${selectedJunctionId}.`}
              />
            ) : (
              <div className="space-y-6">
                {/* Controller Meta Banner */}
                {signalDetail && (
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-3.5 rounded-xl bg-ink/60 border border-white/10 text-xs">
                    <div>
                      <span className="text-muted block text-[10px] uppercase font-mono">Controller Code</span>
                      <span className="font-mono font-semibold text-text">{signalDetail.code}</span>
                    </div>
                    <div>
                      <span className="text-muted block text-[10px] uppercase font-mono">Hardware Status</span>
                      <span className="inline-flex items-center gap-1.5 font-medium text-emerald-400 capitalize">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                        {signalDetail.status}
                      </span>
                    </div>
                    <div>
                      <span className="text-muted block text-[10px] uppercase font-mono">Cycle Length</span>
                      <span className="font-mono font-semibold text-accent">
                        {cycleTotalSeconds > 0 ? formatSeconds(cycleTotalSeconds) : "—"}
                      </span>
                    </div>
                    <div>
                      <span className="text-muted block text-[10px] uppercase font-mono">Last Synchronized</span>
                      <span className="font-mono text-text">
                        {formatDateTime(signalDetail.updated_at)}
                      </span>
                    </div>
                  </div>
                )}

                {/* Visual Cycle Segment Bar */}
                {activePhases.length > 0 && cycleTotalSeconds > 0 && (
                  <div>
                    <div className="flex items-center justify-between text-xs mb-2">
                      <span className="text-muted font-mono uppercase text-[11px] flex items-center gap-1.5">
                        <Timer className="w-3.5 h-3.5 text-accent" />
                        Cycle Interval Distribution
                      </span>
                      <span className="text-text font-mono text-xs font-medium">
                        Total {cycleTotalSeconds}s
                      </span>
                    </div>
                    <div className="h-3 rounded-full bg-ink/80 overflow-hidden flex border border-white/10">
                      {activePhases.map((phase) => {
                        const pct = (phase.duration_seconds / cycleTotalSeconds) * 100;
                        const isGreen = phase.state.toLowerCase() === "green";
                        const isYellow = phase.state.toLowerCase() === "yellow";
                        const bg = isGreen
                          ? "bg-emerald-500"
                          : isYellow
                          ? "bg-amber-400"
                          : "bg-rose-500";
                        return (
                          <div
                            key={phase.id}
                            style={{ width: `${pct}%` }}
                            className={`${bg} h-full transition-all relative group ${
                              phase.is_active ? "brightness-125 saturate-150 animate-pulse" : "opacity-80"
                            }`}
                            title={`Phase #${phase.phase_order} (${phase.name}): ${phase.duration_seconds}s (${phase.state})`}
                          />
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Phase List with Color-coded pills and timing */}
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-xs font-mono uppercase tracking-wider text-muted flex items-center gap-1.5">
                      <Layers className="w-3.5 h-3.5 text-accent" />
                      Phases & Interval Sequences ({activePhases.length})
                    </h3>
                    {activePhase && (
                      <span className="text-xs font-mono text-emerald-400 flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
                        Active Phase: #{activePhase.phase_order} ({activePhase.name})
                      </span>
                    )}
                  </div>

                  {activePhases.length === 0 ? (
                    <div className="p-6 rounded-xl bg-ink/40 border border-white/5 text-center text-xs text-muted">
                      No phases configured for this signal controller.
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {activePhases.map((phase) => {
                        const styles = getPhaseColorStyles(phase.state);
                        const isSelected = selectedPhaseId === phase.id;

                        return (
                          <div
                            key={phase.id}
                            onClick={() => handlePhaseSelect(phase)}
                            className={`p-4 rounded-xl border transition-all cursor-pointer relative ${
                              phase.is_active
                                ? "bg-surface/90 border-accent/40 shadow-lg shadow-accent/5 ring-1 ring-accent/30"
                                : "bg-ink/60 border-white/10 hover:border-white/20"
                            } ${isSelected ? "ring-2 ring-accent" : ""}`}
                          >
                            <div className="flex items-start justify-between gap-2 mb-2">
                              <div className="flex items-center gap-2">
                                <span className="font-mono text-xs font-bold text-muted bg-white/5 px-2 py-0.5 rounded">
                                  #{phase.phase_order}
                                </span>
                                <h4 className="text-sm font-semibold text-text truncate max-w-[150px] sm:max-w-[180px]">
                                  {phase.name}
                                </h4>
                              </div>

                              {/* State Pill */}
                              <span
                                className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-mono uppercase border font-medium ${styles.pill}`}
                              >
                                <span className={`w-2 h-2 rounded-full ${styles.dot}`} />
                                {phase.state}
                              </span>
                            </div>

                            <div className="flex items-center justify-between text-xs text-muted pt-2 border-t border-white/5">
                              <div className="flex items-center gap-1.5 font-mono">
                                <Clock className="w-3.5 h-3.5 text-accent" />
                                <span className="text-text font-semibold">
                                  {phase.duration_seconds}s
                                </span>
                                <span>interval</span>
                              </div>

                              <div>
                                {phase.is_active ? (
                                  <span className="text-emerald-400 font-mono text-[11px] font-medium flex items-center gap-1">
                                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                                    ACTIVE NOW
                                  </span>
                                ) : (
                                  <span className="text-muted/70 font-mono text-[11px]">STANDBY</span>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            )}
          </Card>

          {/* Manual Override & Phase Control Controls */}
          <Card className="p-5 sm:p-6 bg-surface border-white/10">
            <div className="flex items-center justify-between border-b border-white/10 pb-4 mb-5">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-amber/15 border border-amber/30 text-amber flex items-center justify-center">
                  <Settings2 className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-display font-semibold text-text">
                    Manual Phase Timing & Override Controls
                  </h3>
                  <p className="text-xs text-muted">
                    Supervisory override interface. Dispatched actions write to system audit logs.
                  </p>
                </div>
              </div>
              <Badge variant={isAdmin() || isOfficer() ? "amber" : "muted"}>
                {isAdmin() || isOfficer() ? "Officer Clearance" : "Read Only"}
              </Badge>
            </div>

            {/* Role Verification Wrapper: Analysts see a clean read-only permission notice */}
            <RequireRole
              allowedRoles={["admin", "traffic_officer"]}
              fallback={
                <div className="p-5 rounded-xl bg-ink/60 border border-amber/30 flex items-start gap-3.5">
                  <div className="w-8 h-8 rounded-lg bg-amber/15 text-amber flex items-center justify-center shrink-0 mt-0.5">
                    <ShieldAlert className="w-4 h-4" />
                  </div>
                  <div>
                    <h4 className="text-sm font-semibold text-text">
                      Read-Only Telemetry Clearance
                    </h4>
                    <p className="text-xs text-muted mt-1 leading-relaxed">
                      Your current role (<span className="text-text font-mono font-medium">{user?.role || "analyst"}</span>) grants inspection clearance. Signal phase timing modification (PATCH) and manual signal override requires role <span className="font-mono text-accent font-medium">traffic_officer</span> or <span className="font-mono text-accent font-medium">admin</span>.
                    </p>
                  </div>
                </div>
              }
            >
              {/* Authorized Operator Controls */}
              <div className="space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Action 1: Adjust Selected Phase Interval (PATCH) */}
                  <div className="p-4 rounded-xl bg-ink/60 border border-white/10 space-y-4">
                    <div className="flex items-center justify-between border-b border-white/5 pb-2">
                      <span className="text-xs font-mono font-semibold text-text flex items-center gap-1.5">
                        <Sliders className="w-3.5 h-3.5 text-accent" />
                        Modify Phase Interval (PATCH)
                      </span>
                      {selectedPhaseId && (
                        <span className="text-[11px] font-mono text-muted">
                          ID: #{selectedPhaseId}
                        </span>
                      )}
                    </div>

                    {!selectedPhaseId ? (
                      <p className="text-xs text-muted py-4 text-center">
                        Select a phase above to configure timing.
                      </p>
                    ) : (
                      <form onSubmit={handleApplyPhaseUpdate} className="space-y-3.5">
                        <div>
                          <label className="block text-[11px] text-muted font-mono uppercase mb-1">
                            Target State
                          </label>
                          <div className="grid grid-cols-3 gap-2">
                            {(["green", "yellow", "red"] as const).map((st) => (
                              <button
                                key={st}
                                type="button"
                                onClick={() => setEditState(st)}
                                className={`py-1.5 text-xs font-mono font-medium uppercase rounded-lg border transition-all cursor-pointer ${
                                  editState === st
                                    ? st === "green"
                                      ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/50 shadow-sm"
                                      : st === "yellow"
                                      ? "bg-amber-500/20 text-amber-400 border-amber-500/50 shadow-sm"
                                      : "bg-rose-500/20 text-rose-400 border-rose-500/50 shadow-sm"
                                    : "bg-surface/60 text-muted border-white/5 hover:bg-surface hover:text-text"
                                }`}
                              >
                                {st}
                              </button>
                            ))}
                          </div>
                        </div>

                        <div>
                          <label className="block text-[11px] text-muted font-mono uppercase mb-1">
                            Duration Seconds: {editDuration}s
                          </label>
                          <div className="flex items-center gap-2">
                            <input
                              type="number"
                              min={5}
                              max={300}
                              value={editDuration}
                              onChange={(e) => setEditDuration(Math.max(1, Number(e.target.value)))}
                              className="w-24 h-9 px-2.5 rounded-lg bg-surface border border-white/15 text-text font-mono text-xs focus:ring-2 focus:ring-accent focus:border-accent"
                            />
                            <div className="flex items-center gap-1">
                              <button
                                type="button"
                                onClick={() => setEditDuration((prev) => Math.max(5, prev - 5))}
                                className="px-2 py-1 text-xs font-mono rounded bg-white/5 hover:bg-white/10 text-muted hover:text-text border border-white/5 cursor-pointer"
                              >
                                -5s
                              </button>
                              <button
                                type="button"
                                onClick={() => setEditDuration((prev) => prev + 5)}
                                className="px-2 py-1 text-xs font-mono rounded bg-white/5 hover:bg-white/10 text-muted hover:text-text border border-white/5 cursor-pointer"
                              >
                                +5s
                              </button>
                              <button
                                type="button"
                                onClick={() => setEditDuration((prev) => prev + 15)}
                                className="px-2 py-1 text-xs font-mono rounded bg-white/5 hover:bg-white/10 text-muted hover:text-text border border-white/5 cursor-pointer"
                              >
                                +15s
                              </button>
                            </div>
                          </div>
                        </div>

                        <div className="flex items-center gap-2 pt-1">
                          <input
                            type="checkbox"
                            id="edit-is-active"
                            checked={editIsActive}
                            onChange={(e) => setEditIsActive(e.target.checked)}
                            className="rounded bg-surface border-white/20 text-accent focus:ring-accent"
                          />
                          <label
                            htmlFor="edit-is-active"
                            className="text-xs text-muted cursor-pointer select-none"
                          >
                            Set as current active phase interval
                          </label>
                        </div>

                        <Button
                          type="submit"
                          variant="primary"
                          size="sm"
                          disabled={patchPhaseMutation.isPending}
                          className="w-full mt-2"
                        >
                          {patchPhaseMutation.isPending ? (
                            <LoadingSpinner size="sm" label="Applying..." />
                          ) : (
                            <>
                              <Check className="w-3.5 h-3.5 mr-1" />
                              Save Phase Timing (PATCH)
                            </>
                          )}
                        </Button>
                      </form>
                    )}
                  </div>

                  {/* Action 2: Manual Signal Override (POST) */}
                  <div className="p-4 rounded-xl bg-ink/60 border border-amber/20 space-y-4">
                    <div className="flex items-center justify-between border-b border-white/5 pb-2">
                      <span className="text-xs font-mono font-semibold text-amber flex items-center gap-1.5">
                        <Zap className="w-3.5 h-3.5 text-amber" />
                        Direct State Override (POST)
                      </span>
                      <span className="text-[10px] font-mono uppercase bg-amber/15 text-amber px-1.5 py-0.5 rounded">
                        Audit Logged
                      </span>
                    </div>

                    <form onSubmit={handleExecuteOverride} className="space-y-3">
                      <div>
                        <label className="block text-[11px] text-muted font-mono uppercase mb-1">
                          Override Lamp State
                        </label>
                        <select
                          value={overrideState}
                          onChange={(e) => setOverrideState(e.target.value)}
                          className="w-full h-9 px-2.5 rounded-lg bg-surface border border-white/15 text-text font-mono text-xs focus:ring-2 focus:ring-amber focus:border-amber cursor-pointer"
                        >
                          <option value="green">GREEN (Force Green Light)</option>
                          <option value="yellow">YELLOW (Force Caution Clearance)</option>
                          <option value="red">RED (All-Red Stop Preemption)</option>
                        </select>
                      </div>

                      <div>
                        <label className="block text-[11px] text-muted font-mono uppercase mb-1">
                          Operational Reason (Required)
                        </label>
                        <textarea
                          rows={2}
                          value={overrideReason}
                          onChange={(e) => setOverrideReason(e.target.value)}
                          placeholder="e.g. Incident clearance, arterial hold, or emergency escort..."
                          className="w-full p-2.5 rounded-lg bg-surface border border-white/15 text-text text-xs focus:ring-2 focus:ring-amber focus:border-amber resize-none"
                        />
                      </div>

                      <Button
                        type="submit"
                        variant="secondary"
                        size="sm"
                        disabled={overrideMutation.isPending || !overrideReason.trim()}
                        className="w-full border-amber/40 text-amber hover:border-amber hover:bg-amber/10"
                      >
                        {overrideMutation.isPending ? (
                          <LoadingSpinner size="sm" label="Actuating..." />
                        ) : (
                          <>
                            <AlertOctagon className="w-3.5 h-3.5 mr-1.5" />
                            Actuate Manual Override
                          </>
                        )}
                      </Button>
                    </form>
                  </div>
                </div>
              </div>
            </RequireRole>
          </Card>
        </div>

        {/* Right Column (4 cols): Vision Optical State Observations */}
        <div className="lg:col-span-4 space-y-6">
          <Card className="p-5 sm:p-6 bg-surface border-white/10">
            <div className="flex items-center justify-between border-b border-white/10 pb-4 mb-4">
              <div>
                <div className="flex items-center gap-2">
                  <Camera className="w-5 h-5 text-accent" />
                  <h3 className="text-base font-display font-semibold text-text">
                    Vision Optical Detections
                  </h3>
                </div>
                <p className="text-xs text-muted mt-0.5">
                  Camera-observed physical lamp states from CV detectors.
                </p>
              </div>
              <Badge variant="teal" dot>
                Vision AI
              </Badge>
            </div>

            {/* Discrepancy Warning if Camera != Controller */}
            {cvDiscrepancy && (
              <div className="p-3.5 rounded-xl bg-danger/15 border border-danger/30 text-xs text-danger mb-4 space-y-1">
                <div className="flex items-center gap-1.5 font-semibold">
                  <AlertTriangle className="w-4 h-4 text-danger shrink-0" />
                  <span>Optical State Discrepancy Detected!</span>
                </div>
                <p className="text-danger/90 leading-relaxed pl-5">
                  Camera observed <span className="font-mono uppercase font-bold">{cvDiscrepancy.cameraState}</span> ({formatPercent(cvDiscrepancy.cameraConf * 100)} conf), but controller reports <span className="font-mono uppercase font-bold">{cvDiscrepancy.controllerState}</span>. Possible bulb failure or camera occlusion.
                </p>
              </div>
            )}

            {visionLoading ? (
              <div className="py-12 flex flex-col items-center justify-center">
                <LoadingSpinner size="md" label="Fetching camera detections..." />
              </div>
            ) : visionIsError ? (
              <ErrorState
                title="Vision Feed Offline"
                message={visionError?.message || "Could not retrieve optical signal observations."}
                onRetry={refetchVision}
              />
            ) : !visionObservations?.items || visionObservations.items.length === 0 ? (
              <EmptyState
                icon={<Camera className="w-7 h-7 text-muted" />}
                title="No Optical Observations"
                description={`No optical camera detections logged for junction #${selectedJunctionId}.`}
              />
            ) : (
              <div className="space-y-3">
                {visionObservations.items.map((obs) => {
                  const styles = getPhaseColorStyles(obs.observed_state);
                  const confPct = Math.round((obs.observed_confidence ?? 0) * 100);

                  return (
                    <div
                      key={obs.signal_id + (obs.observed_at || "")}
                      className="p-3.5 rounded-xl bg-ink/60 border border-white/10 space-y-2 hover:border-white/20 transition-colors"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <span className="font-mono text-xs font-semibold text-text">
                            {obs.signal_code}
                          </span>
                          <span className="text-[10px] text-muted block font-mono">
                            {obs.intersection_name || `Junction #${obs.intersection_id}`}
                          </span>
                        </div>

                        {/* Lamp pill */}
                        <span
                          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-mono uppercase border font-medium ${styles.pill}`}
                        >
                          <span className={`w-1.5 h-1.5 rounded-full ${styles.dot}`} />
                          {obs.observed_state}
                        </span>
                      </div>

                      {/* Confidence Meter */}
                      <div>
                        <div className="flex items-center justify-between text-[11px] mb-1 font-mono">
                          <span className="text-muted">Model Confidence</span>
                          <span className="text-accent font-medium">{confPct}%</span>
                        </div>
                        <div className="h-1.5 rounded-full bg-ink overflow-hidden border border-white/5">
                          <div
                            style={{ width: `${confPct}%` }}
                            className="h-full bg-accent transition-all rounded-full"
                          />
                        </div>
                      </div>

                      <div className="flex items-center justify-between text-[10px] text-muted font-mono pt-1 border-t border-white/5">
                        <span>Capture Time:</span>
                        <span>{formatDateTime(obs.observed_at)}</span>
                      </div>
                    </div>
                  );
                })}

                {visionObservations.pages > 1 && (
                  <Pagination
                    page={visionPage}
                    totalPages={visionObservations.pages}
                    totalRecords={visionObservations.total}
                    perPage={20}
                    onPageChange={setVisionPage}
                    recordLabel="observations"
                  />
                )}
              </div>
            )}
          </Card>

          {/* Quick Guidance Box */}
          <Card className="p-4 bg-surface/50 border-white/5 text-xs text-muted space-y-2 leading-relaxed">
            <div className="flex items-center gap-2 text-text font-semibold">
              <Info className="w-4 h-4 text-accent" />
              <span>NTCIP Operational Guidance</span>
            </div>
            <p>
              • Phase modifications take effect at the start of the next ring cycle interval.
            </p>
            <p>
              • Direct overrides immediately interrupt standard coordination splits and require mandatory reason logging.
            </p>
            <p>
              • Signal observations reflect real-time CNN optical inference from connected roadside CCTV feeds.
            </p>
          </Card>
        </div>
      </div>
    </div>
  );
}

export default function SignalsPage() {
  return (
    <Suspense fallback={<LoadingSpinner size="lg" fullPage label="Loading signals console..." />}>
      <SignalsPageContent />
    </Suspense>
  );
}
