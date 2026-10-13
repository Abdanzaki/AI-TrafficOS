"use client";

import React, { useState, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  Camera,
  CheckCircle2,
  Clock,
  Eye,
  Filter,
  Image as ImageIcon,
  MapPin,
  RefreshCw,
  RotateCcw,
  Shield,
  ShieldAlert,
  X,
} from "lucide-react";
import { useApiQuery, useApiMutation } from "@/lib/use-api";
import { Card } from "@/components/ui/Card";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Pagination } from "@/components/ui/Pagination";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";

export interface ViolationItem {
  id: number;
  violation_type: "red_light" | "wrong_way" | "no_helmet" | string;
  detected_at: string;
  intersection_id?: number | null;
  camera_id?: string | null;
  confidence: number;
  status: "recorded" | "reviewed" | "dismissed" | "escalated" | string;
  evidence_ref?: string | null;
  details?: Record<string, any> | null;
  created_at: string;
  updated_at: string;
}

interface PaginatedViolations {
  items: ViolationItem[];
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

function getViolationTypeBadge(type: string): {
  variant: BadgeVariant;
  label: string;
  icon: React.ElementType;
} {
  switch (type.toLowerCase()) {
    case "red_light":
      return { variant: "danger", label: "Red Light Runner", icon: AlertTriangle };
    case "wrong_way":
      return { variant: "danger", label: "Wrong-Way Driving", icon: ShieldAlert };
    case "no_helmet":
      return { variant: "amber", label: "No Helmet Rider", icon: Shield };
    default:
      return { variant: "muted", label: type, icon: AlertCircle };
  }
}

function getStatusBadge(status: string): {
  variant: BadgeVariant;
  label: string;
} {
  switch (status.toLowerCase()) {
    case "recorded":
      return { variant: "amber", label: "Recorded" };
    case "reviewed":
      return { variant: "teal", label: "Reviewed" };
    case "escalated":
      return { variant: "danger", label: "Escalated" };
    case "dismissed":
      return { variant: "muted", label: "Dismissed" };
    default:
      return { variant: "muted", label: status };
  }
}

export function ViolationsList() {
  const queryClient = useQueryClient();
  const { canWrite } = useAuth();

  // Filters & Pagination
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [junctionFilter, setJunctionFilter] = useState<string>("all");
  const [page, setPage] = useState<number>(1);
  const perPage = 15;

  // Selected for detail drawer / modal
  const [selectedViolation, setSelectedViolation] = useState<ViolationItem | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // 1. Fetch Junctions for dropdown filter
  const { data: junctionsData } = useApiQuery<PaginatedJunctions>({
    queryKey: ["junctions-list-violations"],
    endpoint: "/junctions",
    params: { per_page: 100 },
    queryOptions: { staleTime: 60000 },
  });

  const junctionMap = useMemo(() => {
    const map = new Map<number, JunctionOption>();
    junctionsData?.items?.forEach((j) => map.set(j.id, j));
    return map;
  }, [junctionsData]);

  // 2. Fetch Violations list
  const queryParams = useMemo(() => {
    const params: Record<string, any> = {
      page,
      per_page: perPage,
    };
    if (typeFilter !== "all") params.violation_type = typeFilter;
    if (statusFilter !== "all") params.status = statusFilter;
    if (junctionFilter !== "all") params.intersection_id = Number(junctionFilter);
    return params;
  }, [typeFilter, statusFilter, junctionFilter, page, perPage]);

  const {
    data: violationsData,
    isLoading,
    isFetching,
    isError,
    error,
    refetch,
  } = useApiQuery<PaginatedViolations>({
    queryKey: ["violations-list", queryParams],
    endpoint: "/violations",
    params: queryParams,
    queryOptions: {
      refetchInterval: 15000,
    },
  });

  // 3. Status Update Mutation
  const updateStatusMutation = useApiMutation<
    ViolationItem,
    { id: number; data: { status: string } }
  >({
    endpoint: (vars) => `/violations/${vars.id}`,
    method: "PATCH",
    mutationOptions: {
      onSuccess: (_, vars) => {
        setActionSuccess(`Violation #${vars.id} status updated to ${vars.data.status}.`);
        queryClient.invalidateQueries({ queryKey: ["violations-list"] });
        if (selectedViolation?.id === vars.id) {
          setSelectedViolation((prev) =>
            prev ? { ...prev, status: vars.data.status } : null
          );
        }
      },
      onError: (err) => {
        setActionError(err.message || "Failed to update violation status.");
      },
    },
  });

  const handleResetFilters = () => {
    setTypeFilter("all");
    setStatusFilter("all");
    setJunctionFilter("all");
    setPage(1);
  };

  const hasActiveFilters =
    typeFilter !== "all" || statusFilter !== "all" || junctionFilter !== "all";

  const items = violationsData?.items || [];
  const totalItems = violationsData?.total || 0;
  const totalPages = violationsData?.pages || 1;

  return (
    <div className="space-y-6" data-testid="violations-panel">
      {/* Top Banner / Disclaimer */}
      <div className="p-3.5 rounded-xl bg-ink-raised border border-white/10 text-xs text-muted flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
        <div className="flex items-center gap-2">
          <Camera className="w-4 h-4 text-accent shrink-0" />
          <span>
            <strong>CV Violation Engine:</strong> Deterministic red light, wrong-way, and
            motorcycle helmet verification. City live feeds require statutory authority.
          </span>
        </div>
        <Badge variant="muted" className="self-start sm:self-auto font-mono text-[10px]">
          Batch 2 Perception
        </Badge>
      </div>

      {/* Global Alerts */}
      {actionSuccess && (
        <div className="p-3.5 rounded-xl bg-success/10 border border-success/30 text-success text-xs sm:text-sm flex items-center justify-between">
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
        <div className="p-3.5 rounded-xl bg-danger/10 border border-danger/30 text-danger text-xs sm:text-sm flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
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

      {/* Filters Toolbar */}
      <Card className="p-4 sm:p-5">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted">
            <Filter className="w-3.5 h-3.5" />
            <span>Filter Violations</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 flex-1 lg:max-w-3xl">
            {/* Violation Type */}
            <div>
              <label className="block text-[11px] font-medium text-muted uppercase tracking-wider mb-1">
                Violation Type
              </label>
              <select
                value={typeFilter}
                onChange={(e) => {
                  setTypeFilter(e.target.value);
                  setPage(1);
                }}
                className="w-full bg-ink border border-white/10 rounded-lg px-3 py-1.5 text-xs text-text focus:outline-none focus:border-accent"
                data-testid="filter-violation-type"
              >
                <option value="all">All Types</option>
                <option value="red_light">Red Light Runner</option>
                <option value="wrong_way">Wrong-Way Driving</option>
                <option value="no_helmet">No Helmet Rider</option>
              </select>
            </div>

            {/* Junction */}
            <div>
              <label className="block text-[11px] font-medium text-muted uppercase tracking-wider mb-1">
                Junction
              </label>
              <select
                value={junctionFilter}
                onChange={(e) => {
                  setJunctionFilter(e.target.value);
                  setPage(1);
                }}
                className="w-full bg-ink border border-white/10 rounded-lg px-3 py-1.5 text-xs text-text focus:outline-none focus:border-accent"
                data-testid="filter-junction"
              >
                <option value="all">All Junctions</option>
                {junctionsData?.items?.map((j) => (
                  <option key={j.id} value={j.id}>
                    {j.name} ({j.code})
                  </option>
                ))}
              </select>
            </div>

            {/* Status */}
            <div>
              <label className="block text-[11px] font-medium text-muted uppercase tracking-wider mb-1">
                Status
              </label>
              <select
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value);
                  setPage(1);
                }}
                className="w-full bg-ink border border-white/10 rounded-lg px-3 py-1.5 text-xs text-text focus:outline-none focus:border-accent"
                data-testid="filter-status"
              >
                <option value="all">All Statuses</option>
                <option value="recorded">Recorded</option>
                <option value="reviewed">Reviewed</option>
                <option value="escalated">Escalated</option>
                <option value="dismissed">Dismissed</option>
              </select>
            </div>
          </div>

          <div className="flex items-center gap-2 self-end lg:self-center">
            {hasActiveFilters && (
              <Button
                variant="ghost"
                size="sm"
                onClick={handleResetFilters}
                className="text-xs text-muted hover:text-text gap-1"
              >
                <RotateCcw className="w-3 h-3" />
                <span>Reset</span>
              </Button>
            )}
            <Button
              variant="secondary"
              size="sm"
              onClick={() => refetch()}
              disabled={isLoading || isFetching}
              className="gap-1.5"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? "animate-spin" : ""}`} />
              <span>Refresh</span>
            </Button>
          </div>
        </div>
      </Card>

      {/* Main Table / State */}
      {isLoading ? (
        <Card className="p-12 flex flex-col items-center justify-center">
          <LoadingSpinner size="lg" label="Loading traffic violations..." />
        </Card>
      ) : isError ? (
        <ErrorState
          title="Failed to Load Violations"
          message={error?.message || "An error occurred while fetching violations."}
          onRetry={() => refetch()}
        />
      ) : items.length === 0 ? (
        <Card className="p-12">
          <EmptyState
            title="No Traffic Violations Found"
            description={
              hasActiveFilters
                ? "No violations match the selected filters. Try broadening your criteria."
                : "No violations recorded by the computer vision perception pipeline yet."
            }
            action={
              hasActiveFilters
                ? {
                    label: "Clear Filters",
                    onClick: handleResetFilters,
                  }
                : undefined
            }
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-white/10 bg-white/[0.02] text-muted uppercase text-[10px] tracking-wider font-semibold">
                  <th className="py-3 px-4">Violation ID</th>
                  <th className="py-3 px-4">Type</th>
                  <th className="py-3 px-4">Detected At</th>
                  <th className="py-3 px-4">Junction / Camera</th>
                  <th className="py-3 px-4">Confidence</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Evidence</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {items.map((v) => {
                  const typeBadge = getViolationTypeBadge(v.violation_type);
                  const statusBadge = getStatusBadge(v.status);
                  const TypeIcon = typeBadge.icon;
                  const junction = v.intersection_id ? junctionMap.get(v.intersection_id) : null;
                  const confPct = Math.round(v.confidence * 100);

                  return (
                    <tr
                      key={v.id}
                      className="hover:bg-white/[0.02] transition-colors"
                      data-testid={`violation-row-${v.id}`}
                    >
                      {/* ID */}
                      <td className="py-3 px-4 font-mono font-medium text-text">
                        #V-{v.id}
                      </td>

                      {/* Type */}
                      <td className="py-3 px-4">
                        <Badge variant={typeBadge.variant} className="gap-1.5 py-1">
                          <TypeIcon className="w-3 h-3 shrink-0" />
                          <span>{typeBadge.label}</span>
                        </Badge>
                      </td>

                      {/* Timestamp */}
                      <td className="py-3 px-4 text-text/90">
                        <div className="flex items-center gap-1.5 font-mono text-[11px]">
                          <Clock className="w-3 h-3 text-muted shrink-0" />
                          <span>{formatDateTime(v.detected_at)}</span>
                        </div>
                      </td>

                      {/* Junction / Camera */}
                      <td className="py-3 px-4">
                        {junction ? (
                          <div className="flex items-center gap-1.5 text-text font-medium">
                            <MapPin className="w-3.5 h-3.5 text-accent shrink-0" />
                            <span>{junction.name}</span>
                          </div>
                        ) : (
                          <span className="text-muted font-mono">
                            {v.camera_id || "Unspecified Camera"}
                          </span>
                        )}
                        {v.camera_id && junction && (
                          <div className="text-[10px] text-muted font-mono mt-0.5">
                            {v.camera_id}
                          </div>
                        )}
                      </td>

                      {/* Confidence */}
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <div className="w-12 bg-white/10 rounded-full h-1.5 overflow-hidden">
                            <div
                              className={`h-full rounded-full ${
                                confPct >= 80
                                  ? "bg-accent"
                                  : confPct >= 60
                                  ? "bg-amber-400"
                                  : "bg-muted"
                              }`}
                              style={{ width: `${confPct}%` }}
                            />
                          </div>
                          <span className="font-mono text-text text-[11px] font-semibold">
                            {confPct}%
                          </span>
                        </div>
                      </td>

                      {/* Status */}
                      <td className="py-3 px-4">
                        <Badge variant={statusBadge.variant} className="text-[10px] py-0.5">
                          {statusBadge.label}
                        </Badge>
                      </td>

                      {/* Evidence Ref */}
                      <td className="py-3 px-4">
                        {v.evidence_ref ? (
                          <span
                            className="inline-flex items-center gap-1 text-[11px] text-accent font-mono truncate max-w-[140px] hover:underline cursor-pointer"
                            onClick={() => setSelectedViolation(v)}
                            title={v.evidence_ref}
                          >
                            <ImageIcon className="w-3 h-3 shrink-0" />
                            <span>Snapshot</span>
                          </span>
                        ) : (
                          <span className="text-[10px] text-muted italic">No snapshot</span>
                        )}
                      </td>

                      {/* Actions */}
                      <td className="py-3 px-4 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setSelectedViolation(v)}
                            className="h-7 px-2 text-xs"
                            title="View Details"
                          >
                            <Eye className="w-3.5 h-3.5" />
                          </Button>

                          {canWrite() && v.status === "recorded" && (
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() =>
                                updateStatusMutation.mutate({
                                  id: v.id,
                                  data: { status: "reviewed" },
                                })
                              }
                              disabled={updateStatusMutation.isPending}
                              className="h-7 px-2 text-[11px]"
                            >
                              Review
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <Pagination
            page={page}
            totalPages={totalPages}
            totalRecords={totalItems}
            perPage={perPage}
            onPageChange={setPage}
            recordLabel="violations"
          />
        </Card>
      )}

      {/* Details Drawer / Modal */}
      {selectedViolation && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in">
          <Card className="w-full max-w-lg p-6 space-y-4 max-h-[90vh] overflow-y-auto border border-white/10 shadow-2xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <Badge
                    variant={getViolationTypeBadge(selectedViolation.violation_type).variant}
                  >
                    {getViolationTypeBadge(selectedViolation.violation_type).label}
                  </Badge>
                  <span className="font-mono text-sm text-text font-bold">
                    #V-{selectedViolation.id}
                  </span>
                </div>
                <p className="text-xs text-muted mt-1">
                  Detected {formatDateTime(selectedViolation.detected_at)}
                </p>
              </div>
              <button
                onClick={() => setSelectedViolation(null)}
                className="text-muted hover:text-text p-1"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Quick Metrics */}
            <div className="grid grid-cols-2 gap-3 p-3 rounded-lg bg-ink/40 border border-white/5 text-xs">
              <div>
                <span className="text-muted block text-[10px] uppercase tracking-wider">
                  Confidence
                </span>
                <span className="font-mono text-text font-semibold text-sm">
                  {Math.round(selectedViolation.confidence * 100)}%
                </span>
              </div>
              <div>
                <span className="text-muted block text-[10px] uppercase tracking-wider">
                  Status
                </span>
                <Badge
                  variant={getStatusBadge(selectedViolation.status).variant}
                  className="mt-0.5"
                >
                  {getStatusBadge(selectedViolation.status).label}
                </Badge>
              </div>
              <div>
                <span className="text-muted block text-[10px] uppercase tracking-wider">
                  Camera ID
                </span>
                <span className="font-mono text-text text-xs">
                  {selectedViolation.camera_id || "Unspecified"}
                </span>
              </div>
              <div>
                <span className="text-muted block text-[10px] uppercase tracking-wider">
                  Evidence Reference
                </span>
                <span className="font-mono text-text text-xs truncate block" title={selectedViolation.evidence_ref || "None"}>
                  {selectedViolation.evidence_ref || "None"}
                </span>
              </div>
            </div>

            {/* Diagnostic Details */}
            {selectedViolation.details && (
              <div className="space-y-1.5">
                <span className="text-xs font-semibold text-text uppercase tracking-wider">
                  CV Diagnostic Telemetry
                </span>
                <pre className="p-3 rounded-lg bg-ink border border-white/5 text-[11px] font-mono text-text/80 overflow-x-auto max-h-48">
                  {JSON.stringify(selectedViolation.details, null, 2)}
                </pre>
              </div>
            )}

            {/* Officer Actions */}
            {canWrite() && (
              <div className="flex items-center justify-end gap-2 pt-2 border-t border-white/10">
                {selectedViolation.status === "recorded" && (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() =>
                      updateStatusMutation.mutate({
                        id: selectedViolation.id,
                        data: { status: "reviewed" },
                      })
                    }
                  >
                    Mark as Reviewed
                  </Button>
                )}
                {selectedViolation.status !== "escalated" && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() =>
                      updateStatusMutation.mutate({
                        id: selectedViolation.id,
                        data: { status: "escalated" },
                      })
                    }
                  >
                    Escalate
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setSelectedViolation(null)}
                >
                  Close
                </Button>
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
