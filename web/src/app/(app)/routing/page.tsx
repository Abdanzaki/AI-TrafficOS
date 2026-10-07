"use client";

import React, { useState, useMemo } from "react";
import Link from "next/link";
import {
  Route as RouteIcon,
  ArrowRight,
  ArrowLeftRight,
  RefreshCw,
  Sparkles,
  GitFork,
  Network,
  Activity,
  Sliders,
  ChevronDown,
  ChevronUp,
  AlertTriangle,
  Gauge,
  Navigation,
  ExternalLink,
  Flame,
} from "lucide-react";
import { useApiQuery, useApiMutation } from "@/lib/use-api";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatNumber, formatSeconds, getCongestionStatus } from "@/lib/format";

// --- Types matching backend schemas (backend/app/schemas/routing.py) ---

interface RouteEdgeResponse {
  road_id: number;
  from_intersection_id: number;
  to_intersection_id: number;
  length_km: number;
  cost_minutes: number;
}

interface RouteResponse {
  algorithm: string;
  path: number[];
  edges: RouteEdgeResponse[];
  total_cost_minutes: number;
  total_distance_km: number;
}

interface RouteRequest {
  from_intersection_id: number;
  to_intersection_id: number;
  algorithm: "dijkstra" | "astar";
  time_weight: number;
  congestion_weight: number;
  distance_weight: number;
  condition_weight: number;
}

interface CongestionRankingItem {
  road_id: number;
  road_name: string;
  from_intersection_id?: number | null;
  to_intersection_id?: number | null;
  congestion_level: number;
  rank: number;
}

interface GraphStatsResponse {
  intersection_count: number;
  road_count: number;
  directed_edge_count: number;
}

interface JunctionOption {
  id: number;
  name: string;
  code: string;
  city?: string | null;
  zone?: string | null;
}

interface PaginatedJunctions {
  items: JunctionOption[];
  total: number;
  page: number;
  per_page: number;
}

export default function RoutingPage() {
  // --- Form & Search State ---
  const [fromIntersectionId, setFromIntersectionId] = useState<string>("");
  const [toIntersectionId, setToIntersectionId] = useState<string>("");
  const [algorithm, setAlgorithm] = useState<"astar" | "dijkstra">("astar");
  const [rankingLimit, setRankingLimit] = useState<number>(10);
  const [showAdvancedWeights, setShowAdvancedWeights] = useState<boolean>(false);

  // Cost Profile Weights (defaults matching RouteRequest schema in backend)
  const [timeWeight, setTimeWeight] = useState<number>(1.0);
  const [congestionWeight, setCongestionWeight] = useState<number>(1.0);
  const [distanceWeight, setDistanceWeight] = useState<number>(0.15);
  const [conditionWeight, setConditionWeight] = useState<number>(0.5);

  const [formValidationMsg, setFormValidationMsg] = useState<string | null>(null);

  // --- API Query: Intersections List (for selectors) ---
  const {
    data: junctionsData,
    isLoading: junctionsLoading,
    error: junctionsError,
    refetch: refetchJunctions,
  } = useApiQuery<PaginatedJunctions>({
    queryKey: ["routing-junctions-list"],
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

  // --- API Query: Graph Stats ---
  const {
    data: graphStats,
    isLoading: statsLoading,
    error: statsError,
    refetch: refetchStats,
  } = useApiQuery<GraphStatsResponse>({
    queryKey: ["routing-graph-stats"],
    endpoint: "/routing/graph-stats",
    queryOptions: {
      staleTime: 30000,
    },
  });

  // --- API Query: Congestion Ranking ---
  const {
    data: congestionRanking,
    isLoading: rankingLoading,
    error: rankingError,
    refetch: refetchRanking,
  } = useApiQuery<CongestionRankingItem[]>({
    queryKey: ["routing-congestion-ranking", rankingLimit],
    endpoint: "/routing/congestion-ranking",
    params: { limit: rankingLimit },
    queryOptions: {
      refetchInterval: 20000,
    },
  });

  // --- API Mutation: Optimal Route Computation ---
  const {
    mutate: computeRoute,
    data: routeResult,
    isPending: isComputingRoute,
    error: routeError,
    reset: resetRoute,
  } = useApiMutation<RouteResponse, RouteRequest>({
    endpoint: "/routing/optimal-route",
    method: "POST",
  });

  // Handle route computation submit
  const handleCalculateRoute = (e?: React.FormEvent) => {
    e?.preventDefault();
    setFormValidationMsg(null);

    const fromId = Number(fromIntersectionId);
    const toId = Number(toIntersectionId);

    if (!fromIntersectionId || isNaN(fromId)) {
      setFormValidationMsg("Please select an origin junction.");
      return;
    }
    if (!toIntersectionId || isNaN(toId)) {
      setFormValidationMsg("Please select a destination junction.");
      return;
    }
    if (fromId === toId) {
      setFormValidationMsg("Origin and destination junctions must be different.");
      return;
    }

    computeRoute({
      from_intersection_id: fromId,
      to_intersection_id: toId,
      algorithm,
      time_weight: timeWeight,
      congestion_weight: congestionWeight,
      distance_weight: distanceWeight,
      condition_weight: conditionWeight,
    });
  };

  // Swap origin and destination
  const handleSwapJunctions = () => {
    const prevFrom = fromIntersectionId;
    setFromIntersectionId(toIntersectionId);
    setToIntersectionId(prevFrom);
    setFormValidationMsg(null);
  };

  // Set origin or destination from corridor ranking
  const handleSelectCorridorEnd = (fromId?: number | null, toId?: number | null) => {
    if (fromId != null) setFromIntersectionId(String(fromId));
    if (toId != null) setToIntersectionId(String(toId));
    setFormValidationMsg(null);
    window.scrollTo({ top: 300, behavior: "smooth" });
  };

  const handleGlobalRefresh = () => {
    refetchJunctions();
    refetchStats();
    refetchRanking();
  };

  return (
    <div className="max-w-7xl mx-auto space-y-8">
      {/* 1. Header Section */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-white/10">
        <div>
          <div className="flex items-center gap-2.5 mb-1">
            <div className="p-2 rounded-xl bg-accent/10 border border-accent/20 text-accent">
              <RouteIcon className="w-5 h-5" />
            </div>
            <h1 className="text-2xl sm:text-3xl font-display font-bold text-text tracking-tight">
              Route Optimization
            </h1>
            <Badge variant="teal">Graph Topology Engine</Badge>
          </div>
          <p className="text-xs sm:text-sm text-muted">
            Minimum impedance pathfinding across metropolitan junction networks using Dijkstra &amp; A* heuristics.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Button
            variant="secondary"
            size="sm"
            onClick={handleGlobalRefresh}
            className="text-xs"
          >
            <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
            Refresh Network
          </Button>
          <Button
            variant="ghost"
            size="sm"
            href="/emergency"
            className="text-xs border border-white/10"
          >
            <Navigation className="w-3.5 h-3.5 mr-1.5 text-danger" />
            Emergency Corridors
          </Button>
        </div>
      </div>

      {/* 2. Note on Phase 5 Predictive Congestion Integration */}
      <Card className="p-4 sm:p-5 border-accent/30 bg-gradient-to-r from-surface to-accent/5 relative overflow-hidden">
        <div className="flex items-start gap-3.5">
          <div className="p-2 rounded-xl bg-accent/15 border border-accent/30 text-accent shrink-0 mt-0.5">
            <Sparkles className="w-5 h-5" />
          </div>
          <div className="flex-1 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-display font-semibold text-text">
                Phase 5 Predictive Congestion Integration
              </h3>
              <Badge variant="teal" dot>Live Telemetry Feeds</Badge>
            </div>
            <p className="text-xs text-muted leading-relaxed">
              Routing impedance calculations dynamically merge real-time telemetry sensor records with{" "}
              <span className="text-text font-medium">Phase 5 spatio-temporal AI predictions (GRU / ST-GCN models)</span>.
              Predicted bottleneck delays scale road corridor traversal multipliers automatically, ensuring optimal
              trajectories divert traffic before gridlock materializes.
            </p>
          </div>
          <Link
            href="/predictions"
            className="hidden md:inline-flex items-center gap-1.5 text-xs text-accent hover:text-[#1ae4b7] font-medium shrink-0 self-center"
          >
            <span>View AI Models</span>
            <ExternalLink className="w-3 h-3" />
          </Link>
        </div>
      </Card>

      {/* 3. Graph Topology Stats Summary */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm uppercase tracking-wider font-semibold text-muted font-display flex items-center gap-2">
            <Activity className="w-4 h-4 text-accent" />
            Hydrated Network Topology
          </h2>
          <span className="text-xs text-muted">
            {statsLoading ? "Hydrating graph..." : "Active In-Memory Graph"}
          </span>
        </div>

        {statsError ? (
          <ErrorState
            title="Failed to load graph topology"
            message={statsError.message || "Could not retrieve graph statistics from the routing engine."}
            onRetry={refetchStats}
          />
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Card className="p-4 bg-surface/70 border-white/10 flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-accent/10 border border-accent/20 flex items-center justify-center text-accent">
                <Network className="w-6 h-6" />
              </div>
              <div>
                <div className="text-2xl font-display font-bold text-text">
                  {statsLoading ? "—" : formatNumber(graphStats?.intersection_count)}
                </div>
                <div className="text-xs text-muted font-medium">
                  Intersection Nodes
                </div>
              </div>
            </Card>

            <Card className="p-4 bg-surface/70 border-white/10 flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-amber/10 border border-amber/20 flex items-center justify-center text-amber">
                <GitFork className="w-6 h-6" />
              </div>
              <div>
                <div className="text-2xl font-display font-bold text-text">
                  {statsLoading ? "—" : formatNumber(graphStats?.road_count)}
                </div>
                <div className="text-xs text-muted font-medium">
                  Physical Road Corridors
                </div>
              </div>
            </Card>

            <Card className="p-4 bg-surface/70 border-white/10 flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-success/10 border border-success/20 flex items-center justify-center text-success">
                <ArrowLeftRight className="w-6 h-6" />
              </div>
              <div>
                <div className="text-2xl font-display font-bold text-text">
                  {statsLoading ? "—" : formatNumber(graphStats?.directed_edge_count)}
                </div>
                <div className="text-xs text-muted font-medium">
                  Directed Traversal Edges
                </div>
              </div>
            </Card>
          </div>
        )}
      </div>

      {/* 4. Main Two-Column Layout: Route Planner & Route Results */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Route Configuration Console (5 cols) */}
        <Card className="lg:col-span-5 p-5 sm:p-6 border-white/10 space-y-5 bg-surface/90">
          <div className="flex items-center justify-between pb-3 border-b border-white/10">
            <div>
              <h2 className="text-base font-display font-bold text-text flex items-center gap-2">
                <Navigation className="w-4 h-4 text-accent" />
                Route Computation
              </h2>
              <p className="text-xs text-muted">
                Configure origin, destination, and impedance weighting
              </p>
            </div>
            <Badge variant="teal">Dijkstra &amp; A*</Badge>
          </div>

          {junctionsError && (
            <div className="p-3 rounded-xl bg-danger/15 border border-danger/30 text-danger text-xs flex items-center justify-between">
              <span>Failed to load junctions: {junctionsError.message}</span>
              <button
                type="button"
                onClick={() => refetchJunctions()}
                className="underline hover:text-white"
              >
                Retry
              </button>
            </div>
          )}

          <form onSubmit={handleCalculateRoute} className="space-y-4">
            {/* Origin Junction Selector */}
            <div className="space-y-1.5">
              <label
                htmlFor="origin-select"
                className="block text-xs font-semibold text-text uppercase tracking-wider font-mono flex items-center justify-between"
              >
                <span className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-accent" />
                  Origin Junction
                </span>
                {fromIntersectionId && (
                  <span className="text-muted font-normal">
                    ID #{fromIntersectionId}
                  </span>
                )}
              </label>
              {junctionsLoading ? (
                <div className="h-10 px-3 rounded-xl bg-ink/60 border border-white/10 flex items-center text-xs text-muted">
                  <LoadingSpinner size="sm" className="mr-2" /> Loading junctions...
                </div>
              ) : (
                <select
                  id="origin-select"
                  value={fromIntersectionId}
                  onChange={(e) => {
                    setFromIntersectionId(e.target.value);
                    setFormValidationMsg(null);
                  }}
                  className="w-full h-11 px-3 rounded-xl bg-ink/80 border border-white/15 text-text text-xs sm:text-sm focus:border-accent focus:outline-none transition-colors"
                >
                  <option value="">-- Select Origin Intersection --</option>
                  {junctionsData?.items?.map((j) => (
                    <option key={j.id} value={j.id}>
                      #{j.id} • {j.name} ({j.code})
                    </option>
                  ))}
                </select>
              )}
            </div>

            {/* Swap Button */}
            <div className="flex justify-center -my-1">
              <button
                type="button"
                onClick={handleSwapJunctions}
                disabled={!fromIntersectionId && !toIntersectionId}
                className="p-1.5 rounded-full bg-surface border border-white/15 text-muted hover:text-accent hover:border-accent/40 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                title="Swap origin and destination"
              >
                <ArrowLeftRight className="w-3.5 h-3.5" />
              </button>
            </div>

            {/* Destination Junction Selector */}
            <div className="space-y-1.5">
              <label
                htmlFor="dest-select"
                className="block text-xs font-semibold text-text uppercase tracking-wider font-mono flex items-center justify-between"
              >
                <span className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-danger" />
                  Destination Junction
                </span>
                {toIntersectionId && (
                  <span className="text-muted font-normal">
                    ID #{toIntersectionId}
                  </span>
                )}
              </label>
              {junctionsLoading ? (
                <div className="h-10 px-3 rounded-xl bg-ink/60 border border-white/10 flex items-center text-xs text-muted">
                  <LoadingSpinner size="sm" className="mr-2" /> Loading junctions...
                </div>
              ) : (
                <select
                  id="dest-select"
                  value={toIntersectionId}
                  onChange={(e) => {
                    setToIntersectionId(e.target.value);
                    setFormValidationMsg(null);
                  }}
                  className="w-full h-11 px-3 rounded-xl bg-ink/80 border border-white/15 text-text text-xs sm:text-sm focus:border-accent focus:outline-none transition-colors"
                >
                  <option value="">-- Select Destination Intersection --</option>
                  {junctionsData?.items?.map((j) => (
                    <option key={j.id} value={j.id}>
                      #{j.id} • {j.name} ({j.code})
                    </option>
                  ))}
                </select>
              )}
            </div>

            {/* Algorithm Selector Toggle */}
            <div className="space-y-1.5 pt-2">
              <label className="block text-xs font-semibold text-text uppercase tracking-wider font-mono">
                Pathfinding Algorithm
              </label>
              <div className="grid grid-cols-2 gap-2 p-1 rounded-xl bg-ink/80 border border-white/10">
                <button
                  type="button"
                  onClick={() => setAlgorithm("astar")}
                  className={`py-2 px-3 rounded-lg text-xs font-medium transition-all ${
                    algorithm === "astar"
                      ? "bg-accent text-ink font-semibold shadow-sm"
                      : "text-muted hover:text-text hover:bg-surface/50"
                  }`}
                >
                  <div className="font-display">A* Search</div>
                  <div className="text-[10px] opacity-80">Spatial Heuristic</div>
                </button>
                <button
                  type="button"
                  onClick={() => setAlgorithm("dijkstra")}
                  className={`py-2 px-3 rounded-lg text-xs font-medium transition-all ${
                    algorithm === "dijkstra"
                      ? "bg-accent text-ink font-semibold shadow-sm"
                      : "text-muted hover:text-text hover:bg-surface/50"
                  }`}
                >
                  <div className="font-display">Dijkstra</div>
                  <div className="text-[10px] opacity-80">Uniform Cost</div>
                </button>
              </div>
            </div>

            {/* Advanced Cost Profile Tuning (Collapsible) */}
            <div className="pt-2 border-t border-white/10">
              <button
                type="button"
                onClick={() => setShowAdvancedWeights(!showAdvancedWeights)}
                className="w-full flex items-center justify-between text-xs text-muted hover:text-text py-1 transition-colors"
              >
                <span className="flex items-center gap-1.5 font-medium">
                  <Sliders className="w-3.5 h-3.5 text-accent" />
                  Impedance Cost Weights
                </span>
                <span className="flex items-center text-[11px]">
                  {showAdvancedWeights ? "Hide" : "Tuning"}
                  {showAdvancedWeights ? (
                    <ChevronUp className="w-3.5 h-3.5 ml-1" />
                  ) : (
                    <ChevronDown className="w-3.5 h-3.5 ml-1" />
                  )}
                </span>
              </button>

              {showAdvancedWeights && (
                <div className="mt-3 space-y-3 p-3 rounded-xl bg-ink/60 border border-white/10 text-xs">
                  <div>
                    <div className="flex justify-between text-[11px] text-muted mb-1">
                      <span>Travel Time Weight</span>
                      <span className="font-mono text-text">{timeWeight.toFixed(2)}x</span>
                    </div>
                    <input
                      type="range"
                      min="0"
                      max="3"
                      step="0.1"
                      value={timeWeight}
                      onChange={(e) => setTimeWeight(parseFloat(e.target.value))}
                      className="w-full accent-accent h-1 bg-surface rounded-lg"
                    />
                  </div>

                  <div>
                    <div className="flex justify-between text-[11px] text-muted mb-1">
                      <span>Congestion Penalty Weight</span>
                      <span className="font-mono text-text">{congestionWeight.toFixed(2)}x</span>
                    </div>
                    <input
                      type="range"
                      min="0"
                      max="3"
                      step="0.1"
                      value={congestionWeight}
                      onChange={(e) => setCongestionWeight(parseFloat(e.target.value))}
                      className="w-full accent-amber h-1 bg-surface rounded-lg"
                    />
                  </div>

                  <div>
                    <div className="flex justify-between text-[11px] text-muted mb-1">
                      <span>Physical Distance Weight</span>
                      <span className="font-mono text-text">{distanceWeight.toFixed(2)}x</span>
                    </div>
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step="0.05"
                      value={distanceWeight}
                      onChange={(e) => setDistanceWeight(parseFloat(e.target.value))}
                      className="w-full accent-teal h-1 bg-surface rounded-lg"
                    />
                  </div>

                  <div>
                    <div className="flex justify-between text-[11px] text-muted mb-1">
                      <span>Road Hierarchy / Condition Weight</span>
                      <span className="font-mono text-text">{conditionWeight.toFixed(2)}x</span>
                    </div>
                    <input
                      type="range"
                      min="0"
                      max="2"
                      step="0.1"
                      value={conditionWeight}
                      onChange={(e) => setConditionWeight(parseFloat(e.target.value))}
                      className="w-full accent-muted h-1 bg-surface rounded-lg"
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Validation Message */}
            {formValidationMsg && (
              <div className="p-3 rounded-xl bg-danger/15 border border-danger/30 text-danger text-xs flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>{formValidationMsg}</span>
              </div>
            )}

            {/* Submit Action */}
            <Button
              type="submit"
              variant="primary"
              size="md"
              disabled={isComputingRoute || junctionsLoading}
              className="w-full font-display font-semibold"
            >
              {isComputingRoute ? (
                <>
                  <LoadingSpinner size="sm" className="mr-2" />
                  Calculating Optimal Route...
                </>
              ) : (
                <>
                  <RouteIcon className="w-4 h-4 mr-2" />
                  Calculate Optimal Route
                </>
              )}
            </Button>
          </form>
        </Card>

        {/* Right Column: Computed Route Display (7 cols) */}
        <div className="lg:col-span-7 space-y-4">
          <Card className="p-5 sm:p-6 border-white/10 bg-surface/90">
            <div className="flex items-center justify-between pb-3 border-b border-white/10 mb-4">
              <div>
                <h2 className="text-base font-display font-bold text-text flex items-center gap-2">
                  <Navigation className="w-4 h-4 text-accent" />
                  Computed Route Output
                </h2>
                <p className="text-xs text-muted">
                  Sequential intersection nodes and per-segment impedance
                </p>
              </div>
              {routeResult && (
                <div className="flex items-center gap-2">
                  <Badge variant="teal">{routeResult.algorithm.toUpperCase()}</Badge>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={resetRoute}
                    className="text-[11px] h-7 px-2 text-muted"
                  >
                    Clear
                  </Button>
                </div>
              )}
            </div>

            {/* State Handling: Computing, Error, Empty, or Data */}
            {isComputingRoute ? (
              <div className="py-16 flex flex-col items-center justify-center text-center">
                <LoadingSpinner size="lg" label="Computing shortest impedance path through graph..." />
                <p className="text-xs text-muted mt-2 max-w-sm">
                  Exploring graph edges using {algorithm === "astar" ? "A* Euclidean Heuristic" : "Dijkstra Priority Queue"}...
                </p>
              </div>
            ) : routeError ? (
              <ErrorState
                title="Pathfinding Error"
                message={
                  routeError.message?.includes("NoPathError") || routeError.message?.includes("404")
                    ? `No traversable path exists in the network graph between Junction #${fromIntersectionId} and Junction #${toIntersectionId}. Check connectivity or try alternate junctions.`
                    : routeError.message || "Route calculation failed. Verify network graph connectivity."
                }
                onRetry={handleCalculateRoute}
                retryText="Re-calculate"
              />
            ) : !routeResult ? (
              <EmptyState
                icon={<RouteIcon className="w-8 h-8 text-muted" />}
                title="No Route Calculated"
                description="Select an origin and destination junction on the left and run pathfinding to inspect the optimal path sequence, travel times, and segment costs."
              />
            ) : (
              <div className="space-y-6">
                {/* Metrics Summary Strip */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-3.5 rounded-xl bg-ink/60 border border-white/10">
                  <div>
                    <div className="text-[11px] text-muted uppercase tracking-wider font-mono">
                      Traversal Cost
                    </div>
                    <div className="text-lg font-display font-bold text-accent">
                      {formatNumber(routeResult.total_cost_minutes, 2)} min
                    </div>
                    <div className="text-[10px] text-muted">
                      ({formatSeconds(routeResult.total_cost_minutes * 60)})
                    </div>
                  </div>

                  <div>
                    <div className="text-[11px] text-muted uppercase tracking-wider font-mono">
                      Total Distance
                    </div>
                    <div className="text-lg font-display font-bold text-text">
                      {formatNumber(routeResult.total_distance_km, 2)} km
                    </div>
                    <div className="text-[10px] text-muted">Physical Segment Sum</div>
                  </div>

                  <div>
                    <div className="text-[11px] text-muted uppercase tracking-wider font-mono">
                      Junction Nodes
                    </div>
                    <div className="text-lg font-display font-bold text-text">
                      {routeResult.path.length}
                    </div>
                    <div className="text-[10px] text-muted">
                      {routeResult.edges.length} Segment Hops
                    </div>
                  </div>

                  <div>
                    <div className="text-[11px] text-muted uppercase tracking-wider font-mono">
                      Algorithm
                    </div>
                    <div className="text-lg font-display font-bold text-amber">
                      {routeResult.algorithm}
                    </div>
                    <div className="text-[10px] text-muted">Dynamic Cost Fn</div>
                  </div>
                </div>

                {/* Ordered Junction List (Step Flow) */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs font-semibold text-text uppercase tracking-wider font-mono">
                    <span>Ordered Traversal Sequence ({routeResult.path.length} Junctions)</span>
                  </div>

                  <div className="p-3 rounded-xl bg-ink/40 border border-white/10 max-h-56 overflow-y-auto space-y-2">
                    {routeResult.path.map((nodeId, idx) => {
                      const junctionInfo = junctionMap.get(nodeId);
                      const isOrigin = idx === 0;
                      const isDest = idx === routeResult.path.length - 1;

                      return (
                        <div
                          key={`${nodeId}-${idx}`}
                          className="flex items-center gap-3 text-xs p-2 rounded-lg bg-surface/70 border border-white/5"
                        >
                          <div
                            className={`w-6 h-6 rounded-full flex items-center justify-center font-mono text-[11px] font-bold ${
                              isOrigin
                                ? "bg-accent text-ink"
                                : isDest
                                ? "bg-danger text-white"
                                : "bg-white/10 text-text"
                            }`}
                          >
                            {idx + 1}
                          </div>

                          <div className="flex-1 min-w-0">
                            <div className="font-medium text-text truncate flex items-center gap-2">
                              <span>{junctionInfo?.name || `Intersection #${nodeId}`}</span>
                              {junctionInfo?.code && (
                                <span className="font-mono text-[10px] text-muted">
                                  ({junctionInfo.code})
                                </span>
                              )}
                            </div>
                            <div className="text-[10px] text-muted">
                              Node ID #{nodeId}
                              {junctionInfo?.city && ` • ${junctionInfo.city}`}
                            </div>
                          </div>

                          <div>
                            {isOrigin ? (
                              <Badge variant="teal">Origin</Badge>
                            ) : isDest ? (
                              <Badge variant="danger">Destination</Badge>
                            ) : (
                              <Badge variant="muted">Waypoint {idx}</Badge>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Per-Segment Cost Breakdown Table */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs font-semibold text-text uppercase tracking-wider font-mono">
                    <span>Per-Segment Traversal Breakdown</span>
                    <span className="text-[10px] text-muted font-normal">
                      {routeResult.edges.length} directed road segments
                    </span>
                  </div>

                  <div className="overflow-x-auto rounded-xl border border-white/10">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-ink/80 text-muted uppercase font-mono text-[10px] border-b border-white/10">
                        <tr>
                          <th className="py-2.5 px-3">#</th>
                          <th className="py-2.5 px-3">Segment Corridor</th>
                          <th className="py-2.5 px-3">Trajectory</th>
                          <th className="py-2.5 px-3 text-right">Length</th>
                          <th className="py-2.5 px-3 text-right">Cost (min)</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5 font-mono text-[11px]">
                        {routeResult.edges.map((edge, idx) => {
                          const fromJ = junctionMap.get(edge.from_intersection_id);
                          const toJ = junctionMap.get(edge.to_intersection_id);
                          const costPct = routeResult.total_cost_minutes > 0
                            ? Math.round((edge.cost_minutes / routeResult.total_cost_minutes) * 100)
                            : 0;

                          return (
                            <tr key={idx} className="hover:bg-white/[0.02] transition-colors">
                              <td className="py-2 px-3 text-muted">{idx + 1}</td>
                              <td className="py-2 px-3 font-sans text-text">
                                <span className="font-mono text-accent">Road #{edge.road_id}</span>
                              </td>
                              <td className="py-2 px-3 text-muted font-sans truncate max-w-[180px]">
                                <span className="text-text">
                                  {fromJ?.code || `#${edge.from_intersection_id}`}
                                </span>
                                <span className="mx-1.5 text-accent">→</span>
                                <span className="text-text">
                                  {toJ?.code || `#${edge.to_intersection_id}`}
                                </span>
                              </td>
                              <td className="py-2 px-3 text-right text-text">
                                {formatNumber(edge.length_km, 3)} km
                              </td>
                              <td className="py-2 px-3 text-right">
                                <span className="text-amber font-semibold">
                                  {formatNumber(edge.cost_minutes, 3)}m
                                </span>
                                <span className="text-[10px] text-muted ml-1">
                                  ({costPct}%)
                                </span>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}
          </Card>
        </div>
      </div>

      {/* 5. Network Congestion Ranking Table (GET /routing/congestion-ranking) */}
      <div className="space-y-4 pt-4 border-t border-white/10">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <div className="p-1.5 rounded-lg bg-amber/10 border border-amber/20 text-amber">
                <Flame className="w-4 h-4" />
              </div>
              <h2 className="text-lg font-display font-bold text-text">
                Real-Time Corridor Congestion Ranking
              </h2>
            </div>
            <p className="text-xs text-muted">
              Road corridors ordered by live congestion level (GET /routing/congestion-ranking)
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 text-xs text-muted">
              <span>Show top:</span>
              <select
                value={rankingLimit}
                onChange={(e) => setRankingLimit(Number(e.target.value))}
                className="h-8 px-2 rounded-lg bg-ink/80 border border-white/15 text-text text-xs focus:border-accent focus:outline-none"
              >
                <option value={5}>Top 5</option>
                <option value={10}>Top 10</option>
                <option value={20}>Top 20</option>
                <option value={50}>Top 50</option>
              </select>
            </div>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => refetchRanking()}
              className="text-xs h-8"
            >
              <RefreshCw className="w-3 h-3 mr-1" />
              Refresh
            </Button>
          </div>
        </div>

        <Card className="border-white/10 overflow-hidden bg-surface/80">
          {rankingLoading ? (
            <div className="py-12 flex justify-center">
              <LoadingSpinner size="md" label="Analyzing road congestion indices across network..." />
            </div>
          ) : rankingError ? (
            <div className="p-6">
              <ErrorState
                title="Congestion Ranking Unavailable"
                message={rankingError.message || "Failed to retrieve real-time congestion rankings."}
                onRetry={() => refetchRanking()}
              />
            </div>
          ) : !congestionRanking || congestionRanking.length === 0 ? (
            <div className="p-8">
              <EmptyState
                icon={<Gauge className="w-8 h-8 text-muted" />}
                title="No Congested Corridors Detected"
                description="Network telemetry indicates zero congested road corridors at this time or telemetry staging is empty."
              />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-ink/80 text-muted uppercase font-mono text-[10px] border-b border-white/10">
                  <tr>
                    <th className="py-3 px-4 w-14">Rank</th>
                    <th className="py-3 px-4">Road Corridor Name</th>
                    <th className="py-3 px-4">Endpoints</th>
                    <th className="py-3 px-4">Congestion Meter</th>
                    <th className="py-3 px-4 text-center">Severity</th>
                    <th className="py-3 px-4 text-right">Route Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {congestionRanking.map((item) => {
                    const status = getCongestionStatus(item.congestion_level);
                    const fromJ = item.from_intersection_id ? junctionMap.get(item.from_intersection_id) : null;
                    const toJ = item.to_intersection_id ? junctionMap.get(item.to_intersection_id) : null;

                    return (
                      <tr key={item.road_id} className="hover:bg-white/[0.02] transition-colors">
                        <td className="py-3 px-4 font-mono">
                          <span
                            className={`w-6 h-6 rounded-md inline-flex items-center justify-center font-bold text-xs ${
                              item.rank === 1
                                ? "bg-danger text-white shadow-sm"
                                : item.rank <= 3
                                ? "bg-amber/20 text-amber"
                                : "bg-white/5 text-muted"
                            }`}
                          >
                            #{item.rank}
                          </span>
                        </td>

                        <td className="py-3 px-4">
                          <div className="font-medium text-text text-sm">
                            {item.road_name}
                          </div>
                          <div className="text-[10px] text-muted font-mono">
                            Road ID #{item.road_id}
                          </div>
                        </td>

                        <td className="py-3 px-4 text-muted">
                          <div className="flex items-center gap-1.5 font-mono text-[11px]">
                            <span className="text-text">
                              {fromJ?.code || (item.from_intersection_id ? `Jct #${item.from_intersection_id}` : "—")}
                            </span>
                            <ArrowRight className="w-3 h-3 text-accent" />
                            <span className="text-text">
                              {toJ?.code || (item.to_intersection_id ? `Jct #${item.to_intersection_id}` : "—")}
                            </span>
                          </div>
                          {(fromJ?.name || toJ?.name) && (
                            <div className="text-[10px] text-muted truncate max-w-xs">
                              {fromJ?.name} to {toJ?.name}
                            </div>
                          )}
                        </td>

                        <td className="py-3 px-4 w-48">
                          <div className="space-y-1">
                            <div className="flex justify-between text-[11px] font-mono">
                              <span className={status.colorClass}>{item.congestion_level.toFixed(1)}%</span>
                              <span className="text-muted text-[10px]">LOS: {status.label}</span>
                            </div>
                            <div className="w-full h-2 rounded-full bg-ink overflow-hidden border border-white/5">
                              <div
                                className={`h-full rounded-full transition-all duration-300 ${
                                  status.level === "high"
                                    ? "bg-danger"
                                    : status.level === "medium"
                                    ? "bg-amber"
                                    : "bg-accent"
                                }`}
                                style={{ width: `${Math.min(100, Math.max(5, item.congestion_level))}%` }}
                              />
                            </div>
                          </div>
                        </td>

                        <td className="py-3 px-4 text-center">
                          <Badge variant={status.badgeVariant} dot>
                            {status.label}
                          </Badge>
                        </td>

                        <td className="py-3 px-4 text-right">
                          {item.from_intersection_id != null && item.to_intersection_id != null ? (
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => handleSelectCorridorEnd(item.from_intersection_id, item.to_intersection_id)}
                              className="text-[11px] h-7 px-2.5 py-1"
                            >
                              Route Segment
                            </Button>
                          ) : (
                            <span className="text-[10px] text-muted">Unmapped</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
