"use client";

import React, { useState } from "react";
import {
  AlertCircle,
  BarChart3,
  Calendar,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Compass,
  HelpCircle,
  Info,
  MapPin,
  Sparkles,
  Users,
} from "lucide-react";
import { useApiMutation, useApiQuery } from "@/lib/use-api";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ErrorState } from "@/components/ui/ErrorState";
import { formatDateTime, formatNumber } from "@/lib/format";

export interface AssumptionItem {
  parameter: string;
  description: string;
  range_or_value: string;
  low: number | null;
  base: number | null;
  high: number | null;
  formula: string | null;
}

export interface ScenarioUplift {
  uplift_vehicles: number;
  projected_total_flow: number | null;
  uplift_percentage: number | null;
}

export interface JunctionUpliftResult {
  junction_id: number;
  junction_name: string;
  junction_code: string | null;
  distance_km: number;
  spatial_weight: number;
  baseline_flow: number | null;
  baseline_status: "observed" | "no_baseline_data";
  baseline_note: string | null;
  scenarios: {
    low: ScenarioUplift;
    base: ScenarioUplift;
    high: ScenarioUplift;
  };
  confidence_interval: [number, number];
}

export interface EventDemandResponse {
  event_name: string;
  starts_at: string;
  expected_attendance: number;
  provenance: "parametric-heuristic";
  model_type: string;
  documentation: string;
  total_peak_vehicles: {
    low: number;
    base: number;
    high: number;
  };
  assumptions: AssumptionItem[];
  junctions: JunctionUpliftResult[];
}

interface JunctionOption {
  id: number;
  name: string;
  code: string;
}

interface JunctionsApiResponse {
  items: JunctionOption[];
  total: number;
}

export interface EventDemandForecastProps {
  className?: string;
  onForecastCompleted?: (data: EventDemandResponse) => void;
}

export const EventDemandForecast: React.FC<EventDemandForecastProps> = ({
  className = "",
  onForecastCompleted,
}) => {
  // Form State
  const [name, setName] = useState<string>("City Stadium Championship");
  const [junctionId, setJunctionId] = useState<string>("");
  const [startsAt, setStartsAt] = useState<string>(() => {
    // Default to tomorrow 18:00
    const d = new Date();
    d.setDate(d.getDate() + 1);
    d.setHours(18, 0, 0, 0);
    return d.toISOString().slice(0, 16);
  });
  const [attendance, setAttendance] = useState<number>(15000);
  const [kNearest, setKNearest] = useState<number>(3);
  const [showAssumptions, setShowAssumptions] = useState<boolean>(true);
  const [clientError, setClientError] = useState<string | null>(null);

  // Load physical junctions for selector
  const { data: junctionsData, isLoading: junctionsLoading } =
    useApiQuery<JunctionsApiResponse>({
      queryKey: ["intersections-select-list"],
      endpoint: "/intersections",
      params: { per_page: 50 },
    });

  // Forecasting Mutation
  const forecastMutation = useApiMutation<
    EventDemandResponse,
    {
      name: string;
      junction_id: number;
      starts_at: string;
      expected_attendance: number;
      k_nearest: number;
    }
  >({
    endpoint: "/events/forecast",
    method: "POST",
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setClientError(null);

    if (!name.trim()) {
      setClientError("Event name is required.");
      return;
    }

    const jId = parseInt(junctionId, 10);
    if (isNaN(jId) || jId <= 0) {
      setClientError("Please select a target physical junction.");
      return;
    }

    if (attendance <= 0) {
      setClientError("Expected attendance must be greater than zero.");
      return;
    }

    const startDate = new Date(startsAt);
    if (isNaN(startDate.getTime()) || startDate <= new Date()) {
      setClientError("Event start time must be in the future.");
      return;
    }

    forecastMutation.mutate(
      {
        name: name.trim(),
        junction_id: jId,
        starts_at: startDate.toISOString(),
        expected_attendance: attendance,
        k_nearest: kNearest,
      },
      {
        onSuccess: (data) => {
          if (onForecastCompleted) {
            onForecastCompleted(data);
          }
        },
      }
    );
  };

  const results = forecastMutation.data;

  return (
    <Card className={`p-6 sm:p-8 space-y-8 ${className}`}>
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/10">
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <Badge variant="teal" dot>
              Parametric Heuristic
            </Badge>
            <span className="text-white/20">•</span>
            <span className="text-xs text-muted font-mono">
              Event Uplift Gravity Model
            </span>
          </div>

          <h2 className="text-lg sm:text-xl font-display font-bold text-text tracking-tight">
            Event Traffic Demand Forecasting
          </h2>

          <p className="mt-1 text-xs text-muted max-w-2xl leading-relaxed">
            Project additional vehicular demand across nearby intersections for scheduled events.
            Uses transparent gravity distribution parameters labeled honestly as a heuristic, NOT ML.
          </p>
        </div>
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} noValidate className="space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Event Name */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted uppercase tracking-wider flex items-center gap-1">
              <span>Event Name</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. City Marathon"
              required
              className="w-full bg-ink/70 border border-white/10 rounded-xl px-3 py-2 text-xs sm:text-sm text-text placeholder-muted/60 focus:outline-none focus:border-accent"
            />
          </div>

          {/* Host Junction Select */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted uppercase tracking-wider flex items-center gap-1">
              <MapPin className="w-3.5 h-3.5 text-accent" />
              <span>Host Junction</span>
            </label>
            <select
              value={junctionId}
              onChange={(e) => setJunctionId(e.target.value)}
              disabled={junctionsLoading}
              required
              className="w-full bg-ink/70 border border-white/10 rounded-xl px-3 py-2 text-xs sm:text-sm text-text focus:outline-none focus:border-accent"
            >
              <option value="">
                {junctionsLoading ? "Loading junctions..." : "Select junction..."}
              </option>
              {junctionsData?.items?.map((j) => (
                <option key={j.id} value={j.id}>
                  #{j.id} — {j.name} ({j.code})
                </option>
              ))}
            </select>
          </div>

          {/* Start Datetime */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted uppercase tracking-wider flex items-center gap-1">
              <Calendar className="w-3.5 h-3.5 text-accent" />
              <span>Event Date & Time</span>
            </label>
            <input
              type="datetime-local"
              value={startsAt}
              onChange={(e) => setStartsAt(e.target.value)}
              required
              className="w-full bg-ink/70 border border-white/10 rounded-xl px-3 py-2 text-xs sm:text-sm text-text focus:outline-none focus:border-accent"
            />
          </div>

          {/* Expected Attendance */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted uppercase tracking-wider flex items-center gap-1">
              <Users className="w-3.5 h-3.5 text-accent" />
              <span>Expected Attendance</span>
            </label>
            <input
              type="number"
              min="1"
              step="100"
              value={attendance}
              onChange={(e) => setAttendance(Math.max(1, parseInt(e.target.value, 10) || 0))}
              required
              className="w-full bg-ink/70 border border-white/10 rounded-xl px-3 py-2 text-xs sm:text-sm text-text font-mono focus:outline-none focus:border-accent"
            />
          </div>
        </div>

        {/* Action Controls & k-nearest */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pt-2">
          <div className="flex items-center gap-3">
            <label className="text-xs text-muted font-medium flex items-center gap-1">
              <Compass className="w-3.5 h-3.5 text-muted" />
              <span>Distribute across nearest:</span>
            </label>
            <select
              value={kNearest}
              onChange={(e) => setKNearest(parseInt(e.target.value, 10))}
              className="bg-ink/70 border border-white/10 rounded-lg px-2.5 py-1 text-xs text-text font-mono focus:outline-none focus:border-accent"
            >
              <option value="2">2 Junctions</option>
              <option value="3">3 Junctions (Default)</option>
              <option value="4">4 Junctions</option>
              <option value="5">5 Junctions</option>
            </select>
          </div>

          <Button
            type="submit"
            variant="primary"
            size="sm"
            disabled={forecastMutation.isPending}
            className="cursor-pointer"
          >
            {forecastMutation.isPending ? (
              <>
                <LoadingSpinner size="sm" />
                <span className="ml-1.5">Calculating Demand...</span>
              </>
            ) : (
              <>
                <Sparkles className="w-3.5 h-3.5 mr-1.5" />
                <span>Forecast Demand Uplift</span>
              </>
            )}
          </Button>
        </div>

        {clientError && (
          <div className="p-3 rounded-xl bg-danger/10 border border-danger/30 text-xs text-danger flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{clientError}</span>
          </div>
        )}

        {forecastMutation.isError && (
          <div className="p-3 rounded-xl bg-danger/10 border border-danger/30 text-xs text-danger flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{forecastMutation.error?.message || "Failed to generate event forecast."}</span>
          </div>
        )}
      </form>

      {/* Results View */}
      {results && (
        <div className="space-y-6 pt-6 border-t border-white/10">
          {/* Results Summary Header */}
          <div className="p-5 rounded-2xl bg-ink/60 border border-white/10 flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 flex-wrap mb-1">
                <Badge variant="teal" dot>
                  {results.provenance}
                </Badge>
                <span className="text-white/20">•</span>
                <span className="text-xs text-muted font-mono flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  Starts: {formatDateTime(results.starts_at)}
                </span>
                <span className="text-white/20">•</span>
                <span className="text-xs text-muted font-mono">
                  Attendance: {formatNumber(results.expected_attendance)}
                </span>
              </div>

              <h3 className="text-base sm:text-lg font-display font-bold text-text">
                {results.event_name} — Demand Uplift Projection
              </h3>
            </div>

            {/* Total Peak Arrivals Metrics */}
            <div className="flex items-center gap-3 shrink-0">
              <div className="p-2.5 px-3 rounded-xl bg-surface/80 border border-white/10 text-center">
                <div className="text-[10px] text-muted uppercase font-medium">Low Peak</div>
                <div className="text-sm sm:text-base font-bold font-mono text-text">
                  +{formatNumber(results.total_peak_vehicles.low)} <span className="text-[10px] text-muted">veh</span>
                </div>
              </div>
              <div className="p-2.5 px-3 rounded-xl bg-accent/15 border border-accent/30 text-center">
                <div className="text-[10px] text-accent uppercase font-medium">Base Expected</div>
                <div className="text-sm sm:text-base font-bold font-mono text-accent">
                  +{formatNumber(results.total_peak_vehicles.base)} <span className="text-[10px] text-accent/80">veh</span>
                </div>
              </div>
              <div className="p-2.5 px-3 rounded-xl bg-amber/15 border border-amber/30 text-center">
                <div className="text-[10px] text-amber uppercase font-medium">High Surge</div>
                <div className="text-sm sm:text-base font-bold font-mono text-amber">
                  +{formatNumber(results.total_peak_vehicles.high)} <span className="text-[10px] text-amber/80">veh</span>
                </div>
              </div>
            </div>
          </div>

          {/* Per-Junction Results Cards */}
          <div className="space-y-4">
            <h4 className="text-sm font-display font-semibold text-text flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-accent" />
              <span>Per-Junction Impact Analysis ({results.junctions.length} junctions modeled)</span>
            </h4>

            <div className="grid grid-cols-1 gap-4">
              {results.junctions.map((j) => {
                const baseFlow = j.baseline_flow;
                const baseSc = j.scenarios.base;
                const lowSc = j.scenarios.low;
                const highSc = j.scenarios.high;

                return (
                  <div
                    key={j.junction_id}
                    className="p-5 rounded-2xl bg-surface/50 border border-white/10 space-y-4"
                  >
                    {/* Junction Title & Meta */}
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-white/5">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-display font-semibold text-text text-sm sm:text-base">
                          #{j.junction_id} — {j.junction_name}
                        </span>
                        {j.junction_code && (
                          <span className="text-xs text-muted font-mono">({j.junction_code})</span>
                        )}
                        <Badge variant="muted" className="text-[10px] py-0 px-2">
                          {j.distance_km === 0.0 ? "Host Venue" : `${j.distance_km} km away`}
                        </Badge>
                        <span className="text-xs text-muted font-mono">
                          Share: {(j.spatial_weight * 100).toFixed(1)}%
                        </span>
                      </div>

                      <div className="flex items-center gap-2">
                        {j.baseline_status === "observed" ? (
                          <Badge variant="teal" className="text-[10px]">
                            Observed Baseline: {baseFlow} veh/hr
                          </Badge>
                        ) : (
                          <Badge variant="amber" className="text-[10px]">
                            No Baseline Telemetry
                          </Badge>
                        )}
                      </div>
                    </div>

                    {/* Missing Baseline Warning if applicable */}
                    {j.baseline_status === "no_baseline_data" && (
                      <div className="p-3 rounded-xl bg-amber/10 border border-amber/20 text-xs text-amber flex items-center gap-2">
                        <AlertCircle className="w-4 h-4 shrink-0" />
                        <span>{j.baseline_note || "Baseline telemetry is missing for this junction; total volume cannot be measured."}</span>
                      </div>
                    )}

                    {/* Scenario Bars Grid */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                      {/* Low Scenario */}
                      <div className="p-3 rounded-xl bg-ink/40 border border-white/5 space-y-1.5">
                        <div className="text-[11px] text-muted uppercase font-medium flex items-center justify-between">
                          <span>Conservative (Low)</span>
                          <span className="font-mono text-text">
                            +{formatNumber(lowSc.uplift_vehicles)} veh
                          </span>
                        </div>
                        <div className="text-xs text-muted font-mono">
                          Projected Total:{" "}
                          <span className="text-text font-bold">
                            {lowSc.projected_total_flow !== null
                              ? `${formatNumber(lowSc.projected_total_flow, 1)} veh/hr`
                              : "—"}
                          </span>
                        </div>
                      </div>

                      {/* Base Scenario */}
                      <div className="p-3 rounded-xl bg-accent/10 border border-accent/20 space-y-1.5">
                        <div className="text-[11px] text-accent uppercase font-medium flex items-center justify-between">
                          <span>Expected (Base)</span>
                          <span className="font-mono text-accent font-bold">
                            +{formatNumber(baseSc.uplift_vehicles)} veh
                          </span>
                        </div>
                        <div className="text-xs text-muted font-mono flex items-center justify-between">
                          <span>
                            Total:{" "}
                            <span className="text-text font-bold">
                              {baseSc.projected_total_flow !== null
                                ? `${formatNumber(baseSc.projected_total_flow, 1)} veh/hr`
                                : "—"}
                            </span>
                          </span>
                          {baseSc.uplift_percentage !== null && (
                            <span className="text-accent font-bold">
                              +{baseSc.uplift_percentage.toFixed(1)}%
                            </span>
                          )}
                        </div>
                      </div>

                      {/* High Scenario */}
                      <div className="p-3 rounded-xl bg-amber/10 border border-amber/20 space-y-1.5">
                        <div className="text-[11px] text-amber uppercase font-medium flex items-center justify-between">
                          <span>Surge Peak (High)</span>
                          <span className="font-mono text-amber font-bold">
                            +{formatNumber(highSc.uplift_vehicles)} veh
                          </span>
                        </div>
                        <div className="text-xs text-muted font-mono">
                          Projected Total:{" "}
                          <span className="text-text font-bold">
                            {highSc.projected_total_flow !== null
                              ? `${formatNumber(highSc.projected_total_flow, 1)} veh/hr`
                              : "—"}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Confidence Interval footer */}
                    <div className="text-[11px] text-muted font-mono flex items-center justify-between pt-1">
                      <span>90% Scenario Uncertainty Interval:</span>
                      <span className="text-text font-semibold">
                        [{formatNumber(j.confidence_interval[0])} — {formatNumber(j.confidence_interval[1])} additional peak vehicles]
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Transparent Assumptions List */}
          <div className="pt-2">
            <button
              type="button"
              onClick={() => setShowAssumptions((prev) => !prev)}
              className="text-xs font-medium text-accent hover:text-accent/80 transition-colors flex items-center gap-1.5 cursor-pointer mb-3"
            >
              <span>{showAssumptions ? "Hide Model Assumptions" : "Inspect Parametric Model Assumptions"}</span>
              {showAssumptions ? (
                <ChevronUp className="w-3.5 h-3.5" />
              ) : (
                <ChevronDown className="w-3.5 h-3.5" />
              )}
            </button>

            {showAssumptions && (
              <div className="p-4 rounded-2xl bg-ink/70 border border-white/10 space-y-3">
                <div className="text-xs text-muted leading-relaxed">
                  {results.documentation}
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-white/10 text-muted uppercase text-[10px] font-mono">
                        <th className="pb-2">Parameter</th>
                        <th className="pb-2">Description</th>
                        <th className="pb-2">Scenario Range</th>
                        <th className="pb-2">Mathematical Formulation</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5 font-mono">
                      {results.assumptions.map((item) => (
                        <tr key={item.parameter} className="hover:bg-white/5">
                          <td className="py-2.5 font-bold text-accent pr-3">
                            {item.parameter}
                          </td>
                          <td className="py-2.5 text-text pr-3 font-sans">
                            {item.description}
                          </td>
                          <td className="py-2.5 text-amber pr-3">
                            {item.range_or_value}
                          </td>
                          <td className="py-2.5 text-muted text-[11px]">
                            {item.formula || "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </Card>
  );
};
