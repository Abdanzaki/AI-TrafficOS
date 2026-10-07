"use client";

import React, { useState, useMemo } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import {
  Map as MapIcon,
  MapPin,
  Radio,
  Car,
  AlertTriangle,
  RefreshCw,
  ExternalLink,
  ChevronRight,
  SlidersHorizontal,
  X,
  Gauge,
  Info,
} from "lucide-react";
import { useApiQuery } from "@/lib/use-api";
import { Card } from "@/components/ui/Card";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import type { MappedJunction } from "@/components/map/TrafficMap";
import {
  formatDateTime,
  formatRelativeTime,
  formatSpeed,
  formatSeconds,
  getCongestionStatus,
} from "@/lib/format";

// Dynamically import Leaflet Map with ssr: false to prevent window/document hydration mismatches
const DynamicTrafficMap = dynamic(
  () => import("@/components/map/TrafficMap").then((mod) => mod.TrafficMap),
  {
    ssr: false,
    loading: () => (
      <div className="w-full h-full min-h-[500px] flex flex-col items-center justify-center bg-surface/50 border border-white/10 rounded-2xl">
        <LoadingSpinner size="lg" label="Initializing OpenStreetMap GIS canvas..." />
      </div>
    ),
  }
);

interface RawJunction {
  id: number;
  name: string;
  code: string;
  status: string;
  city?: string | null;
  zone?: string | null;
  lat?: number | null;
  lon?: number | null;
  created_at: string;
  updated_at: string;
}

interface PaginatedJunctions {
  items: RawJunction[];
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

interface SignalPhase {
  id: number;
  signal_id: number;
  intersection_id?: number | null;
  name: string;
  phase_order: number;
  duration_seconds: number;
  state: string;
  is_active: boolean;
}

interface SignalItem {
  id: number;
  intersection_id: number;
  code: string;
  status: string;
  observed_state?: string | null;
  observed_confidence?: number | null;
  observed_at?: string | null;
  phases?: SignalPhase[] | null;
}

interface PaginatedSignals {
  items: SignalItem[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
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

export default function MapPage() {
  const [selectedJunctionId, setSelectedJunctionId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [filterStatus, setFilterStatus] = useState<string>("all");

  // 1. Fetch Junctions / Intersections
  const {
    data: junctionsData,
    isLoading: junctionsLoading,
    error: junctionsError,
    refetch: refetchJunctions,
  } = useApiQuery<PaginatedJunctions>({
    queryKey: ["junctions-map-list"],
    endpoint: "/junctions",
    params: { per_page: 100 },
    queryOptions: {
      refetchInterval: 30000,
    },
  });

  // 2. Fetch Congestion Hotspots for live marker coloring
  const {
    data: hotspotsData,
    refetch: refetchHotspots,
  } = useApiQuery<CongestionHotspot[]>({
    queryKey: ["map-congestion-hotspots"],
    endpoint: "/analytics/congestion-hotspots",
    params: { limit: 100 },
    queryOptions: {
      refetchInterval: 30000,
    },
  });

  // 3. Fetch Signals for selected junction
  const {
    data: signalsData,
    isLoading: signalsLoading,
  } = useApiQuery<PaginatedSignals>({
    queryKey: ["signals-for-junction", selectedJunctionId],
    endpoint: "/signals",
    params: { intersection_id: selectedJunctionId ?? undefined, per_page: 20 },
    queryOptions: {
      enabled: selectedJunctionId !== null,
      refetchInterval: 30000,
    },
  });

  // 4. Fetch Recent Vehicle Events for selected junction
  const {
    data: eventsData,
    isLoading: eventsLoading,
  } = useApiQuery<PaginatedVehicleEvents>({
    queryKey: ["vehicle-events-for-junction", selectedJunctionId],
    endpoint: "/vehicle-events",
    params: { intersection_id: selectedJunctionId ?? undefined, per_page: 10 },
    queryOptions: {
      enabled: selectedJunctionId !== null,
      refetchInterval: 30000,
    },
  });

  // Hotspots lookup map by junction ID
  const hotspotMap = useMemo(() => {
    const map = new Map<number, CongestionHotspot>();
    if (hotspotsData && Array.isArray(hotspotsData)) {
      hotspotsData.forEach((h) => {
        map.set(h.intersection_id, h);
      });
    }
    return map;
  }, [hotspotsData]);

  // Separate mapped and unmapped junctions, with filtering
  const { mappedJunctions, unmappedJunctions, allFilteredCount } = useMemo(() => {
    if (!junctionsData?.items) {
      return { mappedJunctions: [], unmappedJunctions: [], allFilteredCount: 0 };
    }

    const query = searchQuery.trim().toLowerCase();
    const filtered = junctionsData.items.filter((j) => {
      const matchQuery =
        !query ||
        j.name.toLowerCase().includes(query) ||
        j.code.toLowerCase().includes(query) ||
        (j.city && j.city.toLowerCase().includes(query)) ||
        (j.zone && j.zone.toLowerCase().includes(query));

      const matchStatus =
        filterStatus === "all" || j.status.toLowerCase() === filterStatus.toLowerCase();

      return matchQuery && matchStatus;
    });

    const mapped: MappedJunction[] = [];
    const unmapped: RawJunction[] = [];

    filtered.forEach((j) => {
      const hotspot = hotspotMap.get(j.id);
      const congLevel = hotspot
        ? hotspot.avg_congestion_level ?? hotspot.avg_congestion
        : null;

      if (
        typeof j.lat === "number" &&
        typeof j.lon === "number" &&
        !isNaN(j.lat) &&
        !isNaN(j.lon)
      ) {
        mapped.push({
          id: j.id,
          name: j.name,
          code: j.code,
          status: j.status,
          city: j.city,
          zone: j.zone,
          lat: j.lat,
          lon: j.lon,
          congestionLevel: congLevel,
          recordCount: hotspot?.record_count,
        });
      } else {
        unmapped.push(j);
      }
    });

    return {
      mappedJunctions: mapped,
      unmappedJunctions: unmapped,
      allFilteredCount: filtered.length,
    };
  }, [junctionsData, hotspotMap, searchQuery, filterStatus]);

  // Find the selected junction full object
  const selectedJunction = useMemo(() => {
    if (!selectedJunctionId || !junctionsData?.items) return null;
    return junctionsData.items.find((j) => j.id === selectedJunctionId) ?? null;
  }, [selectedJunctionId, junctionsData]);

  const selectedCongestion = useMemo(() => {
    if (!selectedJunctionId) return null;
    const hotspot = hotspotMap.get(selectedJunctionId);
    return hotspot ? hotspot.avg_congestion_level ?? hotspot.avg_congestion : null;
  }, [selectedJunctionId, hotspotMap]);

  const handleRefresh = () => {
    refetchJunctions();
    refetchHotspots();
  };

  const getStatusBadgeVariant = (status: string): BadgeVariant => {
    switch (status.toLowerCase()) {
      case "active":
        return "teal";
      case "maintenance":
        return "amber";
      case "inactive":
        return "danger";
      default:
        return "muted";
    }
  };

  const getSignalStateBadge = (state: string | null | undefined) => {
    const s = state?.toLowerCase();
    if (s === "green") return <Badge variant="teal" dot>Green</Badge>;
    if (s === "yellow") return <Badge variant="amber" dot>Yellow</Badge>;
    if (s === "red") return <Badge variant="danger" dot>Red</Badge>;
    return <Badge variant="muted">Unknown</Badge>;
  };

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Top Controls Bar */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 p-6 rounded-2xl bg-surface/70 border border-white/10 backdrop-blur-sm">
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <h1 className="text-2xl sm:text-3xl font-display font-bold text-text tracking-tight">
              Geospatial Operations Map
            </h1>
            <Badge variant="teal" dot>
              OSM Vector GIS
            </Badge>
          </div>
          <p className="text-xs sm:text-sm text-muted">
            Live arterial intersection nodes, optical signal telemetry, and spatial congestion density.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Search Box */}
          <input
            type="text"
            placeholder="Search name, code, zone..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="px-3 py-1.5 rounded-xl bg-ink/60 border border-white/10 text-xs text-text placeholder-muted focus:outline-none focus:border-accent/50 w-44 sm:w-56"
          />

          {/* Status Filter */}
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className="px-3 py-1.5 rounded-xl bg-ink/60 border border-white/10 text-xs text-text focus:outline-none focus:border-accent/50 cursor-pointer"
            aria-label="Filter junctions by operating status"
          >
            <option value="all">All Statuses</option>
            <option value="active">Active</option>
            <option value="maintenance">Maintenance</option>
            <option value="inactive">Inactive</option>
          </select>

          {/* Refresh Action */}
          <Button
            variant="secondary"
            size="sm"
            onClick={handleRefresh}
            disabled={junctionsLoading}
            title="Refresh map telemetry"
          >
            <RefreshCw
              className={`w-3.5 h-3.5 ${junctionsLoading ? "animate-spin" : ""}`}
            />
          </Button>
        </div>
      </div>

      {/* Main Map + Side Panel Grid */}
      {junctionsLoading && !junctionsData ? (
        <div className="py-24 flex flex-col items-center justify-center">
          <LoadingSpinner size="lg" label="Loading intersection telemetry topology..." />
        </div>
      ) : junctionsError ? (
        <ErrorState
          title="Geospatial Telemetry Unavailable"
          message={
            junctionsError.message ||
            "Unable to connect to the junctions API at /api/v1/junctions."
          }
          onRetry={handleRefresh}
          retryText="Retry Connection"
        />
      ) : !junctionsData?.items || junctionsData.items.length === 0 ? (
        <EmptyState
          icon={<MapIcon className="w-8 h-8 text-accent" />}
          title="No Intersection Nodes Configured"
          description="No road intersections or physical junction controllers were found in the database."
          action={{
            label: "Refresh Network",
            onClick: handleRefresh,
          }}
        />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* Map & Unmapped Drawer Area (8 or 12 cols depending on side panel) */}
          <div
            className={`space-y-4 transition-all duration-300 ${
              selectedJunction ? "lg:col-span-8" : "lg:col-span-12"
            }`}
          >
            {/* Map Canvas Container */}
            <div className="w-full h-[580px] rounded-2xl overflow-hidden shadow-2xl relative">
              <DynamicTrafficMap
                junctions={mappedJunctions}
                selectedId={selectedJunctionId}
                onSelectJunction={(id) => setSelectedJunctionId(id)}
              />

              {/* Map floating stats chip */}
              <div className="absolute top-4 left-4 z-[1000] bg-surface/90 backdrop-blur-md border border-white/10 px-3.5 py-2 rounded-xl text-xs flex items-center gap-3 shadow-lg pointer-events-auto font-mono">
                <div className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-accent" />
                  <span className="text-text font-semibold">{mappedJunctions.length}</span>
                  <span className="text-muted">On Map</span>
                </div>
                <span className="text-white/20">•</span>
                <div className="flex items-center gap-1.5">
                  <span className="text-muted">{unmappedJunctions.length}</span>
                  <span className="text-muted">Unpositioned</span>
                </div>
              </div>
            </div>

            {/* Unpositioned Junctions Drawer (Safe display for nodes without lat/lon coordinates) */}
            {unmappedJunctions.length > 0 && (
              <Card className="p-4 bg-surface/60 border-white/10">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4 text-amber" />
                    <span className="font-display font-semibold text-xs text-text">
                      Unpositioned Nodes ({unmappedJunctions.length})
                    </span>
                    <span className="text-[11px] text-muted">
                      — Intersections awaiting GPS coordinates
                    </span>
                  </div>
                  <Badge variant="amber">No GPS</Badge>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2.5 max-h-48 overflow-y-auto pr-1">
                  {unmappedJunctions.map((j) => {
                    const isSelected = j.id === selectedJunctionId;
                    return (
                      <button
                        key={j.id}
                        type="button"
                        onClick={() => setSelectedJunctionId(j.id)}
                        className={`p-2.5 rounded-xl text-left border transition-all cursor-pointer flex items-center justify-between ${
                          isSelected
                            ? "bg-accent/15 border-accent text-accent"
                            : "bg-ink/50 border-white/5 hover:border-white/20 text-text"
                        }`}
                      >
                        <div className="min-w-0 pr-2">
                          <div className="text-xs font-semibold truncate font-display">
                            {j.name}
                          </div>
                          <div className="text-[10px] text-muted font-mono truncate mt-0.5">
                            {j.code} {j.city ? `• ${j.city}` : ""}
                          </div>
                        </div>
                        <ChevronRight className="w-3.5 h-3.5 text-muted shrink-0" />
                      </button>
                    );
                  })}
                </div>
              </Card>
            )}
          </div>

          {/* Selected Junction Details Side Panel */}
          {selectedJunction && (
            <div className="lg:col-span-4 space-y-4">
              <Card className="p-5 border-white/15 bg-surface/90 backdrop-blur-md shadow-2xl relative">
                {/* Close Button */}
                <button
                  type="button"
                  onClick={() => setSelectedJunctionId(null)}
                  className="absolute top-4 right-4 p-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-muted hover:text-text transition-colors cursor-pointer"
                  title="Close panel"
                >
                  <X className="w-4 h-4" />
                </button>

                {/* Junction Header */}
                <div className="pr-8">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge variant={getStatusBadgeVariant(selectedJunction.status)}>
                      {selectedJunction.status}
                    </Badge>
                    <span className="text-xs text-muted font-mono">
                      #{selectedJunction.id}
                    </span>
                  </div>

                  <h2 className="font-display font-bold text-lg text-text">
                    {selectedJunction.name}
                  </h2>
                  <div className="text-xs font-mono text-muted mt-0.5">
                    Hardware Code: {selectedJunction.code}
                  </div>
                </div>

                {/* Location & Coordinates Strip */}
                <div className="grid grid-cols-2 gap-2 mt-4 pt-4 border-t border-white/10 text-xs font-mono">
                  <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                    <span className="text-muted block text-[10px] uppercase">Zone / City</span>
                    <span className="text-text font-medium truncate block mt-0.5">
                      {selectedJunction.zone || selectedJunction.city || "Metropolitan"}
                    </span>
                  </div>

                  <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                    <span className="text-muted block text-[10px] uppercase">Coordinates</span>
                    <span className="text-text font-medium truncate block mt-0.5">
                      {selectedJunction.lat != null && selectedJunction.lon != null
                        ? `${selectedJunction.lat.toFixed(4)}, ${selectedJunction.lon.toFixed(4)}`
                        : "Unset"}
                    </span>
                  </div>
                </div>

                {/* Congestion Status Box */}
                <div className="mt-4 p-3 rounded-xl bg-ink/60 border border-white/10 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Gauge className="w-4 h-4 text-accent" />
                    <div>
                      <span className="text-xs font-semibold text-text block">
                        Congestion Status
                      </span>
                      <span className="text-[11px] text-muted font-mono">
                        {getCongestionStatus(selectedCongestion).label}
                      </span>
                    </div>
                  </div>

                  <span
                    className="text-sm font-mono font-bold"
                    style={{ color: getCongestionStatus(selectedCongestion).hex }}
                  >
                    {selectedCongestion != null
                      ? `${Math.round(selectedCongestion)}%`
                      : "Smooth"}
                  </span>
                </div>

                {/* Signals & Phases Feed */}
                <div className="mt-5 pt-4 border-t border-white/10 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 text-xs font-display font-semibold text-text">
                      <Radio className="w-3.5 h-3.5 text-accent" />
                      <span>Traffic Signals ({signalsData?.total ?? 0})</span>
                    </div>
                    <span className="text-[10px] font-mono text-muted">Controller Units</span>
                  </div>

                  {signalsLoading ? (
                    <div className="py-4 flex justify-center">
                      <LoadingSpinner size="sm" label="Querying signal phases..." />
                    </div>
                  ) : signalsData?.items && signalsData.items.length > 0 ? (
                    <div className="space-y-2.5 max-h-52 overflow-y-auto pr-1">
                      {signalsData.items.map((sig) => (
                        <div
                          key={sig.id}
                          className="p-3 rounded-xl bg-ink/50 border border-white/5 text-xs space-y-2"
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-mono font-semibold text-text">
                              Signal {sig.code}
                            </span>
                            <div className="flex items-center gap-2">
                              {getSignalStateBadge(sig.observed_state)}
                              <Badge variant={getStatusBadgeVariant(sig.status)} className="text-[10px]">
                                {sig.status}
                              </Badge>
                            </div>
                          </div>

                          {/* Phases Sequence list */}
                          {sig.phases && sig.phases.length > 0 ? (
                            <div className="space-y-1.5 pt-1">
                              <span className="text-[10px] text-muted block font-mono">
                                Phase Intervals:
                              </span>
                              <div className="grid grid-cols-2 gap-1.5 font-mono text-[11px]">
                                {sig.phases.map((phase) => (
                                  <div
                                    key={phase.id}
                                    className={`p-1.5 rounded-lg border flex items-center justify-between ${
                                      phase.is_active
                                        ? "bg-accent/15 border-accent text-accent font-semibold"
                                        : "bg-surface/50 border-white/5 text-muted"
                                    }`}
                                  >
                                    <span className="truncate">
                                      #{phase.phase_order} {phase.name}
                                    </span>
                                    <span>{phase.duration_seconds}s</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          ) : (
                            <div className="text-[11px] text-muted/70 italic">
                              No discrete phase timing registered
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="p-3 rounded-xl bg-ink/30 border border-white/5 text-center text-xs text-muted font-mono">
                      No signal controllers connected to this junction
                    </div>
                  )}
                </div>

                {/* Recent Vehicle Detection Events */}
                <div className="mt-5 pt-4 border-t border-white/10 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 text-xs font-display font-semibold text-text">
                      <Car className="w-3.5 h-3.5 text-accent" />
                      <span>Recent Vision Detections</span>
                    </div>
                    <span className="text-[10px] font-mono text-muted">Edge Perception</span>
                  </div>

                  {eventsLoading ? (
                    <div className="py-4 flex justify-center">
                      <LoadingSpinner size="sm" label="Fetching detection stream..." />
                    </div>
                  ) : eventsData?.items && eventsData.items.length > 0 ? (
                    <div className="space-y-1.5 max-h-44 overflow-y-auto pr-1 font-mono text-[11px]">
                      {eventsData.items.slice(0, 5).map((ev) => (
                        <div
                          key={ev.id}
                          className="p-2 rounded-lg bg-ink/40 border border-white/5 flex items-center justify-between"
                        >
                          <div className="flex items-center gap-2">
                            <span className="text-text font-semibold capitalize">
                              {ev.vehicle_type}
                            </span>
                            {ev.speed_kmh != null && (
                              <span className="text-accent">
                                {formatSpeed(ev.speed_kmh)}
                              </span>
                            )}
                          </div>
                          <span className="text-muted text-[10px]">
                            {formatRelativeTime(ev.detected_at)}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="p-3 rounded-xl bg-ink/30 border border-white/5 text-center text-xs text-muted font-mono">
                      No recent vehicle detections at this node
                    </div>
                  )}
                </div>

                {/* Action Links */}
                <div className="mt-5 pt-4 border-t border-white/10 flex items-center gap-2">
                  <Button
                    href="/traffic"
                    variant="secondary"
                    size="sm"
                    className="w-full text-xs"
                  >
                    <SlidersHorizontal className="w-3.5 h-3.5 mr-1.5" />
                    Traffic Telemetry
                  </Button>
                  <Button
                    href="/control"
                    variant="primary"
                    size="sm"
                    className="w-full text-xs"
                  >
                    Actuate Signals →
                  </Button>
                </div>
              </Card>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
