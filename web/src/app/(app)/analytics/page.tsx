"use client";

import React, { useState, useMemo } from "react";
import Link from "next/link";
import {
  BarChart3,
  TrendingUp,
  Car,
  AlertTriangle,
  Gauge,
  Calendar,
  RefreshCw,
  Flame,
  ArrowRight,
  ShieldAlert,
  CheckCircle2,
} from "lucide-react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import { useApiQuery } from "@/lib/use-api";
import { Card } from "@/components/ui/Card";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import {
  formatNumber,
  formatPercent,
  formatSpeed,
  formatDateTime,
  formatDate,
  getCongestionStatus,
  getSeverityBadgeVariant,
} from "@/lib/format";

// --- Types matching backend schemas (backend/app/schemas/analytics.py) ---

interface TrafficSummaryBucket {
  bucket: string;
  avg_vehicle_count: number;
  avg_speed?: number | null;
  avg_speed_kmh?: number | null;
  avg_congestion: number;
  avg_congestion_level: number;
  record_count: number;
}

interface IncidentsSummaryResponse {
  total: number;
  by_severity: Record<string, number>;
  by_status: Record<string, number>;
}

interface CongestionHotspotResponse {
  intersection_id: number;
  name: string;
  code: string;
  avg_congestion_level: number;
  avg_congestion: number;
  record_count: number;
}

interface JunctionOption {
  id: number;
  name: string;
  code: string;
}

interface PaginatedJunctions {
  items: JunctionOption[];
  total: number;
}

type TimeRangeKey = "24h" | "7d" | "30d" | "all";
type ChartMetricView = "overview" | "vehicles" | "congestion" | "speed";

export default function AnalyticsPage() {
  // --- Filter State ---
  const [timeRange, setTimeRange] = useState<TimeRangeKey>("24h");
  const [selectedIntersectionId, setSelectedIntersectionId] = useState<string>("all");
  const [hotspotsLimit, setHotspotsLimit] = useState<number>(10);
  const [chartView, setChartView] = useState<ChartMetricView>("overview");

  // Compute ISO time window based on selected range
  const { fromDate, toDate, bucketUnit, rangeLabel, rangeSubLabel } = useMemo(() => {
    const now = new Date();
    if (timeRange === "24h") {
      const from = new Date(now.getTime() - 24 * 60 * 60 * 1000);
      return {
        fromDate: from.toISOString(),
        toDate: now.toISOString(),
        bucketUnit: "hour" as const,
        rangeLabel: "Last 24 Hours",
        rangeSubLabel: `${formatDateTime(from)} → ${formatDateTime(now)} (1-hour buckets)`,
      };
    }
    if (timeRange === "7d") {
      const from = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      return {
        fromDate: from.toISOString(),
        toDate: now.toISOString(),
        bucketUnit: "day" as const,
        rangeLabel: "Last 7 Days",
        rangeSubLabel: `${formatDate(from)} → ${formatDate(now)} (daily buckets)`,
      };
    }
    if (timeRange === "30d") {
      const from = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
      return {
        fromDate: from.toISOString(),
        toDate: now.toISOString(),
        bucketUnit: "day" as const,
        rangeLabel: "Last 30 Days",
        rangeSubLabel: `${formatDate(from)} → ${formatDate(now)} (daily buckets)`,
      };
    }
    return {
      fromDate: undefined,
      toDate: undefined,
      bucketUnit: "day" as const,
      rangeLabel: "All Recorded History",
      rangeSubLabel: "Entire historical sensor archive (daily buckets)",
    };
  }, [timeRange]);

  // --- API Query: Intersections List (for optional filter dropdown) ---
  const { data: junctionsData } = useApiQuery<PaginatedJunctions>({
    queryKey: ["analytics-junctions-list"],
    endpoint: "/junctions",
    params: { per_page: 100 },
    queryOptions: {
      staleTime: 60000,
    },
  });

  // --- API Query 1: Traffic Telemetry Summary (GET /analytics/traffic-summary) ---
  const trafficQueryParams = useMemo(() => {
    const params: Record<string, string | number | undefined> = {
      bucket: bucketUnit,
    };
    if (fromDate) params.from = fromDate;
    if (toDate) params.to = toDate;
    if (selectedIntersectionId !== "all") {
      params.intersection_id = Number(selectedIntersectionId);
    }
    return params;
  }, [bucketUnit, fromDate, toDate, selectedIntersectionId]);

  const {
    data: trafficSummary,
    isLoading: trafficLoading,
    error: trafficError,
    refetch: refetchTraffic,
  } = useApiQuery<TrafficSummaryBucket[]>({
    queryKey: ["analytics-traffic-summary", trafficQueryParams],
    endpoint: "/analytics/traffic-summary",
    params: trafficQueryParams,
    queryOptions: {
      refetchInterval: 30000,
    },
  });

  // --- API Query 2: Incidents Summary (GET /analytics/incidents-summary) ---
  const incidentsQueryParams = useMemo(() => {
    const params: Record<string, string | undefined> = {};
    if (fromDate) params.from = fromDate;
    if (toDate) params.to = toDate;
    return params;
  }, [fromDate, toDate]);

  const {
    data: incidentsSummary,
    isLoading: incidentsLoading,
    error: incidentsError,
    refetch: refetchIncidents,
  } = useApiQuery<IncidentsSummaryResponse>({
    queryKey: ["analytics-incidents-summary", incidentsQueryParams],
    endpoint: "/analytics/incidents-summary",
    params: incidentsQueryParams,
    queryOptions: {
      refetchInterval: 30000,
    },
  });

  // --- API Query 3: Congestion Hotspots (GET /analytics/congestion-hotspots) ---
  const hotspotsQueryParams = useMemo(() => {
    const params: Record<string, string | number | undefined> = {
      limit: hotspotsLimit,
    };
    if (fromDate) params.from = fromDate;
    if (toDate) params.to = toDate;
    return params;
  }, [hotspotsLimit, fromDate, toDate]);

  const {
    data: hotspots,
    isLoading: hotspotsLoading,
    error: hotspotsError,
    refetch: refetchHotspots,
  } = useApiQuery<CongestionHotspotResponse[]>({
    queryKey: ["analytics-congestion-hotspots", hotspotsQueryParams],
    endpoint: "/analytics/congestion-hotspots",
    params: hotspotsQueryParams,
    queryOptions: {
      refetchInterval: 30000,
    },
  });

  // Global refresh
  const handleGlobalRefresh = () => {
    refetchTraffic();
    refetchIncidents();
    refetchHotspots();
  };

  // --- Derived KPI Calculations (strictly computed from real backend responses) ---
  const kpis = useMemo(() => {
    if (!trafficSummary || trafficSummary.length === 0) {
      return {
        totalObservations: 0,
        avgVehicles: null,
        avgCongestion: null,
        avgSpeed: null,
      };
    }

    let totalObs = 0;
    let sumVehicles = 0;
    let sumCongestion = 0;
    let sumSpeed = 0;
    let speedCount = 0;

    for (const b of trafficSummary) {
      totalObs += b.record_count;
      sumVehicles += b.avg_vehicle_count;
      sumCongestion += b.avg_congestion;
      if (b.avg_speed != null) {
        sumSpeed += b.avg_speed;
        speedCount++;
      }
    }

    const n = trafficSummary.length;
    return {
      totalObservations: totalObs,
      avgVehicles: n > 0 ? sumVehicles / n : null,
      avgCongestion: n > 0 ? sumCongestion / n : null,
      avgSpeed: speedCount > 0 ? sumSpeed / speedCount : null,
    };
  }, [trafficSummary]);

  // Derived Active Incidents
  const activeIncidentsCount = useMemo(() => {
    if (!incidentsSummary?.by_status) return 0;
    let active = 0;
    for (const [st, count] of Object.entries(incidentsSummary.by_status)) {
      const lower = st.toLowerCase();
      if (!["resolved", "closed", "cleared", "archived"].includes(lower)) {
        active += count;
      }
    }
    return active;
  }, [incidentsSummary]);

  // Chart formatted data
  const chartData = useMemo(() => {
    if (!trafficSummary || trafficSummary.length === 0) return [];

    return trafficSummary.map((item) => {
      const d = new Date(item.bucket);
      const timeLabel =
        bucketUnit === "hour"
          ? d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })
          : d.toLocaleDateString("en-US", { month: "short", day: "numeric" });

      const fullTimeLabel = formatDateTime(item.bucket);

      return {
        rawTime: item.bucket,
        time: timeLabel,
        fullTime: fullTimeLabel,
        vehicles: Math.round(item.avg_vehicle_count * 10) / 10,
        congestion: Math.round(item.avg_congestion * 10) / 10,
        speed: item.avg_speed != null ? Math.round(item.avg_speed * 10) / 10 : null,
        records: item.record_count,
      };
    });
  }, [trafficSummary, bucketUnit]);

  return (
    <div className="max-w-7xl mx-auto space-y-8">
      {/* 1. Header & Controls */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 pb-3 border-b border-white/10">
        <div>
          <div className="flex items-center gap-2.5 mb-1">
            <div className="p-2 rounded-xl bg-accent/10 border border-accent/20 text-accent">
              <BarChart3 className="w-5 h-5" />
            </div>
            <h1 className="text-2xl sm:text-3xl font-display font-bold text-text tracking-tight">
              Analytics &amp; Trends
            </h1>
            <Badge variant="teal">Aggregated SQL Telemetry</Badge>
          </div>
          <p className="text-xs sm:text-sm text-muted">
            Macroscopic network throughput, corridor bottleneck trends, and incident distribution.
          </p>
        </div>

        {/* Filters Strip */}
        <div className="flex flex-wrap items-center gap-2.5">
          {/* Time Range Selector */}
          <div className="flex items-center rounded-xl bg-surface border border-white/10 p-1">
            {(
              [
                { key: "24h", label: "24H" },
                { key: "7d", label: "7D" },
                { key: "30d", label: "30D" },
                { key: "all", label: "All" },
              ] as const
            ).map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => setTimeRange(t.key)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium font-mono transition-all ${
                  timeRange === t.key
                    ? "bg-accent text-ink font-semibold shadow-sm"
                    : "text-muted hover:text-text hover:bg-white/5"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Intersection Selector */}
          <div className="relative">
            <select
              value={selectedIntersectionId}
              onChange={(e) => setSelectedIntersectionId(e.target.value)}
              className="h-9 px-3 rounded-xl bg-surface border border-white/10 text-xs text-text focus:border-accent focus:outline-none"
            >
              <option value="all">All Intersections (City-Wide)</option>
              {junctionsData?.items?.map((j) => (
                <option key={j.id} value={j.id}>
                  #{j.id} - {j.name} ({j.code})
                </option>
              ))}
            </select>
          </div>

          {/* Refresh Action */}
          <Button
            variant="secondary"
            size="sm"
            onClick={handleGlobalRefresh}
            className="text-xs h-9 px-3"
            title="Refresh analytics data"
          >
            <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
            Refresh
          </Button>
        </div>
      </div>

      {/* Honest Time-Range Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 px-4 py-2.5 rounded-xl bg-ink/70 border border-white/10 text-xs text-muted">
        <div className="flex items-center gap-2">
          <Calendar className="w-3.5 h-3.5 text-accent" />
          <span className="font-semibold text-text">Time Window:</span>
          <span>{rangeLabel}</span>
          <span className="text-muted/60">•</span>
          <span className="font-mono text-[11px] text-muted">{rangeSubLabel}</span>
        </div>
        <div className="text-[11px] font-mono text-muted">
          Aggregation: <span className="text-text font-medium">{bucketUnit.toUpperCase()}</span>
          {selectedIntersectionId !== "all" && (
            <span className="ml-2 text-accent">
              • Junction #{selectedIntersectionId}
            </span>
          )}
        </div>
      </div>

      {/* 2. KPI Cards Strip */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* KPI 1: Total Vehicles */}
        <Card className="p-5 border-white/10 bg-surface/80 flex flex-col justify-between">
          <div className="flex items-center justify-between text-muted mb-2">
            <span className="text-xs uppercase font-mono font-semibold tracking-wider">
              Avg Vehicle Volume
            </span>
            <div className="p-2 rounded-xl bg-accent/10 text-accent">
              <Car className="w-4 h-4" />
            </div>
          </div>
          <div>
            <div className="text-2xl sm:text-3xl font-display font-bold text-text">
              {trafficLoading ? "—" : formatNumber(kpis.avgVehicles, 1)}
            </div>
            <div className="text-xs text-muted mt-1 flex items-center justify-between">
              <span>Avg per observation bucket</span>
              <span className="font-mono text-accent">
                {formatNumber(kpis.totalObservations)} records
              </span>
            </div>
          </div>
        </Card>

        {/* KPI 2: Average Congestion */}
        <Card className="p-5 border-white/10 bg-surface/80 flex flex-col justify-between">
          <div className="flex items-center justify-between text-muted mb-2">
            <span className="text-xs uppercase font-mono font-semibold tracking-wider">
              Network Congestion
            </span>
            <div className="p-2 rounded-xl bg-amber/10 text-amber">
              <Flame className="w-4 h-4" />
            </div>
          </div>
          <div>
            <div className="text-2xl sm:text-3xl font-display font-bold text-text">
              {trafficLoading ? "—" : formatPercent(kpis.avgCongestion)}
            </div>
            <div className="text-xs text-muted mt-1 flex items-center justify-between">
              <span>Mean congestion index</span>
              {kpis.avgCongestion != null && (
                <Badge variant={getCongestionStatus(kpis.avgCongestion).badgeVariant} dot>
                  {getCongestionStatus(kpis.avgCongestion).label}
                </Badge>
              )}
            </div>
          </div>
        </Card>

        {/* KPI 3: Active Incidents */}
        <Card className="p-5 border-white/10 bg-surface/80 flex flex-col justify-between">
          <div className="flex items-center justify-between text-muted mb-2">
            <span className="text-xs uppercase font-mono font-semibold tracking-wider">
              Active Incidents
            </span>
            <div className="p-2 rounded-xl bg-danger/10 text-danger">
              <AlertTriangle className="w-4 h-4" />
            </div>
          </div>
          <div>
            <div className="text-2xl sm:text-3xl font-display font-bold text-text">
              {incidentsLoading ? "—" : activeIncidentsCount}
            </div>
            <div className="text-xs text-muted mt-1 flex items-center justify-between">
              <span>Unresolved roadway hazards</span>
              <span className="font-mono text-text">
                {incidentsSummary?.total ?? 0} total
              </span>
            </div>
          </div>
        </Card>

        {/* KPI 4: Average Speed */}
        <Card className="p-5 border-white/10 bg-surface/80 flex flex-col justify-between">
          <div className="flex items-center justify-between text-muted mb-2">
            <span className="text-xs uppercase font-mono font-semibold tracking-wider">
              Average Flow Speed
            </span>
            <div className="p-2 rounded-xl bg-success/10 text-success">
              <Gauge className="w-4 h-4" />
            </div>
          </div>
          <div>
            <div className="text-2xl sm:text-3xl font-display font-bold text-text">
              {trafficLoading ? "—" : formatSpeed(kpis.avgSpeed)}
            </div>
            <div className="text-xs text-muted mt-1 flex items-center justify-between">
              <span>Corridor traversal velocity</span>
              <span className="font-mono text-success font-medium">Telemetry</span>
            </div>
          </div>
        </Card>
      </div>

      {/* 3. Traffic Trends Chart Section */}
      <Card className="p-5 sm:p-6 border-white/10 bg-surface/90 space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-white/10">
          <div>
            <h2 className="text-base font-display font-bold text-text flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-accent" />
              Traffic Flow &amp; Congestion Trends
            </h2>
            <p className="text-xs text-muted">
              Bucketed SQL telemetry metrics aggregated by {bucketUnit} across selected scope
            </p>
          </div>

          {/* Metric View Tabs */}
          <div className="flex items-center rounded-xl bg-ink/80 border border-white/10 p-1">
            {(
              [
                { key: "overview", label: "Overview" },
                { key: "vehicles", label: "Vehicles" },
                { key: "congestion", label: "Congestion" },
                { key: "speed", label: "Speed" },
              ] as const
            ).map((v) => (
              <button
                key={v.key}
                type="button"
                onClick={() => setChartView(v.key)}
                className={`px-3 py-1 text-xs font-medium rounded-lg transition-colors ${
                  chartView === v.key
                    ? "bg-surface text-text font-semibold border border-white/15 shadow-sm"
                    : "text-muted hover:text-text"
                }`}
              >
                {v.label}
              </button>
            ))}
          </div>
        </div>

        {trafficLoading ? (
          <div className="h-72 flex flex-col items-center justify-center">
            <LoadingSpinner size="md" label="Aggregating time-bucketed traffic records..." />
          </div>
        ) : trafficError ? (
          <div className="py-8">
            <ErrorState
              title="Unable to load traffic trends"
              message={trafficError.message || "Failed to query traffic summary aggregation."}
              onRetry={refetchTraffic}
            />
          </div>
        ) : chartData.length === 0 ? (
          <div className="py-12">
            <EmptyState
              icon={<BarChart3 className="w-8 h-8 text-muted" />}
              title="No Telemetry Data in Selected Window"
              description={`Zero traffic records observed for ${rangeLabel.toLowerCase()}. Select a wider time window or adjust filters.`}
            />
          </div>
        ) : (
          <div className="h-80 w-full pt-2">
            <ResponsiveContainer width="100%" height="100%">
              {chartView === "speed" ? (
                <LineChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" vertical={false} />
                  <XAxis
                    dataKey="time"
                    stroke="#8B93B0"
                    fontSize={11}
                    tickLine={false}
                    axisLine={{ stroke: "rgba(255, 255, 255, 0.1)" }}
                  />
                  <YAxis
                    stroke="#8B93B0"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v) => `${v} km/h`}
                  />
                  <Tooltip
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const item = payload[0].payload;
                      return (
                        <div className="rounded-xl bg-ink/95 border border-white/10 p-3 shadow-xl backdrop-blur-md text-xs">
                          <div className="font-mono text-muted mb-1.5">{item.fullTime}</div>
                          <div className="flex items-center justify-between gap-4">
                            <span className="text-muted">Average Speed:</span>
                            <span className="font-mono font-bold text-success">
                              {item.speed != null ? `${item.speed} km/h` : "—"}
                            </span>
                          </div>
                          <div className="flex items-center justify-between gap-4 mt-1 text-[11px] text-muted">
                            <span>Observations:</span>
                            <span className="font-mono">{item.records} records</span>
                          </div>
                        </div>
                      );
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="speed"
                    name="Avg Speed (km/h)"
                    stroke="#22C55E"
                    strokeWidth={2.5}
                    dot={{ fill: "#22C55E", r: 3 }}
                    activeDot={{ r: 6 }}
                  />
                </LineChart>
              ) : (
                <AreaChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="vehiclesGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#00D9A8" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#00D9A8" stopOpacity={0.0} />
                    </linearGradient>
                    <linearGradient id="congestionGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#FFB800" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#FFB800" stopOpacity={0.0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" vertical={false} />
                  <XAxis
                    dataKey="time"
                    stroke="#8B93B0"
                    fontSize={11}
                    tickLine={false}
                    axisLine={{ stroke: "rgba(255, 255, 255, 0.1)" }}
                  />
                  <YAxis
                    yAxisId="left"
                    stroke="#8B93B0"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : `${v}`)}
                  />
                  {(chartView === "overview" || chartView === "congestion") && (
                    <YAxis
                      yAxisId="right"
                      orientation="right"
                      domain={[0, 100]}
                      stroke="#8B93B0"
                      fontSize={11}
                      tickLine={false}
                      axisLine={false}
                      tickFormatter={(v) => `${v}%`}
                    />
                  )}
                  <Tooltip
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const item = payload[0].payload;
                      return (
                        <div className="rounded-xl bg-ink/95 border border-white/10 p-3 shadow-xl backdrop-blur-md text-xs space-y-1">
                          <div className="font-mono text-muted mb-1">{item.fullTime}</div>
                          {(chartView === "overview" || chartView === "vehicles") && (
                            <div className="flex items-center justify-between gap-4">
                              <span className="flex items-center gap-1.5 text-muted">
                                <span className="w-2 h-2 rounded-full bg-accent" />
                                Avg Vehicles:
                              </span>
                              <span className="font-mono font-bold text-accent">
                                {item.vehicles}
                              </span>
                            </div>
                          )}
                          {(chartView === "overview" || chartView === "congestion") && (
                            <div className="flex items-center justify-between gap-4">
                              <span className="flex items-center gap-1.5 text-muted">
                                <span className="w-2 h-2 rounded-full bg-amber" />
                                Avg Congestion:
                              </span>
                              <span className="font-mono font-bold text-amber">
                                {item.congestion}%
                              </span>
                            </div>
                          )}
                          {item.speed != null && (chartView === "overview") && (
                            <div className="flex items-center justify-between gap-4">
                              <span className="flex items-center gap-1.5 text-muted">
                                <span className="w-2 h-2 rounded-full bg-success" />
                                Avg Speed:
                              </span>
                              <span className="font-mono font-bold text-success">
                                {item.speed} km/h
                              </span>
                            </div>
                          )}
                          <div className="flex items-center justify-between gap-4 pt-1 border-t border-white/10 text-[11px] text-muted">
                            <span>Observations:</span>
                            <span className="font-mono">{item.records}</span>
                          </div>
                        </div>
                      );
                    }}
                  />
                  {(chartView === "overview" || chartView === "vehicles") && (
                    <Area
                      yAxisId="left"
                      type="monotone"
                      dataKey="vehicles"
                      name="Avg Vehicles"
                      stroke="#00D9A8"
                      strokeWidth={2}
                      fillOpacity={1}
                      fill="url(#vehiclesGradient)"
                    />
                  )}
                  {(chartView === "overview" || chartView === "congestion") && (
                    <Area
                      yAxisId="right"
                      type="monotone"
                      dataKey="congestion"
                      name="Congestion %"
                      stroke="#FFB800"
                      strokeWidth={2}
                      fillOpacity={1}
                      fill="url(#congestionGradient)"
                    />
                  )}
                </AreaChart>
              )}
            </ResponsiveContainer>
          </div>
        )}
      </Card>

      {/* 4. Two-Column Lower Grid: Incident Breakdown & Congestion Hotspots */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Incidents Summary Breakdown (5 cols) */}
        <Card className="lg:col-span-5 p-5 sm:p-6 border-white/10 bg-surface/90 space-y-5">
          <div className="flex items-center justify-between pb-3 border-b border-white/10">
            <div>
              <h2 className="text-base font-display font-bold text-text flex items-center gap-2">
                <ShieldAlert className="w-4 h-4 text-danger" />
                Incident Distribution
              </h2>
              <p className="text-xs text-muted">
                Grouped counts by severity and status lifecycle (GET /analytics/incidents-summary)
              </p>
            </div>
            <Badge variant="danger">{incidentsSummary?.total ?? 0} Total</Badge>
          </div>

          {incidentsLoading ? (
            <div className="py-12 flex justify-center">
              <LoadingSpinner size="md" label="Aggregating incident distribution..." />
            </div>
          ) : incidentsError ? (
            <ErrorState
              title="Incident Summary Error"
              message={incidentsError.message || "Failed to load incidents summary."}
              onRetry={refetchIncidents}
            />
          ) : !incidentsSummary || incidentsSummary.total === 0 ? (
            <EmptyState
              icon={<CheckCircle2 className="w-8 h-8 text-success" />}
              title="Zero Incidents Logged"
              description={`No roadway incidents or accidents recorded within ${rangeLabel.toLowerCase()}.`}
            />
          ) : (
            <div className="space-y-6">
              {/* Severity Breakdown */}
              <div className="space-y-2.5">
                <div className="flex items-center justify-between text-xs font-semibold text-text uppercase tracking-wider font-mono">
                  <span>By Severity Level</span>
                  <span className="text-[10px] text-muted font-normal">
                    {Object.keys(incidentsSummary.by_severity).length} levels reported
                  </span>
                </div>

                <div className="space-y-2">
                  {Object.entries(incidentsSummary.by_severity).map(([sev, count]) => {
                    const badgeVariant = getSeverityBadgeVariant(sev);
                    const pct = incidentsSummary.total > 0
                      ? Math.round((count / incidentsSummary.total) * 100)
                      : 0;

                    return (
                      <div
                        key={sev}
                        className="p-2.5 rounded-xl bg-ink/50 border border-white/5 flex items-center justify-between text-xs"
                      >
                        <div className="flex items-center gap-2">
                          <Badge variant={badgeVariant} dot className="capitalize">
                            {sev}
                          </Badge>
                        </div>
                        <div className="flex items-center gap-3">
                          <div className="w-20 h-1.5 rounded-full bg-ink overflow-hidden border border-white/10 hidden sm:block">
                            <div
                              className={`h-full rounded-full ${
                                badgeVariant === "danger"
                                  ? "bg-danger"
                                  : badgeVariant === "amber"
                                  ? "bg-amber"
                                  : "bg-accent"
                              }`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <span className="font-mono text-text font-semibold">
                            {count}
                          </span>
                          <span className="font-mono text-muted text-[10px] w-8 text-right">
                            ({pct}%)
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Status Lifecycle Breakdown */}
              <div className="space-y-2.5 pt-3 border-t border-white/10">
                <div className="flex items-center justify-between text-xs font-semibold text-text uppercase tracking-wider font-mono">
                  <span>By Lifecycle Status</span>
                  <span className="text-[10px] text-muted font-normal">
                    {Object.keys(incidentsSummary.by_status).length} states
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  {Object.entries(incidentsSummary.by_status).map(([st, count]) => {
                    const isClosed = ["resolved", "closed", "cleared"].includes(st.toLowerCase());
                    const badgeVariant: BadgeVariant = isClosed ? "success" : "amber";

                    return (
                      <div
                        key={st}
                        className="p-2.5 rounded-xl bg-ink/50 border border-white/5 flex flex-col justify-between text-xs"
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="capitalize text-muted text-[11px] truncate">
                            {st.replace(/_/g, " ")}
                          </span>
                          <Badge variant={badgeVariant} className="text-[10px] px-1.5 py-0">
                            {isClosed ? "Done" : "Active"}
                          </Badge>
                        </div>
                        <div className="font-display font-bold text-lg text-text">
                          {count}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </Card>

        {/* Right Column: Congestion Hotspots Ranking Table (7 cols) */}
        <Card className="lg:col-span-7 p-5 sm:p-6 border-white/10 bg-surface/90 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-white/10">
            <div>
              <h2 className="text-base font-display font-bold text-text flex items-center gap-2">
                <Flame className="w-4 h-4 text-amber" />
                Congestion Hotspots Ranking
              </h2>
              <p className="text-xs text-muted">
                Junctions ranked by mean congestion level (GET /analytics/congestion-hotspots)
              </p>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-[11px] text-muted">Limit:</span>
              <select
                value={hotspotsLimit}
                onChange={(e) => setHotspotsLimit(Number(e.target.value))}
                className="h-7 px-2 rounded-lg bg-ink/80 border border-white/15 text-text text-xs focus:border-accent focus:outline-none"
              >
                <option value={5}>Top 5</option>
                <option value={10}>Top 10</option>
                <option value={20}>Top 20</option>
              </select>
            </div>
          </div>

          {hotspotsLoading ? (
            <div className="py-12 flex justify-center">
              <LoadingSpinner size="md" label="Ranking intersection congestion hotspots..." />
            </div>
          ) : hotspotsError ? (
            <ErrorState
              title="Hotspots Data Unavailable"
              message={hotspotsError.message || "Failed to load congestion hotspots."}
              onRetry={refetchHotspots}
            />
          ) : !hotspots || hotspots.length === 0 ? (
            <div className="py-12">
              <EmptyState
                icon={<Gauge className="w-8 h-8 text-muted" />}
                title="No Congestion Hotspots"
                description={`No intersection bottlenecks registered in the ${rangeLabel.toLowerCase()} window.`}
              />
            </div>
          ) : (
            <div className="overflow-x-auto rounded-xl border border-white/10">
              <table className="w-full text-left text-xs">
                <thead className="bg-ink/80 text-muted uppercase font-mono text-[10px] border-b border-white/10">
                  <tr>
                    <th className="py-2.5 px-3 w-10">#</th>
                    <th className="py-2.5 px-3">Intersection</th>
                    <th className="py-2.5 px-3">Congestion Level</th>
                    <th className="py-2.5 px-3 text-right">Observations</th>
                    <th className="py-2.5 px-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {hotspots.map((item, idx) => {
                    const status = getCongestionStatus(item.avg_congestion_level);

                    return (
                      <tr key={item.intersection_id} className="hover:bg-white/[0.02] transition-colors">
                        <td className="py-2.5 px-3 font-mono">
                          <span
                            className={`w-5 h-5 rounded inline-flex items-center justify-center font-bold text-[11px] ${
                              idx === 0
                                ? "bg-danger text-white shadow-sm"
                                : idx < 3
                                ? "bg-amber/20 text-amber"
                                : "bg-white/5 text-muted"
                            }`}
                          >
                            {idx + 1}
                          </span>
                        </td>

                        <td className="py-2.5 px-3">
                          <div className="font-medium text-text">
                            {item.name}
                          </div>
                          <div className="font-mono text-[10px] text-muted">
                            {item.code} • ID #{item.intersection_id}
                          </div>
                        </td>

                        <td className="py-2.5 px-3 min-w-[140px]">
                          <div className="space-y-1">
                            <div className="flex justify-between text-[11px] font-mono">
                              <span className={status.colorClass}>
                                {item.avg_congestion_level.toFixed(1)}%
                              </span>
                              <Badge variant={status.badgeVariant} className="text-[9px] px-1 py-0">
                                {status.label}
                              </Badge>
                            </div>
                            <div className="w-full h-1.5 rounded-full bg-ink overflow-hidden border border-white/5">
                              <div
                                className={`h-full rounded-full ${
                                  status.level === "high"
                                    ? "bg-danger"
                                    : status.level === "medium"
                                    ? "bg-amber"
                                    : "bg-accent"
                                }`}
                                style={{ width: `${Math.min(100, Math.max(5, item.avg_congestion_level))}%` }}
                              />
                            </div>
                          </div>
                        </td>

                        <td className="py-2.5 px-3 text-right font-mono text-muted">
                          {formatNumber(item.record_count)}
                        </td>

                        <td className="py-2.5 px-3 text-right">
                          <Link
                            href={`/traffic`}
                            className="inline-flex items-center gap-1 text-[11px] text-accent hover:text-[#1ae4b7] font-medium"
                          >
                            <span>Inspect</span>
                            <ArrowRight className="w-3 h-3" />
                          </Link>
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
