"use client";

import React, { useState, useMemo, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Siren,
  ShieldAlert,
  Flame,
  Shield,
  Truck,
  Car,
  Clock,
  MapPin,
  RefreshCw,
  RotateCcw,
  Plus,
  X,
  ChevronLeft,
  ChevronRight,
  ArrowRight,
  CheckCircle2,
  AlertTriangle,
  Radio,
  SlidersHorizontal,
  Navigation,
  Compass,
  Zap,
  Activity,
  Layers,
  Sparkles,
} from "lucide-react";
import { useApiQuery, useApiMutation } from "@/lib/use-api";
import { useTopic } from "@/lib/realtime";
import { Card } from "@/components/ui/Card";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { RequireRole } from "@/components/RequireRole";
import { useAuth } from "@/lib/auth";
import {
  formatDateTime,
  formatRelativeTime,
  formatSeconds,
} from "@/lib/format";

// --- Types matching backend schemas (backend/app/schemas/emergency.py & control.py) ---

export interface EmergencyEventItem {
  id: number;
  incident_id?: number | null;
  intersection_id?: number | null;
  vehicle_type: string;
  priority: number;
  status: "active" | "dispatched" | "on_scene" | "resolved" | string;
  detected_at: string;
  cleared_at?: string | null;
  created_at: string;
  updated_at: string;
}

interface PaginatedEmergencyEvents {
  items: EmergencyEventItem[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

interface JunctionOption {
  id: number;
  name: string;
  code: string;
}

interface PaginatedJunctions {
  items: JunctionOption[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

interface CorridorSignalAction {
  intersection_id: number;
  signal_id?: number | null;
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

interface GreenCorridorRecommendResponse {
  corridor_plan: GreenCorridorPlan;
  is_recommendation: boolean;
  note: string;
}

interface EmergencyEventCreatePayload {
  vehicle_type: string;
  priority: number;
  status: string;
  intersection_id?: number | null;
  incident_id?: number | null;
}

interface EmergencyEventUpdatePayload {
  priority?: number;
  status?: string;
  cleared_at?: string | null;
}

function getPriorityBadge(priority: number): {
  variant: BadgeVariant;
  label: string;
} {
  switch (priority) {
    case 1:
      return { variant: "danger", label: "P1 — Critical" };
    case 2:
      return { variant: "amber", label: "P2 — High" };
    case 3:
      return { variant: "teal", label: "P3 — Medium" };
    case 4:
      return { variant: "muted", label: "P4 — Low" };
    case 5:
      return { variant: "muted", label: "P5 — Routine" };
    default:
      return { variant: "muted", label: `P${priority}` };
  }
}

function getStatusBadge(status: string): {
  variant: BadgeVariant;
  label: string;
} {
  switch (status.toLowerCase()) {
    case "active":
      return { variant: "amber", label: "Active" };
    case "dispatched":
      return { variant: "teal", label: "Dispatched" };
    case "on_scene":
      return { variant: "teal", label: "On Scene" };
    case "resolved":
      return { variant: "success", label: "Resolved" };
    default:
      return { variant: "muted", label: status };
  }
}

function getVehicleIcon(vehicleType: string) {
  const norm = vehicleType.toLowerCase();
  if (norm.includes("fire")) {
    return <Flame className="w-4 h-4 text-danger" />;
  }
  if (norm.includes("police")) {
    return <Shield className="w-4 h-4 text-accent" />;
  }
  if (norm.includes("ambulance") || norm.includes("medic")) {
    return <Siren className="w-4 h-4 text-amber" />;
  }
  return <Truck className="w-4 h-4 text-text" />;
}

export default function EmergencyPage() {
  const queryClient = useQueryClient();
  const { user, canWrite } = useAuth();

  // Filters & Pagination
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [priorityFilter, setPriorityFilter] = useState<string>("all");
  const [page, setPage] = useState<number>(1);
  const perPage = 15;

  // Active Green Corridor Visualization State
  const [activeCorridorPlan, setActiveCorridorPlan] = useState<GreenCorridorPlan | null>(null);
  const [activeCorridorSourceEventId, setActiveCorridorSourceEventId] = useState<number | null>(null);

  // Modals & Panels
  const [isDispatchModalOpen, setIsDispatchModalOpen] = useState<boolean>(false);
  const [prioritizeEvent, setPrioritizeEvent] = useState<EmergencyEventItem | null>(null);
  const [selectedDestinationId, setSelectedDestinationId] = useState<string>("");
  const [isPlannerOpen, setIsPlannerOpen] = useState<boolean>(false);

  // Standalone corridor planner state
  const [planFromId, setPlanFromId] = useState<string>("");
  const [planToId, setPlanToId] = useState<string>("");
  const [planSpeed, setPlanSpeed] = useState<number>(60);

  // Feedback notifications
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Dispatch Form State
  const [newVehicleType, setNewVehicleType] = useState<string>("Ambulance");
  const [newPriority, setNewPriority] = useState<number>(1);
  const [newStatus, setNewStatus] = useState<string>("active");
  const [newIntersectionId, setNewIntersectionId] = useState<string>("");
  const [newIncidentId, setNewIncidentId] = useState<string>("");
  const [dispatchFormError, setDispatchFormError] = useState<string | null>(null);

  // 1. Fetch Junctions
  const { data: junctionsData } = useApiQuery<PaginatedJunctions>({
    queryKey: ["junctions-list-emergency"],
    endpoint: "/junctions",
    params: { per_page: 100 },
    queryOptions: {
      staleTime: 60000,
    },
  });

  const junctionMap = useMemo(() => {
    const map = new Map<number, JunctionOption>();
    junctionsData?.items?.forEach((j) => map.set(j.id, j));
    return map;
  }, [junctionsData]);

  // 2. Fetch Paginated Emergency Events
  const queryParams = useMemo(() => {
    const params: Record<string, string | number> = {
      page,
      per_page: perPage,
    };
    if (statusFilter !== "all") {
      params.status = statusFilter;
    }
    if (priorityFilter !== "all") {
      params.priority = Number(priorityFilter);
    }
    return params;
  }, [page, perPage, statusFilter, priorityFilter]);

  // Real-time invalidations: emergency.created and emergency.updated update emergency events list (replaces 15s poll)
  useTopic("emergency.created", () => {
    queryClient.invalidateQueries({ queryKey: ["emergency-events-list"] });
  });

  useTopic("emergency.updated", () => {
    queryClient.invalidateQueries({ queryKey: ["emergency-events-list"] });
  });

  const {
    data: eventsData,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useApiQuery<PaginatedEmergencyEvents>({
    queryKey: ["emergency-events-list", page, perPage, statusFilter, priorityFilter],
    endpoint: "/emergency-events",
    params: queryParams,
  });

  // Mutations
  const createEventMutation = useApiMutation<EmergencyEventItem, EmergencyEventCreatePayload>({
    endpoint: "/emergency-events",
    method: "POST",
    mutationOptions: {
      onSuccess: (created) => {
        setActionSuccess(`Emergency dispatch event #${created.id} (${created.vehicle_type}) created.`);
        setActionError(null);
        queryClient.invalidateQueries({ queryKey: ["emergency-events-list"] });
        setIsDispatchModalOpen(false);
        // Reset form
        setNewVehicleType("Ambulance");
        setNewPriority(1);
        setNewStatus("active");
        setNewIntersectionId("");
        setNewIncidentId("");
        setDispatchFormError(null);
      },
      onError: (err) => {
        setDispatchFormError(err.message || "Failed to dispatch emergency event.");
      },
    },
  });

  const updateEventMutation = useApiMutation<EmergencyEventItem, { id: number; data: EmergencyEventUpdatePayload }>({
    endpoint: ({ id }) => `/emergency-events/${id}`,
    method: "PATCH",
    mutationOptions: {
      onSuccess: (updated) => {
        setActionSuccess(`Emergency event #${updated.id} transitioned to "${updated.status}".`);
        setActionError(null);
        queryClient.invalidateQueries({ queryKey: ["emergency-events-list"] });
      },
      onError: (err) => {
        setActionError(err.message || "Failed to update emergency event status.");
        setActionSuccess(null);
      },
    },
  });

  const prioritizeMutation = useApiMutation<
    EmergencyPrioritizeResponse,
    { emergency_event_id: number; destination_intersection_id: number }
  >({
    endpoint: "/control/emergency/prioritize",
    method: "POST",
    mutationOptions: {
      onSuccess: (res, vars) => {
        setActiveCorridorPlan(res.corridor_plan);
        setActiveCorridorSourceEventId(vars.emergency_event_id);
        setActionSuccess(
          `Advisory green wave corridor "${res.corridor_plan.corridor_id}" activated across ${res.corridor_plan.path.length} junctions. ETA: ${res.corridor_plan.estimated_minutes.toFixed(1)} mins.`
        );
        setActionError(null);
        setPrioritizeEvent(null);
        setSelectedDestinationId("");
        queryClient.invalidateQueries({ queryKey: ["emergency-events-list"] });
      },
      onError: (err) => {
        setActionError(err.message || "Failed to activate emergency preemption green corridor.");
        setActionSuccess(null);
      },
    },
  });

  const restoreMutation = useApiMutation<EmergencyRestoreResponse, { emergency_event_id: number }>({
    endpoint: "/control/emergency/restore",
    method: "POST",
    mutationOptions: {
      onSuccess: (res) => {
        setActionSuccess(`Signal controllers restored to standard cycle. Event #${res.emergency_event_id} marked resolved.`);
        setActionError(null);
        setActiveCorridorPlan(null);
        setActiveCorridorSourceEventId(null);
        queryClient.invalidateQueries({ queryKey: ["emergency-events-list"] });
      },
      onError: (err) => {
        setActionError(err.message || "Failed to restore standard signal timing.");
        setActionSuccess(null);
      },
    },
  });

  const recommendMutation = useApiMutation<
    GreenCorridorRecommendResponse,
    { from_intersection_id: number; to_intersection_id: number; emergency_speed_kmh: number }
  >({
    endpoint: "/control/green-corridor/recommend",
    method: "POST",
    mutationOptions: {
      onSuccess: (res) => {
        setActiveCorridorPlan(res.corridor_plan);
        setActiveCorridorSourceEventId(null);
        setActionSuccess(
          `Advisory candidate corridor calculated: ${res.corridor_plan.path.length} junctions, ETA: ${res.corridor_plan.estimated_minutes.toFixed(1)} min.`
        );
        setActionError(null);
      },
      onError: (err) => {
        setActionError(err.message || "No viable emergency path found between selected junctions.");
        setActionSuccess(null);
      },
    },
  });

  // Reset page when filter changes
  const handleFilterChange = (setter: (v: string) => void, val: string) => {
    setter(val);
    setPage(1);
  };

  const handleResetFilters = () => {
    setStatusFilter("all");
    setPriorityFilter("all");
    setPage(1);
  };

  const hasActiveFilters = statusFilter !== "all" || priorityFilter !== "all";

  // Dispatch Form Submit
  const handleDispatchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setDispatchFormError(null);

    if (!newVehicleType.trim()) {
      setDispatchFormError("Vehicle type is required.");
      return;
    }

    const payload: EmergencyEventCreatePayload = {
      vehicle_type: newVehicleType.trim(),
      priority: Number(newPriority),
      status: newStatus,
    };

    if (newIntersectionId) {
      payload.intersection_id = Number(newIntersectionId);
    }

    if (newIncidentId) {
      const incNum = parseInt(newIncidentId, 10);
      if (isNaN(incNum)) {
        setDispatchFormError("Linked Incident ID must be an integer.");
        return;
      }
      payload.incident_id = incNum;
    }

    createEventMutation.mutate(payload);
  };

  // Prioritize Submit
  const handlePrioritizeSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!prioritizeEvent) return;

    if (!selectedDestinationId) {
      setActionError("Please select a destination junction for the emergency route.");
      return;
    }

    const destId = Number(selectedDestinationId);
    if (prioritizeEvent.intersection_id && destId === prioritizeEvent.intersection_id) {
      setActionError("Destination junction must be different from origin junction.");
      return;
    }

    prioritizeMutation.mutate({
      emergency_event_id: prioritizeEvent.id,
      destination_intersection_id: destId,
    });
  };

  // Standalone corridor preview submit
  const handleRecommendSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!planFromId || !planToId) {
      setActionError("Please select both origin and destination junctions.");
      return;
    }
    if (planFromId === planToId) {
      setActionError("Origin and destination junctions must differ.");
      return;
    }

    recommendMutation.mutate({
      from_intersection_id: Number(planFromId),
      to_intersection_id: Number(planToId),
      emergency_speed_kmh: Number(planSpeed) || 60,
    });
  };

  // Offline handling
  const isNetworkOffline = isError && !eventsData && error?.status === 0;

  if (isNetworkOffline) {
    return (
      <div className="max-w-7xl mx-auto space-y-6">
        <ErrorState
          title="Emergency Dispatch Gateway Unreachable"
          message="Failed to connect to /api/v1/emergency-events. Verify backend service availability on port 8000."
          onRetry={() => refetch()}
          retryText="Retry Connection"
        />
      </div>
    );
  }

  const items = eventsData?.items || [];
  const totalItems = eventsData?.total || 0;
  const totalPages = eventsData?.pages || 1;

  // Stat summary counters
  const activeEventsCount = items.filter((e) => e.status === "active").length;
  const dispatchedEventsCount = items.filter((e) => e.status === "dispatched").length;
  const onSceneEventsCount = items.filter((e) => e.status === "on_scene").length;
  const resolvedEventsCount = items.filter((e) => e.status === "resolved").length;

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5 mb-1.5 flex-wrap">
            <h1 className="text-2xl sm:text-3xl font-display font-bold text-text tracking-tight">
              Emergency & Green-Corridor
            </h1>
            <Badge variant="danger" dot>
              Preemption Wave Engine
            </Badge>
            <span className="text-xs text-muted font-mono">
              NTCIP 1202 Signal Priority
            </span>
          </div>
          <p className="text-xs sm:text-sm text-muted max-w-2xl leading-relaxed">
            Coordinated emergency transit routing, acoustic/optical preemption, and automated green-wave corridor actuation.
          </p>
        </div>

        <div className="flex items-center gap-3 self-start md:self-auto flex-wrap">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => refetch()}
            disabled={isLoading || isFetching}
            className="gap-1.5"
          >
            <RefreshCw
              className={`w-3.5 h-3.5 ${isFetching ? "animate-spin" : ""}`}
            />
            <span className="hidden sm:inline">Refresh</span>
          </Button>

          <Button
            variant="secondary"
            size="sm"
            onClick={() => setIsPlannerOpen(!isPlannerOpen)}
            className="gap-1.5 border-accent/30 text-accent hover:border-accent"
          >
            <Compass className="w-4 h-4" />
            <span>{isPlannerOpen ? "Close Planner" : "Corridor Planner"}</span>
          </Button>

          {canWrite() ? (
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                setDispatchFormError(null);
                setIsDispatchModalOpen(true);
              }}
              className="gap-1.5"
            >
              <Plus className="w-4 h-4" />
              <span>Dispatch Emergency Vehicle</span>
            </Button>
          ) : (
            <Badge variant="muted" className="text-xs py-1 px-3">
              Analyst (Read-Only)
            </Badge>
          )}
        </div>
      </div>

      {/* Global Alerts / Status Banner */}
      {actionSuccess && (
        <div className="p-3.5 rounded-xl bg-success/10 border border-success/30 text-success text-xs sm:text-sm flex items-center justify-between animate-in fade-in">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            <span>{actionSuccess}</span>
          </div>
          <button
            onClick={() => setActionSuccess(null)}
            className="text-success hover:opacity-80 p-1"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {actionError && (
        <div className="p-3.5 rounded-xl bg-danger/10 border border-danger/30 text-danger text-xs sm:text-sm flex items-center justify-between animate-in fade-in">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>{actionError}</span>
          </div>
          <button
            onClick={() => setActionError(null)}
            className="text-danger hover:opacity-80 p-1"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Overview Stat Counters */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4">
        <Card className="p-4 bg-surface/70 border-white/10">
          <div className="text-[11px] font-medium text-amber uppercase tracking-wider">
            Active Calls
          </div>
          <div className="mt-1 font-display text-2xl font-bold text-amber">
            {activeEventsCount}
          </div>
          <div className="text-[10px] text-muted mt-0.5">Pending preemption wave</div>
        </Card>

        <Card className="p-4 bg-surface/70 border-white/10">
          <div className="text-[11px] font-medium text-accent uppercase tracking-wider">
            Dispatched Waves
          </div>
          <div className="mt-1 font-display text-2xl font-bold text-accent">
            {dispatchedEventsCount}
          </div>
          <div className="text-[10px] text-muted mt-0.5">Corridor preemption active</div>
        </Card>

        <Card className="p-4 bg-surface/70 border-white/10">
          <div className="text-[11px] font-medium text-text uppercase tracking-wider">
            On Scene
          </div>
          <div className="mt-1 font-display text-2xl font-bold text-text">
            {onSceneEventsCount}
          </div>
          <div className="text-[10px] text-muted mt-0.5">Units arrived at target</div>
        </Card>

        <Card className="p-4 bg-surface/70 border-white/10">
          <div className="text-[11px] font-medium text-success uppercase tracking-wider">
            Resolved
          </div>
          <div className="mt-1 font-display text-2xl font-bold text-success">
            {resolvedEventsCount}
          </div>
          <div className="text-[10px] text-muted mt-0.5">Corridors cleared</div>
        </Card>
      </div>

      {/* STANDALONE CORRIDOR SIMULATION / PLANNER ACCORDION */}
      {isPlannerOpen && (
        <Card className="p-5 border-accent/30 bg-surface/80 space-y-4 animate-in slide-in-from-top-3">
          <div className="flex items-center justify-between border-b border-white/10 pb-3">
            <div className="flex items-center gap-2">
              <Compass className="w-5 h-5 text-accent" />
              <h2 className="font-display font-semibold text-text text-base">
                Green Corridor Routing & Wave Simulator (Read-Only)
              </h2>
            </div>
            <button
              onClick={() => setIsPlannerOpen(false)}
              className="text-muted hover:text-text p-1"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <p className="text-xs text-muted max-w-2xl leading-relaxed">
            Calculate and inspect graph-based emergency green wave preemption routes without altering active controller configurations. Evaluates timing budgets and phase conflict bounds.
          </p>

          <form onSubmit={handleRecommendSubmit} className="grid grid-cols-1 sm:grid-cols-4 gap-3 text-xs">
            <div>
              <label className="block text-muted mb-1 font-medium">Origin Junction *</label>
              <select
                value={planFromId}
                onChange={(e) => setPlanFromId(e.target.value)}
                className="w-full bg-ink border border-white/15 rounded-xl px-3 py-2 text-text text-xs focus:outline-none focus:border-accent"
              >
                <option value="">Select Origin...</option>
                {junctionsData?.items?.map((j) => (
                  <option key={j.id} value={j.id}>
                    #{j.id} — {j.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-muted mb-1 font-medium">Destination Junction *</label>
              <select
                value={planToId}
                onChange={(e) => setPlanToId(e.target.value)}
                className="w-full bg-ink border border-white/15 rounded-xl px-3 py-2 text-text text-xs focus:outline-none focus:border-accent"
              >
                <option value="">Select Destination...</option>
                {junctionsData?.items?.map((j) => (
                  <option key={j.id} value={j.id}>
                    #{j.id} — {j.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-muted mb-1 font-medium">Cruising Speed (km/h)</label>
              <input
                type="number"
                min={20}
                max={120}
                value={planSpeed}
                onChange={(e) => setPlanSpeed(Number(e.target.value))}
                className="w-full bg-ink border border-white/15 rounded-xl px-3 py-2 text-text text-xs focus:outline-none focus:border-accent font-mono"
              />
            </div>

            <div className="flex items-end">
              <Button
                type="submit"
                variant="primary"
                size="sm"
                disabled={recommendMutation.isPending}
                className="w-full"
              >
                {recommendMutation.isPending ? "Computing..." : "Simulate Corridor"}
              </Button>
            </div>
          </form>
        </Card>
      )}

      {/* ACTIVE GREEN CORRIDOR ROUTE VISUALIZATION */}
      {activeCorridorPlan && (
        <Card className="p-5 sm:p-6 border-accent/40 bg-accent/5 space-y-5 animate-in fade-in">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-white/10 pb-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-accent/20 border border-accent/40 flex items-center justify-center text-accent shrink-0">
                <Zap className="w-5 h-5" />
              </div>
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <h2 className="font-display font-bold text-text text-base sm:text-lg">
                    Green-Corridor Route: {activeCorridorPlan.corridor_id}
                  </h2>
                  <Badge variant="teal" dot>
                    Active Wave
                  </Badge>
                  {activeCorridorSourceEventId && (
                    <Badge variant="amber" className="font-mono text-xs">
                      Event #{activeCorridorSourceEventId}
                    </Badge>
                  )}
                </div>
                <p className="text-xs text-muted mt-0.5">
                  Ordered sequential green wave preemption path. Estimated traversal time:{" "}
                  <span className="font-mono text-accent font-semibold">
                    {activeCorridorPlan.estimated_minutes.toFixed(2)} min ({Math.round(activeCorridorPlan.estimated_minutes * 60)}s)
                  </span>
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 self-start sm:self-auto">
              {activeCorridorSourceEventId && canWrite() && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => restoreMutation.mutate({ emergency_event_id: activeCorridorSourceEventId })}
                  disabled={restoreMutation.isPending}
                  className="border-danger/40 text-danger hover:bg-danger/10"
                >
                  <RotateCcw className="w-3.5 h-3.5 mr-1" />
                  <span>Restore Standard Signals</span>
                </Button>
              )}

              <button
                onClick={() => {
                  setActiveCorridorPlan(null);
                  setActiveCorridorSourceEventId(null);
                }}
                className="w-8 h-8 rounded-lg bg-surface border border-white/10 flex items-center justify-center text-muted hover:text-text"
                title="Dismiss Corridor View"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Sequential Junction Nodes Path Visualization */}
          <div className="space-y-3">
            <div className="text-xs uppercase tracking-wider font-semibold text-muted flex items-center gap-1.5">
              <Navigation className="w-3.5 h-3.5 text-accent" />
              <span>Coordinated Wave Path ({activeCorridorPlan.path.length} Junctions):</span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {activeCorridorPlan.path.map((nodeId, idx) => {
                const junc = junctionMap.get(nodeId);
                const action = activeCorridorPlan.signal_actions.find(
                  (a) => a.intersection_id === nodeId
                );
                const isOrigin = idx === 0;
                const isDest = idx === activeCorridorPlan.path.length - 1;

                return (
                  <Card
                    key={`${nodeId}-${idx}`}
                    className={`p-3.5 border ${
                      isOrigin
                        ? "border-amber/40 bg-amber/5"
                        : isDest
                        ? "border-success/40 bg-success/5"
                        : "border-white/10 bg-surface/70"
                    } relative overflow-hidden`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="w-6 h-6 rounded-full bg-ink/70 border border-white/10 flex items-center justify-center text-xs font-mono font-bold text-accent">
                          {idx + 1}
                        </span>
                        <div>
                          <div className="font-semibold text-text text-xs">
                            {junc?.name || `Junction #${nodeId}`}
                          </div>
                          <div className="text-[10px] font-mono text-muted">
                            #{nodeId} {junc?.code ? `• ${junc.code}` : ""}
                          </div>
                        </div>
                      </div>

                      {isOrigin && (
                        <Badge variant="amber" className="text-[9px]">
                          Origin
                        </Badge>
                      )}
                      {isDest && (
                        <Badge variant="success" className="text-[9px]">
                          Destination
                        </Badge>
                      )}
                    </div>

                    {/* Preemption Directive */}
                    {action && (
                      <div className="mt-2.5 pt-2 border-t border-white/5 space-y-1 text-[11px]">
                        <div className="flex items-center justify-between">
                          <span className="text-muted font-medium">Directive:</span>
                          <span className="font-mono text-accent font-semibold uppercase">
                            {action.action}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-muted font-medium">Duration:</span>
                          <span className="font-mono text-text">
                            {formatSeconds(action.duration_seconds)}
                          </span>
                        </div>
                        <div className="text-[10px] text-muted italic line-clamp-1">
                          {action.reason}
                        </div>
                      </div>
                    )}
                  </Card>
                );
              })}
            </div>
          </div>
        </Card>
      )}

      {/* FILTER CONTROLS BAR */}
      <div className="bg-surface/60 p-4 rounded-2xl border border-white/10 flex flex-col md:flex-row md:items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 text-xs font-medium text-muted uppercase tracking-wider">
          <Activity className="w-3.5 h-3.5 text-accent" />
          <span>Filter Events:</span>
        </div>

        <div className="flex items-center gap-2.5 flex-wrap flex-1 justify-start md:justify-end">
          {/* Status Filter */}
          <select
            value={statusFilter}
            onChange={(e) => handleFilterChange(setStatusFilter, e.target.value)}
            className="bg-ink/80 border border-white/15 rounded-xl px-3 py-1.5 text-xs font-medium text-text focus:outline-none focus:border-accent"
          >
            <option value="all">All Statuses</option>
            <option value="active">Active</option>
            <option value="dispatched">Dispatched</option>
            <option value="on_scene">On Scene</option>
            <option value="resolved">Resolved</option>
          </select>

          {/* Priority Filter */}
          <select
            value={priorityFilter}
            onChange={(e) => handleFilterChange(setPriorityFilter, e.target.value)}
            className="bg-ink/80 border border-white/15 rounded-xl px-3 py-1.5 text-xs font-medium text-text focus:outline-none focus:border-accent"
          >
            <option value="all">All Priorities</option>
            <option value="1">Priority 1 (Critical)</option>
            <option value="2">Priority 2 (High)</option>
            <option value="3">Priority 3 (Medium)</option>
            <option value="4">Priority 4 (Low)</option>
            <option value="5">Priority 5 (Routine)</option>
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

      {/* EMERGENCY EVENTS TABLE */}
      {isLoading && items.length === 0 ? (
        <Card className="p-12 text-center flex flex-col items-center justify-center min-h-[350px]">
          <LoadingSpinner size="lg" label="Loading emergency dispatch records..." />
        </Card>
      ) : isError ? (
        <ErrorState
          title="Failed to Load Emergency Events"
          message={error?.message || "An unexpected error occurred while fetching emergency records."}
          onRetry={() => refetch()}
        />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Siren className="w-8 h-8 text-muted" />}
          title="No Emergency Events"
          description={
            hasActiveFilters
              ? "No emergency events match your filter criteria. Try resetting filters."
              : "No active emergency vehicle dispatches on record."
          }
          action={
            hasActiveFilters
              ? {
                  label: "Reset Filter Criteria",
                  onClick: handleResetFilters,
                }
              : canWrite()
              ? {
                  label: "Dispatch Emergency Vehicle",
                  onClick: () => setIsDispatchModalOpen(true),
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
                  <th className="py-3 px-3.5">ID / Detected</th>
                  <th className="py-3 px-3.5">Vehicle Type</th>
                  <th className="py-3 px-3.5">Priority</th>
                  <th className="py-3 px-3.5">Status</th>
                  <th className="py-3 px-3.5">Origin Junction</th>
                  <th className="py-3 px-3.5">Linked Incident</th>
                  <th className="py-3 px-3.5">Cleared At</th>
                  <th className="py-3 px-3.5 text-right">Preemption Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {items.map((event) => {
                  const prioBadge = getPriorityBadge(event.priority);
                  const statBadge = getStatusBadge(event.status);
                  const junc = event.intersection_id
                    ? junctionMap.get(event.intersection_id)
                    : null;

                  return (
                    <tr
                      key={event.id}
                      className="hover:bg-white/5 transition-colors group"
                    >
                      {/* ID / Detected */}
                      <td className="py-3 px-3.5 align-top">
                        <div className="font-mono font-medium text-text flex items-center gap-1">
                          #{event.id}
                        </div>
                        <div className="text-[11px] text-muted flex items-center gap-1 mt-0.5">
                          <Clock className="w-3 h-3 text-muted/70 flex-shrink-0" />
                          <span>{formatRelativeTime(event.detected_at)}</span>
                        </div>
                        <div className="text-[10px] text-muted/70 font-mono mt-0.5">
                          {formatDateTime(event.detected_at)}
                        </div>
                      </td>

                      {/* Vehicle Type */}
                      <td className="py-3 px-3.5 align-top">
                        <div className="flex items-center gap-2">
                          <div className="w-7 h-7 rounded-lg bg-surface/90 border border-white/10 flex items-center justify-center shrink-0">
                            {getVehicleIcon(event.vehicle_type)}
                          </div>
                          <div>
                            <span className="font-medium text-text capitalize block">
                              {event.vehicle_type}
                            </span>
                          </div>
                        </div>
                      </td>

                      {/* Priority */}
                      <td className="py-3 px-3.5 align-top">
                        <Badge variant={prioBadge.variant} className="text-[10px]">
                          {prioBadge.label}
                        </Badge>
                      </td>

                      {/* Status */}
                      <td className="py-3 px-3.5 align-top">
                        <Badge variant={statBadge.variant} dot className="text-[10px]">
                          {statBadge.label}
                        </Badge>
                      </td>

                      {/* Origin Junction */}
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
                        ) : event.intersection_id ? (
                          <span className="font-mono text-muted">
                            Junction #{event.intersection_id}
                          </span>
                        ) : (
                          <span className="text-muted italic">Non-junction dispatch</span>
                        )}
                      </td>

                      {/* Linked Incident */}
                      <td className="py-3 px-3.5 align-top">
                        {event.incident_id ? (
                          <span className="font-mono text-accent">
                            Incident #{event.incident_id}
                          </span>
                        ) : (
                          <span className="text-muted font-mono">—</span>
                        )}
                      </td>

                      {/* Cleared At */}
                      <td className="py-3 px-3.5 align-top">
                        {event.cleared_at ? (
                          <div className="text-success font-mono text-[11px] flex items-center gap-1">
                            <CheckCircle2 className="w-3 h-3" />
                            <span>{formatRelativeTime(event.cleared_at)}</span>
                          </div>
                        ) : (
                          <span className="text-muted font-mono">—</span>
                        )}
                      </td>

                      {/* Preemption Actions */}
                      <td className="py-3 px-3.5 align-top text-right">
                        <div className="flex items-center justify-end gap-1.5 flex-wrap">
                          {canWrite() && event.status !== "resolved" && (
                            <>
                              {/* Prioritize Corridor Button */}
                              <Button
                                variant="secondary"
                                size="sm"
                                onClick={() => {
                                  setPrioritizeEvent(event);
                                  setSelectedDestinationId("");
                                }}
                                className="px-2.5 py-1 text-[11px] border-accent/40 text-accent hover:bg-accent/10"
                                title="Prioritize Green Corridor"
                              >
                                <Zap className="w-3 h-3 mr-1" />
                                <span>Prioritize</span>
                              </Button>

                              {/* Restore Button if dispatched */}
                              {event.status === "dispatched" && (
                                <Button
                                  variant="secondary"
                                  size="sm"
                                  onClick={() => restoreMutation.mutate({ emergency_event_id: event.id })}
                                  disabled={restoreMutation.isPending}
                                  className="px-2 py-1 text-[10px] border-danger/40 text-danger hover:bg-danger/10"
                                  title="Restore Signal Coordination"
                                >
                                  <RotateCcw className="w-3 h-3 mr-1" />
                                  <span>Restore</span>
                                </Button>
                              )}

                              {/* Status Transition Shortcut */}
                              {event.status === "active" && (
                                <button
                                  type="button"
                                  onClick={() => updateEventMutation.mutate({ id: event.id, data: { status: "dispatched" } })}
                                  className="px-2 py-1 rounded bg-white/5 hover:bg-white/10 text-muted hover:text-text text-[10px]"
                                  title="Mark Dispatched"
                                >
                                  Dispatched
                                </button>
                              )}

                              {event.status === "dispatched" && (
                                <button
                                  type="button"
                                  onClick={() => updateEventMutation.mutate({ id: event.id, data: { status: "on_scene" } })}
                                  className="px-2 py-1 rounded bg-white/5 hover:bg-white/10 text-muted hover:text-text text-[10px]"
                                  title="Mark On Scene"
                                >
                                  On Scene
                                </button>
                              )}

                              {event.status === "on_scene" && (
                                <button
                                  type="button"
                                  onClick={() => updateEventMutation.mutate({ id: event.id, data: { status: "resolved" } })}
                                  className="px-2 py-1 rounded bg-success/15 hover:bg-success/25 text-success text-[10px]"
                                  title="Mark Resolved"
                                >
                                  Resolve
                                </button>
                              )}
                            </>
                          )}

                          {event.status === "resolved" && (
                            <span className="text-[11px] text-muted font-mono">
                              Cleared
                            </span>
                          )}
                        </div>
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
              of <span className="font-mono text-text font-medium">{totalItems}</span> events
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

      {/* DISPATCH EMERGENCY VEHICLE MODAL */}
      {isDispatchModalOpen && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4"
        >
          <div
            onClick={() => setIsDispatchModalOpen(false)}
            className="fixed inset-0 bg-black/75 backdrop-blur-sm transition-opacity"
          />

          <div className="relative w-full max-w-lg bg-surface border border-white/15 rounded-2xl shadow-2xl p-6 z-10 space-y-5 animate-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between border-b border-white/10 pb-4">
              <div>
                <h2 className="text-lg font-display font-bold text-text">
                  Dispatch Emergency Vehicle
                </h2>
                <p className="text-xs text-muted mt-0.5">
                  Officer Operator: <span className="font-mono text-text">{user?.email}</span>
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsDispatchModalOpen(false)}
                className="w-8 h-8 rounded-lg bg-ink hover:bg-white/10 border border-white/10 flex items-center justify-center text-muted hover:text-text cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {dispatchFormError && (
              <div className="p-3 rounded-lg bg-danger/15 border border-danger/30 text-danger text-xs flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>{dispatchFormError}</span>
              </div>
            )}

            <form onSubmit={handleDispatchSubmit} className="space-y-4 text-xs">
              <div className="grid grid-cols-2 gap-3">
                {/* Vehicle Type */}
                <div>
                  <label className="block text-muted font-medium mb-1">
                    Vehicle Type *
                  </label>
                  <select
                    value={newVehicleType}
                    onChange={(e) => setNewVehicleType(e.target.value)}
                    className="w-full bg-ink border border-white/15 rounded-xl px-3 py-2 text-text text-xs focus:outline-none focus:border-accent"
                  >
                    <option value="Ambulance">Ambulance</option>
                    <option value="Fire Engine">Fire Engine</option>
                    <option value="Police Cruiser">Police Cruiser</option>
                    <option value="Rescue Unit">Rescue Unit</option>
                    <option value="Hazmat Squad">Hazmat Squad</option>
                  </select>
                </div>

                {/* Priority */}
                <div>
                  <label className="block text-muted font-medium mb-1">
                    Priority Tier *
                  </label>
                  <select
                    value={newPriority}
                    onChange={(e) => setNewPriority(Number(e.target.value))}
                    className="w-full bg-ink border border-white/15 rounded-xl px-3 py-2 text-text text-xs focus:outline-none focus:border-accent"
                  >
                    <option value={1}>1 — Critical Emergency</option>
                    <option value={2}>2 — High Priority</option>
                    <option value={3}>3 — Moderate Urgency</option>
                    <option value={4}>4 — Low Priority</option>
                    <option value={5}>5 — Routine Transit</option>
                  </select>
                </div>
              </div>

              {/* Origin Intersection */}
              <div>
                <label className="block text-muted font-medium mb-1">
                  Origin Intersection (Recommended for green corridor routing)
                </label>
                <select
                  value={newIntersectionId}
                  onChange={(e) => setNewIntersectionId(e.target.value)}
                  className="w-full bg-ink border border-white/15 rounded-xl px-3 py-2 text-text text-xs focus:outline-none focus:border-accent"
                >
                  <option value="">None / Open Roadway</option>
                  {junctionsData?.items?.map((j) => (
                    <option key={j.id} value={j.id}>
                      #{j.id} — {j.name} ({j.code})
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                {/* Linked Incident */}
                <div>
                  <label className="block text-muted font-medium mb-1">
                    Linked Incident ID (Optional)
                  </label>
                  <input
                    type="number"
                    value={newIncidentId}
                    onChange={(e) => setNewIncidentId(e.target.value)}
                    placeholder="e.g. 1"
                    className="w-full bg-ink border border-white/15 rounded-xl px-3 py-2 text-text text-xs focus:outline-none focus:border-accent font-mono placeholder:text-muted/60"
                  />
                </div>

                {/* Initial Status */}
                <div>
                  <label className="block text-muted font-medium mb-1">
                    Initial Status
                  </label>
                  <select
                    value={newStatus}
                    onChange={(e) => setNewStatus(e.target.value)}
                    className="w-full bg-ink border border-white/15 rounded-xl px-3 py-2 text-text text-xs focus:outline-none focus:border-accent"
                  >
                    <option value="active">Active</option>
                    <option value="dispatched">Dispatched</option>
                  </select>
                </div>
              </div>

              <div className="pt-3 border-t border-white/10 flex items-center justify-end gap-2.5">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setIsDispatchModalOpen(false)}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  disabled={createEventMutation.isPending}
                >
                  {createEventMutation.isPending ? "Dispatching..." : "Confirm Dispatch"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* PRIORITIZE CORRIDOR MODAL */}
      {prioritizeEvent && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4"
        >
          <div
            onClick={() => setPrioritizeEvent(null)}
            className="fixed inset-0 bg-black/75 backdrop-blur-sm transition-opacity"
          />

          <div className="relative w-full max-w-lg bg-surface border border-accent/40 rounded-2xl shadow-2xl p-6 z-10 space-y-5 animate-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between border-b border-white/10 pb-4">
              <div>
                <div className="flex items-center gap-2">
                  <Zap className="w-5 h-5 text-accent" />
                  <h2 className="text-lg font-display font-bold text-text">
                    Activate Green Wave Preemption
                  </h2>
                </div>
                <p className="text-xs text-muted mt-0.5">
                  Route coordination for Event #{prioritizeEvent.id} ({prioritizeEvent.vehicle_type})
                </p>
              </div>
              <button
                type="button"
                onClick={() => setPrioritizeEvent(null)}
                className="w-8 h-8 rounded-lg bg-ink hover:bg-white/10 border border-white/10 flex items-center justify-center text-muted hover:text-text cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-3.5 rounded-xl bg-ink/70 border border-white/5 space-y-2 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-muted">Origin Intersection:</span>
                <span className="font-medium text-text">
                  {prioritizeEvent.intersection_id
                    ? junctionMap.get(prioritizeEvent.intersection_id)?.name ||
                      `Junction #${prioritizeEvent.intersection_id}`
                    : "No origin junction on event record"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted">Priority Classification:</span>
                <Badge variant={getPriorityBadge(prioritizeEvent.priority).variant} className="text-[10px]">
                  Priority {prioritizeEvent.priority}
                </Badge>
              </div>
            </div>

            {!prioritizeEvent.intersection_id && (
              <div className="p-3 rounded-lg bg-amber/15 border border-amber/30 text-amber text-xs flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>
                  Notice: Event has no assigned origin junction. Route planner requires origin coordinates or linked junction to formulate corridor.
                </span>
              </div>
            )}

            <form onSubmit={handlePrioritizeSubmit} className="space-y-4 text-xs">
              <div>
                <label className="block text-muted font-medium mb-1">
                  Target Destination Junction *
                </label>
                <select
                  value={selectedDestinationId}
                  onChange={(e) => setSelectedDestinationId(e.target.value)}
                  className="w-full bg-ink border border-white/15 rounded-xl px-3 py-2 text-text text-xs focus:outline-none focus:border-accent"
                >
                  <option value="">Select Destination Junction...</option>
                  {junctionsData?.items?.map((j) => (
                    <option key={j.id} value={j.id}>
                      #{j.id} — {j.name} ({j.code})
                    </option>
                  ))}
                </select>
              </div>

              <div className="p-3 rounded-lg bg-surface/90 border border-white/10 text-muted text-[11px] leading-relaxed">
                <span className="text-accent font-semibold block mb-0.5">NTCIP Preemption Guarantee:</span>
                Actuates supervisory green splits along intermediate controllers while preserving authoritative minimum pedestrian and clearance safe bounds.
              </div>

              <div className="pt-3 border-t border-white/10 flex items-center justify-end gap-2.5">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setPrioritizeEvent(null)}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  disabled={prioritizeMutation.isPending || !selectedDestinationId}
                >
                  {prioritizeMutation.isPending ? "Actuating..." : "Engage Green Corridor"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
