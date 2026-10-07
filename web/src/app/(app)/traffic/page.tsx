"use client";

import React, { useState, useMemo } from "react";
import {
  Car,
  Clock,
  Gauge,
  Layers,
  RefreshCw,
  SlidersHorizontal,
  TrendingUp,
  MapPin,
  Activity,
  BarChart3,
  Truck,
  Bus,
  Bike,
  Plus,
  FileSpreadsheet,
  CheckCircle2,
  AlertCircle,
  X,
  Filter,
} from "lucide-react";
import { useApiQuery, useApiMutation } from "@/lib/use-api";
import { useAuth } from "@/lib/auth";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Stat } from "@/components/ui/Stat";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import {
  VehicleClassBarChart,
  type VehicleClassItem,
} from "@/components/charts/VehicleClassBarChart";
import {
  DensityLineChart,
  type DensityPoint,
} from "@/components/charts/DensityLineChart";
import {
  AreaTrafficChart,
  type AreaTrafficPoint,
} from "@/components/charts/AreaTrafficChart";
import {
  formatNumber,
  formatPercent,
  formatSpeed,
  formatDuration,
  formatDateTime,
  formatTime,
  getCongestionStatus,
} from "@/lib/format";

export type TimeRange = "1h" | "6h" | "24h" | "7d";
export type ActiveTab = "overview" | "records";

interface TrafficSummaryBucket {
  bucket: string;
  avg_vehicle_count: number;
  avg_speed: number | null;
  avg_speed_kmh: number | null;
  avg_congestion: number;
  avg_congestion_level: number;
  record_count: number;
}

interface VehicleEventItem {
  id: number;
  intersection_id?: number | null;
  lane_id?: number | null;
  event_type: string;
  vehicle_type: string;
  speed_kmh?: number | null;
  direction?: string | null;
  confidence?: number | null;
  detected_at: string;
}

interface PaginatedVehicleEvents {
  items: VehicleEventItem[];
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

interface CongestionHotspot {
  intersection_id: number;
  name: string;
  code: string;
  avg_congestion_level: number;
  avg_congestion: number;
  record_count: number;
}

interface TrafficRecordItem {
  id: number;
  intersection_id: number;
  lane_id?: number | null;
  recorded_at: string;
  vehicle_count: number;
  avg_speed_kmh?: number | null;
  congestion_level: number;
  source: string;
  intersection?: { id: number; name: string; code: string } | null;
  lane?: { id: number } | null;
}

interface PaginatedTrafficRecords {
  items: TrafficRecordItem[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

interface CreateRecordPayload {
  intersection_id: number;
  lane_id?: number | null;
  vehicle_count: number;
  avg_speed_kmh?: number | null;
  congestion_level: number;
  source: string;
}

export default function TrafficPage() {
  const { user, canWrite } = useAuth();
  const [activeTab, setActiveTab] = useState<ActiveTab>("overview");
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [selectedJunctionId, setSelectedJunctionId] = useState<number | "all">("all");

  // Telemetry records tab states
  const [recordsPage, setRecordsPage] = useState(1);
  const [recordSourceFilter, setRecordSourceFilter] = useState<string>("all");
  const [showIngestModal, setShowIngestModal] = useState(false);

  // Ingest Form States
  const [ingestIntersectionId, setIngestIntersectionId] = useState<number | "">("");
  const [ingestVehicleCount, setIngestVehicleCount] = useState<number>(25);
  const [ingestAvgSpeed, setIngestAvgSpeed] = useState<number>(42);
  const [ingestCongestion, setIngestCongestion] = useState<number>(35);
  const [ingestSource, setIngestSource] = useState<string>("sensor");
  const [ingestError, setIngestError] = useState<string | null>(null);
  const [ingestSuccess, setIngestSuccess] = useState<string | null>(null);

  // Compute ISO time window based on selected timeRange
  const { fromIso, toIso, bucketUnit } = useMemo(() => {
    const now = new Date();
    let past = new Date(now);
    let unit = "hour";

    switch (timeRange) {
      case "1h":
        past = new Date(now.getTime() - 60 * 60 * 1000);
        unit = "hour";
        break;
      case "6h":
        past = new Date(now.getTime() - 6 * 60 * 60 * 1000);
        unit = "hour";
        break;
      case "24h":
        past = new Date(now.getTime() - 24 * 60 * 60 * 1000);
        unit = "hour";
        break;
      case "7d":
        past = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
        unit = "day";
        break;
    }

    return {
      fromIso: past.toISOString(),
      toIso: now.toISOString(),
      bucketUnit: unit,
    };
  }, [timeRange]);

  // Fetch junctions list for filtering
  const {
    data: junctionsData,
  } = useApiQuery<PaginatedJunctions>({
    queryKey: ["junctions-filter-list"],
    endpoint: "/junctions",
    params: { per_page: 100 },
    queryOptions: {
      refetchInterval: 30000,
    },
  });

  // Fetch traffic summary telemetry buckets
  const summaryParams = useMemo(() => {
    const params: Record<string, string | number> = {
      from: fromIso,
      to: toIso,
      bucket: bucketUnit,
    };
    if (selectedJunctionId !== "all") {
      params.intersection_id = selectedJunctionId;
    }
    return params;
  }, [fromIso, toIso, bucketUnit, selectedJunctionId]);

  const {
    data: summaryData,
    isLoading: summaryLoading,
    error: summaryError,
    refetch: refetchSummary,
  } = useApiQuery<TrafficSummaryBucket[]>({
    queryKey: ["traffic-summary", summaryParams],
    endpoint: "/analytics/traffic-summary",
    params: summaryParams,
    queryOptions: {
      refetchInterval: 30000,
    },
  });

  // Fetch vehicle detection events for classification & live feed
  const eventParams = useMemo(() => {
    const params: Record<string, string | number> = {
      detected_from: fromIso,
      detected_to: toIso,
      per_page: 100,
    };
    if (selectedJunctionId !== "all") {
      params.intersection_id = selectedJunctionId;
    }
    return params;
  }, [fromIso, toIso, selectedJunctionId]);

  const {
    data: eventsData,
    isLoading: eventsLoading,
    error: eventsError,
    refetch: refetchEvents,
  } = useApiQuery<PaginatedVehicleEvents>({
    queryKey: ["vehicle-events-traffic", eventParams],
    endpoint: "/vehicle-events",
    params: eventParams,
    queryOptions: {
      refetchInterval: 30000,
    },
  });

  // Fetch top congestion hotspots
  const {
    data: hotspotsData,
    refetch: refetchHotspots,
  } = useApiQuery<CongestionHotspot[]>({
    queryKey: ["congestion-hotspots-summary", fromIso, toIso],
    endpoint: "/analytics/congestion-hotspots",
    params: { from: fromIso, to: toIso, limit: 5 },
    queryOptions: {
      refetchInterval: 30000,
    },
  });

  // Fetch paginated raw telemetry records from /traffic-records
  const recordsQueryParams = useMemo(() => {
    const params: Record<string, string | number> = {
      page: recordsPage,
      per_page: 20,
    };
    if (selectedJunctionId !== "all") {
      params.intersection_id = selectedJunctionId;
    }
    if (recordSourceFilter !== "all") {
      params.source = recordSourceFilter;
    }
    return params;
  }, [recordsPage, selectedJunctionId, recordSourceFilter]);

  const {
    data: recordsData,
    isLoading: recordsLoading,
    error: recordsError,
    refetch: refetchRecords,
  } = useApiQuery<PaginatedTrafficRecords>({
    queryKey: ["traffic-records-list", recordsQueryParams],
    endpoint: "/traffic-records",
    params: recordsQueryParams,
    queryOptions: {
      refetchInterval: 30000,
    },
  });

  // Mutation for creating a traffic record (Officer/Admin only)
  const createRecordMutation = useApiMutation<TrafficRecordItem, CreateRecordPayload>({
    endpoint: "/traffic-records",
    method: "POST",
  });

  const handleIngestSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIngestError(null);
    setIngestSuccess(null);

    if (ingestIntersectionId === "") {
      setIngestError("Please select an intersection");
      return;
    }

    try {
      await createRecordMutation.mutateAsync({
        intersection_id: Number(ingestIntersectionId),
        vehicle_count: Number(ingestVehicleCount),
        avg_speed_kmh: Number(ingestAvgSpeed),
        congestion_level: Number(ingestCongestion),
        source: ingestSource,
      });

      setIngestSuccess("Telemetry record successfully ingested into system!");
      refetchRecords();
      refetchSummary();
      setTimeout(() => {
        setShowIngestModal(false);
        setIngestSuccess(null);
      }, 1500);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create traffic record";
      setIngestError(msg);
    }
  };

  // Aggregate Vehicle Counts by Class
  const { vehicleClassChartData, classBreakdown } = useMemo(() => {
    const counts: Record<string, number> = {
      car: 0,
      truck: 0,
      bus: 0,
      motorcycle: 0,
      bicycle: 0,
    };

    if (eventsData?.items && eventsData.items.length > 0) {
      eventsData.items.forEach((event) => {
        const type = (event.vehicle_type || "car").toLowerCase().trim();
        if (type in counts) {
          counts[type] += 1;
        } else {
          counts[type] = (counts[type] || 0) + 1;
        }
      });
    }

    const chartData: VehicleClassItem[] = [
      { name: "Car", count: counts.car || 0, color: "#00D9A8" },
      { name: "Truck", count: counts.truck || 0, color: "#FFB800" },
      { name: "Bus", count: counts.bus || 0, color: "#38BDF8" },
      { name: "Motorcycle", count: counts.motorcycle || 0, color: "#A855F7" },
      { name: "Bicycle", count: counts.bicycle || 0, color: "#22C55E" },
    ];

    return {
      vehicleClassChartData: chartData,
      classBreakdown: counts,
    };
  }, [eventsData]);

  // Aggregate Metrics & Chart Points from Summary Buckets
  const {
    densityChartData,
    areaChartData,
    avgCongestion,
    avgSpeed,
    avgQueueLength,
    peakQueueLength,
    estimatedWaitTimeSeconds,
    totalVolume,
    totalRecordsCount,
  } = useMemo(() => {
    if (!summaryData || summaryData.length === 0) {
      return {
        densityChartData: [] as DensityPoint[],
        areaChartData: [] as AreaTrafficPoint[],
        avgCongestion: 0,
        avgSpeed: null as number | null,
        avgQueueLength: 0,
        peakQueueLength: 0,
        estimatedWaitTimeSeconds: 0,
        totalVolume: 0,
        totalRecordsCount: recordsData?.total ?? 0,
      };
    }

    let sumCongestion = 0;
    let sumSpeed = 0;
    let speedSamples = 0;
    let sumVehicles = 0;
    let maxQueue = 0;
    let totalRecords = 0;

    const densityPoints: DensityPoint[] = [];
    const areaPoints: AreaTrafficPoint[] = [];

    summaryData.forEach((b) => {
      const cong = b.avg_congestion_level ?? b.avg_congestion ?? 0;
      const speed = b.avg_speed_kmh ?? b.avg_speed;
      const count = b.avg_vehicle_count ?? 0;
      const records = b.record_count ?? 0;

      sumCongestion += cong;
      if (speed !== null && speed !== undefined) {
        sumSpeed += speed;
        speedSamples += 1;
      }
      sumVehicles += count;
      totalRecords += records;

      const bucketQueue = (cong / 100.0) * count;
      if (bucketQueue > maxQueue) {
        maxQueue = bucketQueue;
      }

      const formattedLabel =
        bucketUnit === "day" ? formatDateTime(b.bucket) : formatTime(b.bucket);

      densityPoints.push({
        time: formattedLabel,
        density: Math.round(cong),
        occupancy: Math.round(cong),
        speed: speed !== null && speed !== undefined ? Math.round(speed) : null,
      });

      areaPoints.push({
        time: formattedLabel,
        vehicles: Math.round(count),
        speed: speed !== null && speed !== undefined ? Math.round(speed) : null,
        congestion: Math.round(cong),
      });
    });

    const countBuckets = summaryData.length;
    const meanCongestion = countBuckets > 0 ? sumCongestion / countBuckets : 0;
    const meanSpeed = speedSamples > 0 ? sumSpeed / speedSamples : null;
    const meanQueue = countBuckets > 0 ? (meanCongestion / 100.0) * (sumVehicles / countBuckets) : 0;

    const waitSeconds = Math.round(
      meanQueue * 2.0 + (meanCongestion > 50 ? (meanCongestion - 50) * 0.75 : 0)
    );

    return {
      densityChartData: densityPoints,
      areaChartData: areaPoints,
      avgCongestion: meanCongestion,
      avgSpeed: meanSpeed,
      avgQueueLength: meanQueue,
      peakQueueLength: maxQueue,
      estimatedWaitTimeSeconds: waitSeconds,
      totalVolume: Math.round(sumVehicles),
      totalRecordsCount: recordsData?.total ?? totalRecords,
    };
  }, [summaryData, bucketUnit, recordsData?.total]);

  const handleRefreshAll = () => {
    refetchSummary();
    refetchEvents();
    refetchHotspots();
    refetchRecords();
  };

  const isInitialLoading = summaryLoading && !summaryData;
  const isError = summaryError || eventsError;

  return (
    <div className="max-w-7xl mx-auto space-y-8">
      {/* Page Header & Filtering Controls */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 p-6 rounded-2xl bg-surface/70 border border-white/10 backdrop-blur-sm">
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <h1 className="text-2xl sm:text-3xl font-display font-bold text-text tracking-tight">
              Traffic Perception & Telemetry
            </h1>
            <Badge variant="teal" dot>
              Telemetry Live
            </Badge>
          </div>
          <p className="text-xs sm:text-sm text-muted">
            Multi-class vehicle classification, optical tracking, spatial density, and /traffic-records ingestion.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Intersection Selector */}
          <div className="flex items-center gap-2 bg-ink/60 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-muted">
            <MapPin className="w-3.5 h-3.5 text-accent shrink-0" />
            <select
              value={selectedJunctionId}
              onChange={(e) => {
                setSelectedJunctionId(
                  e.target.value === "all" ? "all" : Number(e.target.value)
                );
                setRecordsPage(1);
              }}
              className="bg-transparent text-text border-none focus:outline-none cursor-pointer pr-2"
              aria-label="Filter by intersection"
            >
              <option value="all" className="bg-ink text-text">
                All Intersections ({junctionsData?.total ?? 0})
              </option>
              {junctionsData?.items.map((j) => (
                <option key={j.id} value={j.id} className="bg-ink text-text">
                  {j.name} ({j.code})
                </option>
              ))}
            </select>
          </div>

          {/* Time Range Selector (only in overview tab) */}
          {activeTab === "overview" && (
            <div className="flex items-center bg-ink/60 border border-white/10 rounded-xl p-1 text-xs">
              {(["1h", "6h", "24h", "7d"] as TimeRange[]).map((range) => {
                const active = timeRange === range;
                return (
                  <button
                    key={range}
                    type="button"
                    onClick={() => setTimeRange(range)}
                    className={`px-3 py-1 rounded-lg font-medium transition-all cursor-pointer ${
                      active
                        ? "bg-accent text-ink font-semibold shadow-sm"
                        : "text-muted hover:text-text hover:bg-white/5"
                    }`}
                  >
                    {range}
                  </button>
                );
              })}
            </div>
          )}

          {/* Refresh Button */}
          <Button
            variant="secondary"
            size="sm"
            onClick={handleRefreshAll}
            disabled={summaryLoading || eventsLoading || recordsLoading}
            title="Refresh telemetry"
          >
            <RefreshCw
              className={`w-3.5 h-3.5 ${
                summaryLoading || eventsLoading || recordsLoading ? "animate-spin" : ""
              }`}
            />
          </Button>

          {/* Ingest Traffic Record Write Action (Officer / Admin Only) */}
          {canWrite() ? (
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                setIngestError(null);
                setIngestSuccess(null);
                if (junctionsData?.items && junctionsData.items.length > 0 && ingestIntersectionId === "") {
                  setIngestIntersectionId(junctionsData.items[0].id);
                }
                setShowIngestModal(true);
              }}
            >
              <Plus className="w-4 h-4 mr-1.5" />
              Ingest Record
            </Button>
          ) : (
            <Button
              variant="secondary"
              size="sm"
              disabled
              title="Write access requires Officer or Admin role"
              className="opacity-50 cursor-not-allowed"
            >
              <Plus className="w-4 h-4 mr-1.5 text-muted" />
              Ingest (Read-Only)
            </Button>
          )}
        </div>
      </div>

      {/* Navigation Tabs: Overview vs Records Ledger */}
      <div className="flex items-center gap-3 border-b border-white/10 pb-3">
        <button
          type="button"
          onClick={() => setActiveTab("overview")}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs sm:text-sm font-medium transition-all cursor-pointer ${
            activeTab === "overview"
              ? "bg-accent/15 text-accent border border-accent/30 font-semibold shadow-sm"
              : "text-muted hover:text-text hover:bg-surface/50"
          }`}
        >
          <BarChart3 className="w-4 h-4" />
          <span>Perception & Visuals</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("records")}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs sm:text-sm font-medium transition-all cursor-pointer ${
            activeTab === "records"
              ? "bg-accent/15 text-accent border border-accent/30 font-semibold shadow-sm"
              : "text-muted hover:text-text hover:bg-surface/50"
          }`}
        >
          <FileSpreadsheet className="w-4 h-4" />
          <span>Telemetry Ledger (/traffic-records)</span>
          {recordsData && (
            <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-accent/20 text-accent font-mono">
              {recordsData.total}
            </span>
          )}
        </button>
      </div>

      {/* Ingest Modal */}
      {showIngestModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink/80 backdrop-blur-sm animate-in fade-in">
          <Card className="w-full max-w-lg p-6 bg-surface/95 border-white/20 shadow-2xl relative">
            <button
              type="button"
              onClick={() => setShowIngestModal(false)}
              className="absolute top-4 right-4 p-1.5 rounded-lg text-muted hover:text-text hover:bg-white/5"
            >
              <X className="w-4 h-4" />
            </button>

            <div className="flex items-center gap-2 mb-1">
              <Plus className="w-5 h-5 text-accent" />
              <h2 className="text-lg font-display font-bold text-text">
                Ingest Traffic Record
              </h2>
            </div>
            <p className="text-xs text-muted mb-4">
              Authorized supervisory endpoint (POST /api/v1/traffic-records). Requires Officer or Admin clearance.
            </p>

            {ingestError && (
              <div className="mb-4 p-3 rounded-xl bg-danger/10 border border-danger/30 text-danger text-xs flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{ingestError}</span>
              </div>
            )}

            {ingestSuccess && (
              <div className="mb-4 p-3 rounded-xl bg-success/10 border border-success/30 text-success text-xs flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 shrink-0" />
                <span>{ingestSuccess}</span>
              </div>
            )}

            <form onSubmit={handleIngestSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-muted uppercase tracking-wider mb-1">
                  Intersection
                </label>
                <select
                  value={ingestIntersectionId}
                  onChange={(e) => setIngestIntersectionId(Number(e.target.value))}
                  required
                  className="w-full px-3 py-2 bg-ink/70 border border-white/10 rounded-xl text-xs text-text focus:outline-none focus:border-accent"
                >
                  <option value="" disabled>
                    Select an intersection
                  </option>
                  {junctionsData?.items.map((j) => (
                    <option key={j.id} value={j.id}>
                      {j.name} ({j.code})
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-muted uppercase tracking-wider mb-1">
                    Vehicle Count
                  </label>
                  <input
                    type="number"
                    min={0}
                    required
                    value={ingestVehicleCount}
                    onChange={(e) => setIngestVehicleCount(Number(e.target.value))}
                    className="w-full px-3 py-2 bg-ink/70 border border-white/10 rounded-xl text-xs text-text focus:outline-none focus:border-accent"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-muted uppercase tracking-wider mb-1">
                    Avg Speed (km/h)
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={300}
                    step="0.1"
                    required
                    value={ingestAvgSpeed}
                    onChange={(e) => setIngestAvgSpeed(Number(e.target.value))}
                    className="w-full px-3 py-2 bg-ink/70 border border-white/10 rounded-xl text-xs text-text focus:outline-none focus:border-accent"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-muted uppercase tracking-wider mb-1">
                    Congestion Level (0-100%)
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    step="0.1"
                    required
                    value={ingestCongestion}
                    onChange={(e) => setIngestCongestion(Number(e.target.value))}
                    className="w-full px-3 py-2 bg-ink/70 border border-white/10 rounded-xl text-xs text-text focus:outline-none focus:border-accent"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-muted uppercase tracking-wider mb-1">
                    Observation Source
                  </label>
                  <select
                    value={ingestSource}
                    onChange={(e) => setIngestSource(e.target.value)}
                    className="w-full px-3 py-2 bg-ink/70 border border-white/10 rounded-xl text-xs text-text focus:outline-none focus:border-accent"
                  >
                    <option value="sensor">Sensor</option>
                    <option value="camera">Camera</option>
                    <option value="ai">AI Vision</option>
                    <option value="manual">Manual</option>
                  </select>
                </div>
              </div>

              <div className="pt-2 flex justify-end gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => setShowIngestModal(false)}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  disabled={createRecordMutation.isPending}
                >
                  {createRecordMutation.isPending ? "Ingesting..." : "Ingest Telemetry"}
                </Button>
              </div>
            </form>
          </Card>
        </div>
      )}

      {/* TAB 1: OVERVIEW & ANALYTICS */}
      {activeTab === "overview" && (
        <>
          {isInitialLoading ? (
            <div className="py-20 flex flex-col items-center justify-center">
              <LoadingSpinner size="lg" label="Querying traffic telemetry and perception feeds..." />
            </div>
          ) : isError ? (
            <ErrorState
              title="Telemetry Feed Unavailable"
              message={
                summaryError?.message ||
                eventsError?.message ||
                "Unable to reach the traffic analytics backend at /api/v1/analytics."
              }
              onRetry={handleRefreshAll}
              retryText="Retry Connection"
            />
          ) : (!summaryData || summaryData.length === 0) && (!eventsData?.items || eventsData.items.length === 0) ? (
            <EmptyState
              icon={<Car className="w-8 h-8 text-accent" />}
              title="No Traffic Observations Recorded"
              description={`No telemetry records or vehicle detections were ingested within the selected ${timeRange} window.`}
              action={{
                label: "Refresh Observation Window",
                onClick: handleRefreshAll,
              }}
            />
          ) : (
            <>
              {/* Key KPI Cards */}
              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
                <Stat
                  label="Density / Occupancy"
                  value={formatPercent(avgCongestion, 1)}
                  helperText={`${getCongestionStatus(avgCongestion).label} spatial road occupancy`}
                />

                <Stat
                  label="Avg Queue Length"
                  value={`${formatNumber(avgQueueLength, 1)} veh`}
                  helperText={`Peak: ${formatNumber(peakQueueLength, 1)} veh in window`}
                />

                <Stat
                  label="Est. Wait Delay"
                  value={formatDuration(estimatedWaitTimeSeconds)}
                  helperText="Mean stop-bar signal waiting time"
                />

                <Stat
                  label="Mean Speed"
                  value={formatSpeed(avgSpeed)}
                  helperText="Corridor velocity across lanes"
                />

                <Stat
                  label="Detections (Window)"
                  value={formatNumber(eventsData?.total ?? 0)}
                  helperText={`From ${formatNumber(totalRecordsCount)} sensor records`}
                  className="col-span-2 md:col-span-4 lg:col-span-1"
                />
              </div>

              {/* Vehicle Classification Row */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <Card className="lg:col-span-2 p-6 flex flex-col justify-between">
                  <div>
                    <div className="flex items-center justify-between mb-4">
                      <div className="flex items-center gap-2">
                        <div className="w-8 h-8 rounded-lg bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
                          <BarChart3 className="w-4 h-4" />
                        </div>
                        <div>
                          <h2 className="font-display font-semibold text-text text-base">
                            Vehicle Classification Distribution
                          </h2>
                          <p className="text-xs text-muted">
                            Object recognition counts categorized by detected chassis class (/vehicle-events)
                          </p>
                        </div>
                      </div>
                      <Badge variant="teal">Vision Inference</Badge>
                    </div>

                    <div className="pt-2">
                      <VehicleClassBarChart
                        data={vehicleClassChartData}
                        height={260}
                      />
                    </div>
                  </div>

                  {/* Class Pills */}
                  <div className="grid grid-cols-3 sm:grid-cols-5 gap-2 pt-4 mt-4 border-t border-white/5 text-xs font-mono">
                    <div className="bg-ink/50 p-2 rounded-lg border border-white/5 flex items-center gap-2">
                      <Car className="w-3.5 h-3.5 text-accent shrink-0" />
                      <div>
                        <span className="text-muted block text-[10px]">Cars</span>
                        <span className="text-text font-bold">{classBreakdown.car || 0}</span>
                      </div>
                    </div>

                    <div className="bg-ink/50 p-2 rounded-lg border border-white/5 flex items-center gap-2">
                      <Truck className="w-3.5 h-3.5 text-amber shrink-0" />
                      <div>
                        <span className="text-muted block text-[10px]">Trucks</span>
                        <span className="text-text font-bold">{classBreakdown.truck || 0}</span>
                      </div>
                    </div>

                    <div className="bg-ink/50 p-2 rounded-lg border border-white/5 flex items-center gap-2">
                      <Bus className="w-3.5 h-3.5 text-[#38BDF8] shrink-0" />
                      <div>
                        <span className="text-muted block text-[10px]">Buses</span>
                        <span className="text-text font-bold">{classBreakdown.bus || 0}</span>
                      </div>
                    </div>

                    <div className="bg-ink/50 p-2 rounded-lg border border-white/5 flex items-center gap-2">
                      <Activity className="w-3.5 h-3.5 text-[#A855F7] shrink-0" />
                      <div>
                        <span className="text-muted block text-[10px]">M-Cycles</span>
                        <span className="text-text font-bold">{classBreakdown.motorcycle || 0}</span>
                      </div>
                    </div>

                    <div className="bg-ink/50 p-2 rounded-lg border border-white/5 flex items-center gap-2">
                      <Bike className="w-3.5 h-3.5 text-[#22C55E] shrink-0" />
                      <div>
                        <span className="text-muted block text-[10px]">Bicycles</span>
                        <span className="text-text font-bold">{classBreakdown.bicycle || 0}</span>
                      </div>
                    </div>
                  </div>
                </Card>

                {/* Congestion Hotspots Panel */}
                <Card className="p-6 flex flex-col justify-between">
                  <div>
                    <div className="flex items-center justify-between mb-4">
                      <div className="flex items-center gap-2">
                        <div className="w-8 h-8 rounded-lg bg-amber/15 border border-amber/30 flex items-center justify-center text-amber">
                          <Gauge className="w-4 h-4" />
                        </div>
                        <div>
                          <h2 className="font-display font-semibold text-text text-base">
                            Congestion Hotspots
                          </h2>
                          <p className="text-xs text-muted">
                            Top bottlenecks from /analytics/congestion-hotspots
                          </p>
                        </div>
                      </div>
                    </div>

                    <div className="space-y-3">
                      {hotspotsData && hotspotsData.length > 0 ? (
                        hotspotsData.map((hotspot, idx) => {
                          const cong = hotspot.avg_congestion_level ?? hotspot.avg_congestion;
                          const status = getCongestionStatus(cong);
                          return (
                            <div
                              key={hotspot.intersection_id}
                              className="p-3 rounded-xl bg-ink/40 border border-white/5 flex items-center justify-between gap-3 hover:border-white/20 transition-colors"
                            >
                              <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                  <span className="text-xs font-mono font-bold text-muted">
                                    #{idx + 1}
                                  </span>
                                  <span className="text-xs font-semibold text-text truncate">
                                    {hotspot.name}
                                  </span>
                                </div>
                                <span className="text-[10px] text-muted font-mono block mt-0.5">
                                  {hotspot.code} • {hotspot.record_count} observations
                                </span>
                              </div>

                              <div className="text-right shrink-0">
                                <span
                                  className="text-xs font-mono font-bold block"
                                  style={{ color: status.hex }}
                                >
                                  {formatPercent(cong, 0)}
                                </span>
                                <span className="text-[10px] text-muted font-mono">
                                  {status.label}
                                </span>
                              </div>
                            </div>
                          );
                        })
                      ) : (
                        <div className="p-8 text-center text-xs text-muted font-mono bg-ink/30 rounded-xl border border-white/5">
                          No hotspots detected in this interval
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="pt-4 mt-4 border-t border-white/5 text-[11px] text-muted flex items-center justify-between">
                    <span>Polling cadence:</span>
                    <span className="font-mono text-accent">30 seconds</span>
                  </div>
                </Card>
              </div>

              {/* Temporal Trends: Density & Volume Charts */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Density & Occupancy Line Chart */}
                <Card className="p-6">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <div className="w-8 h-8 rounded-lg bg-amber/15 border border-amber/30 flex items-center justify-center text-amber">
                        <TrendingUp className="w-4 h-4" />
                      </div>
                      <div>
                        <h2 className="font-display font-semibold text-text text-base">
                          Density & Occupancy Over Time
                        </h2>
                        <p className="text-xs text-muted">
                          Corridor saturation index (%) aggregated by {bucketUnit}
                        </p>
                      </div>
                    </div>
                    <Badge variant="amber">Temporal Density</Badge>
                  </div>

                  <DensityLineChart data={densityChartData} height={260} />
                </Card>

                {/* Vehicle Volume Area Chart */}
                <Card className="p-6">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <div className="w-8 h-8 rounded-lg bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
                        <Layers className="w-4 h-4" />
                      </div>
                      <div>
                        <h2 className="font-display font-semibold text-text text-base">
                          Telemetry Volumetric Flow
                        </h2>
                        <p className="text-xs text-muted">
                          Average vehicular count per observation bucket
                        </p>
                      </div>
                    </div>
                    <Badge variant="teal">Volumetric Flow</Badge>
                  </div>

                  <AreaTrafficChart
                    data={areaChartData}
                    height={260}
                    showCongestion={true}
                  />
                </Card>
              </div>

              {/* Live Recent Vehicle Events Feed */}
              <Card className="p-6">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
                  <div>
                    <h2 className="font-display font-semibold text-text text-base">
                      Live Vehicle Perception Feed
                    </h2>
                    <p className="text-xs text-muted">
                      Recent vision detections ingested from camera sensors (/vehicle-events)
                    </p>
                  </div>
                  <Badge variant="teal" dot>
                    {eventsData?.total ?? 0} Events in Window
                  </Badge>
                </div>

                {eventsData?.items && eventsData.items.length > 0 ? (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead>
                        <tr className="border-b border-white/10 text-muted font-mono uppercase text-[11px]">
                          <th className="py-2.5 px-3">Timestamp</th>
                          <th className="py-2.5 px-3">Chassis Class</th>
                          <th className="py-2.5 px-3">Speed</th>
                          <th className="py-2.5 px-3">Direction</th>
                          <th className="py-2.5 px-3">Confidence</th>
                          <th className="py-2.5 px-3 text-right">Event ID</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5 font-mono">
                        {eventsData.items.slice(0, 10).map((event) => (
                          <tr
                            key={event.id}
                            className="hover:bg-white/[0.02] transition-colors"
                          >
                            <td className="py-2.5 px-3 text-muted">
                              {formatDateTime(event.detected_at)}
                            </td>
                            <td className="py-2.5 px-3">
                              <span className="capitalize font-semibold text-text">
                                {event.vehicle_type}
                              </span>
                            </td>
                            <td className="py-2.5 px-3 text-accent font-medium">
                              {event.speed_kmh != null
                                ? formatSpeed(event.speed_kmh)
                                : "—"}
                            </td>
                            <td className="py-2.5 px-3 text-muted capitalize">
                              {event.direction || "—"}
                            </td>
                            <td className="py-2.5 px-3">
                              {event.confidence != null ? (
                                <span className="text-text font-medium">
                                  {Math.round(event.confidence * 100)}%
                                </span>
                              ) : (
                                "—"
                              )}
                            </td>
                            <td className="py-2.5 px-3 text-right text-muted/70">
                              #{event.id}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="p-8 text-center text-xs text-muted font-mono bg-ink/30 rounded-xl border border-white/5">
                    No recent vehicle detection events captured
                  </div>
                )}
              </Card>
            </>
          )}
        </>
      )}

      {/* TAB 2: TELEMETRY LEDGER (/traffic-records) */}
      {activeTab === "records" && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-display font-semibold text-text">
                Ingested Traffic Records
              </h2>
              <p className="text-xs text-muted">
                Immutable observation log retrieved directly from /traffic-records with junction relations.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 bg-ink/60 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-muted">
                <Filter className="w-3.5 h-3.5 text-accent shrink-0" />
                <select
                  value={recordSourceFilter}
                  onChange={(e) => {
                    setRecordSourceFilter(e.target.value);
                    setRecordsPage(1);
                  }}
                  className="bg-transparent text-text border-none focus:outline-none cursor-pointer"
                  aria-label="Filter records by source"
                >
                  <option value="all" className="bg-ink text-text">All Sources</option>
                  <option value="sensor" className="bg-ink text-text">Sensor</option>
                  <option value="camera" className="bg-ink text-text">Camera</option>
                  <option value="ai" className="bg-ink text-text">AI Vision</option>
                  <option value="manual" className="bg-ink text-text">Manual</option>
                </select>
              </div>

              <div className="text-xs text-muted font-mono bg-surface/80 px-3 py-1.5 rounded-lg border border-white/10">
                Total: {recordsData?.total ?? "..."}
              </div>
            </div>
          </div>

          {recordsLoading && !recordsData ? (
            <div className="py-20 flex justify-center">
              <LoadingSpinner size="lg" label="Querying /traffic-records database..." />
            </div>
          ) : recordsError ? (
            <ErrorState
              title="Failed to Load Telemetry Records"
              message={recordsError.message}
              onRetry={() => refetchRecords()}
            />
          ) : !recordsData?.items || recordsData.items.length === 0 ? (
            <EmptyState
              icon={<FileSpreadsheet className="w-8 h-8 text-accent" />}
              title="No Traffic Records Found"
              description="No telemetry records match the current intersection and source filters."
            />
          ) : (
            <Card className="overflow-hidden border-white/10">
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs sm:text-sm">
                  <thead>
                    <tr className="border-b border-white/10 bg-surface/60 text-muted uppercase text-[11px] font-semibold tracking-wider font-mono">
                      <th className="py-3 px-4">Recorded At</th>
                      <th className="py-3 px-4">Intersection</th>
                      <th className="py-3 px-4">Vehicles</th>
                      <th className="py-3 px-4">Avg Speed</th>
                      <th className="py-3 px-4">Congestion</th>
                      <th className="py-3 px-4">Source</th>
                      <th className="py-3 px-4 text-right">ID</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5 font-mono text-xs">
                    {recordsData.items.map((r) => {
                      const congStatus = getCongestionStatus(r.congestion_level);
                      return (
                        <tr key={r.id} className="hover:bg-white/[0.02] transition-colors">
                          <td className="py-3 px-4 text-muted">
                            {formatDateTime(r.recorded_at)}
                          </td>
                          <td className="py-3 px-4">
                            <span className="font-sans font-semibold text-text">
                              {r.intersection?.name || `Intersection #${r.intersection_id}`}
                            </span>
                            {r.intersection?.code && (
                              <span className="text-[10px] text-muted block">
                                {r.intersection.code}
                              </span>
                            )}
                          </td>
                          <td className="py-3 px-4 font-bold text-text">
                            {r.vehicle_count}
                          </td>
                          <td className="py-3 px-4 text-accent">
                            {r.avg_speed_kmh != null ? formatSpeed(r.avg_speed_kmh) : "—"}
                          </td>
                          <td className="py-3 px-4">
                            <span
                              className="font-bold"
                              style={{ color: congStatus.hex }}
                            >
                              {formatPercent(r.congestion_level, 0)}
                            </span>
                            <span className="text-[10px] text-muted ml-1.5 font-sans">
                              ({congStatus.label})
                            </span>
                          </td>
                          <td className="py-3 px-4">
                            <Badge variant="muted" className="text-[10px] capitalize">
                              {r.source}
                            </Badge>
                          </td>
                          <td className="py-3 px-4 text-right text-muted/60">
                            #{r.id}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {recordsData.pages > 1 && (
                <div className="p-4 border-t border-white/10 flex items-center justify-between text-xs text-muted">
                  <span>
                    Page {recordsData.page} of {recordsData.pages}
                  </span>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={recordsPage <= 1}
                      onClick={() => setRecordsPage((p) => Math.max(1, p - 1))}
                      className="px-3 py-1 rounded bg-surface border border-white/10 disabled:opacity-40 hover:text-text cursor-pointer disabled:cursor-not-allowed"
                    >
                      Previous
                    </button>
                    <button
                      type="button"
                      disabled={recordsPage >= recordsData.pages}
                      onClick={() => setRecordsPage((p) => Math.min(recordsData.pages, p + 1))}
                      className="px-3 py-1 rounded bg-surface border border-white/10 disabled:opacity-40 hover:text-text cursor-pointer disabled:cursor-not-allowed"
                    >
                      Next
                    </button>
                  </div>
                </div>
              )}
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
