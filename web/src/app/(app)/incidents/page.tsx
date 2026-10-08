"use client";

import React, { useState, useMemo, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Filter,
  Plus,
  RefreshCw,
  RotateCcw,
  Trash2,
  X,
  ChevronLeft,
  ChevronRight,
  MapPin,
  ShieldAlert,
  Eye,
  Check,
  Calendar,
  AlertCircle,
  Radio,
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
  getSeverityBadgeVariant,
} from "@/lib/format";

// --- Types conforming strictly to backend schemas (backend/app/schemas/incident.py) ---

export interface IncidentItem {
  id: number;
  intersection_id?: number | null;
  severity: "low" | "medium" | "high" | "critical" | "unknown" | string;
  status: "reported" | "acknowledged" | "resolved" | string;
  description?: string | null;
  reported_by?: number | null;
  resolved_at?: string | null;
  lat?: number | null;
  lon?: number | null;
  created_at: string;
  updated_at: string;
}

interface PaginatedIncidents {
  items: IncidentItem[];
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

interface IncidentCreatePayload {
  intersection_id?: number | null;
  severity: string;
  status: string;
  description?: string | null;
  lat?: number | null;
  lon?: number | null;
}

interface IncidentUpdatePayload {
  status?: string | null;
  severity?: string | null;
  description?: string | null;
  intersection_id?: number | null;
  resolved_at?: string | null;
}

function getStatusPill(status: string): {
  variant: BadgeVariant;
  label: string;
} {
  switch (status.toLowerCase()) {
    case "reported":
      return { variant: "danger", label: "Reported" };
    case "acknowledged":
      return { variant: "amber", label: "Acknowledged" };
    case "resolved":
      return { variant: "success", label: "Resolved" };
    default:
      return { variant: "muted", label: status };
  }
}

export default function IncidentsPage() {
  const queryClient = useQueryClient();
  const { user, isAdmin, canWrite } = useAuth();

  // Filters & Pagination
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [severityFilter, setSeverityFilter] = useState<string>("all");
  const [junctionFilter, setJunctionFilter] = useState<string>("all");
  const [page, setPage] = useState<number>(1);
  const perPage = 15;

  // Modals & Drawer State
  const [selectedIncident, setSelectedIncident] = useState<IncidentItem | null>(null);
  const [isCreateOpen, setIsCreateOpen] = useState<boolean>(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // New incident form state
  const [newJunctionId, setNewJunctionId] = useState<string>("");
  const [newSeverity, setNewSeverity] = useState<string>("medium");
  const [newStatus, setNewStatus] = useState<string>("reported");
  const [newDescription, setNewDescription] = useState<string>("");
  const [newLat, setNewLat] = useState<string>("");
  const [newLon, setNewLon] = useState<string>("");
  const [formError, setFormError] = useState<string | null>(null);

  // 1. Fetch Junctions for dropdown
  const { data: junctionsData } = useApiQuery<PaginatedJunctions>({
    queryKey: ["junctions-list-incidents"],
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

  // 2. Query Incidents
  const queryParams = useMemo(() => {
    const params: Record<string, string | number> = {
      page,
      per_page: perPage,
    };
    if (statusFilter !== "all") {
      params.status = statusFilter;
    }
    if (severityFilter !== "all") {
      params.severity = severityFilter;
    }
    if (junctionFilter !== "all") {
      params.intersection_id = Number(junctionFilter);
    }
    return params;
  }, [page, perPage, statusFilter, severityFilter, junctionFilter]);

  // Real-time invalidations: incident.created and incident.updated update incidents list (replaces 15s poll)
  useTopic("incident.created", () => {
    queryClient.invalidateQueries({ queryKey: ["incidents-list"] });
  });

  useTopic("incident.updated", () => {
    queryClient.invalidateQueries({ queryKey: ["incidents-list"] });
  });

  const {
    data: incidentsData,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useApiQuery<PaginatedIncidents>({
    queryKey: [
      "incidents-list",
      page,
      perPage,
      statusFilter,
      severityFilter,
      junctionFilter,
    ],
    endpoint: "/incidents",
    params: queryParams,
  });

  // Mutations
  const updateIncidentMutation = useApiMutation<IncidentItem, { id: number; data: IncidentUpdatePayload }>({
    endpoint: ({ id }) => `/incidents/${id}`,
    method: "PATCH",
    mutationOptions: {
      onSuccess: (updated) => {
        setActionSuccess(`Incident #${updated.id} updated to status "${updated.status}"`);
        setActionError(null);
        queryClient.invalidateQueries({ queryKey: ["incidents-list"] });
        if (selectedIncident && selectedIncident.id === updated.id) {
          setSelectedIncident(updated);
        }
      },
      onError: (err) => {
        setActionError(err.message || "Failed to update incident status");
        setActionSuccess(null);
      },
    },
  });

  const deleteIncidentMutation = useApiMutation<void, { id: number }>({
    endpoint: ({ id }) => `/incidents/${id}`,
    method: "DELETE",
    mutationOptions: {
      onSuccess: (_, { id }) => {
        setActionSuccess(`Incident #${id} permanently deleted.`);
        setActionError(null);
        queryClient.invalidateQueries({ queryKey: ["incidents-list"] });
        if (selectedIncident && selectedIncident.id === id) {
          setSelectedIncident(null);
        }
      },
      onError: (err) => {
        setActionError(err.message || "Failed to delete incident");
        setActionSuccess(null);
      },
    },
  });

  const createIncidentMutation = useApiMutation<IncidentItem, IncidentCreatePayload>({
    endpoint: "/incidents",
    method: "POST",
    mutationOptions: {
      onSuccess: (created) => {
        setActionSuccess(`Incident #${created.id} reported successfully.`);
        setActionError(null);
        queryClient.invalidateQueries({ queryKey: ["incidents-list"] });
        setIsCreateOpen(false);
        // Reset form
        setNewJunctionId("");
        setNewSeverity("medium");
        setNewStatus("reported");
        setNewDescription("");
        setNewLat("");
        setNewLon("");
        setFormError(null);
      },
      onError: (err) => {
        setFormError(err.message || "Failed to create incident");
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
    setSeverityFilter("all");
    setJunctionFilter("all");
    setPage(1);
  };

  const hasActiveFilters =
    statusFilter !== "all" ||
    severityFilter !== "all" ||
    junctionFilter !== "all";

  // Close drawer on Escape
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (isCreateOpen) setIsCreateOpen(false);
        else if (selectedIncident) setSelectedIncident(null);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isCreateOpen, selectedIncident]);

  // Handle Create Form Submit
  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    const payload: IncidentCreatePayload = {
      severity: newSeverity,
      status: newStatus,
      description: newDescription.trim() || undefined,
    };

    if (newJunctionId) {
      payload.intersection_id = Number(newJunctionId);
    }

    if (newLat) {
      const latNum = parseFloat(newLat);
      if (isNaN(latNum) || latNum < -90 || latNum > 90) {
        setFormError("Latitude must be a valid number between -90 and 90.");
        return;
      }
      payload.lat = latNum;
    }

    if (newLon) {
      const lonNum = parseFloat(newLon);
      if (isNaN(lonNum) || lonNum < -180 || lonNum > 180) {
        setFormError("Longitude must be a valid number between -180 and 180.");
        return;
      }
      payload.lon = lonNum;
    }

    createIncidentMutation.mutate(payload);
  };

  // Status transition handler
  const handleStatusTransition = (incidentId: number, targetStatus: string) => {
    setActionError(null);
    setActionSuccess(null);
    updateIncidentMutation.mutate({
      id: incidentId,
      data: { status: targetStatus },
    });
  };

  // Delete handler
  const handleDelete = (incidentId: number) => {
    if (!window.confirm(`Are you sure you want to permanently delete incident #${incidentId}? This action is irreversible.`)) {
      return;
    }
    setActionError(null);
    setActionSuccess(null);
    deleteIncidentMutation.mutate({ id: incidentId });
  };

  // Offline check
  const isNetworkOffline = isError && !incidentsData && error?.status === 0;

  if (isNetworkOffline) {
    return (
      <div className="max-w-7xl mx-auto space-y-6">
        <ErrorState
          title="Incident Service Unreachable"
          message="Failed to connect to /api/v1/incidents. Please verify your network connection and backend service status."
          onRetry={() => refetch()}
          retryText="Retry Connection"
        />
      </div>
    );
  }

  const items = incidentsData?.items || [];
  const totalItems = incidentsData?.total || 0;
  const totalPages = incidentsData?.pages || 1;

  // Stat counters based on current list / items
  const reportedCount = items.filter((i) => i.status === "reported").length;
  const ackCount = items.filter((i) => i.status === "acknowledged").length;
  const resolvedCount = items.filter((i) => i.status === "resolved").length;

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5 mb-1.5 flex-wrap">
            <h1 className="text-2xl sm:text-3xl font-display font-bold text-text tracking-tight">
              Incident Management
            </h1>
            <Badge variant="amber" dot>
              Live Monitor
            </Badge>
            <span className="text-xs text-muted font-mono">
              VALID_INCIDENT_STATUSES: reported | acknowledged | resolved
            </span>
          </div>
          <p className="text-xs sm:text-sm text-muted max-w-2xl leading-relaxed">
            Real-time traffic anomaly reporting, collision detection, and lifecycle status transition registry.
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

          {canWrite() ? (
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                setFormError(null);
                setIsCreateOpen(true);
              }}
              className="gap-1.5"
            >
              <Plus className="w-4 h-4" />
              <span>Report Incident</span>
            </Button>
          ) : (
            <Badge variant="muted" className="text-xs py-1 px-3">
              Analyst (Read-Only)
            </Badge>
          )}
        </div>
      </div>

      {/* Global Alerts / Feedback */}
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

      {/* Overview Stat Counters */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4">
        <Card className="p-4 bg-surface/70 border-white/10">
          <div className="text-[11px] font-medium text-muted uppercase tracking-wider">
            Total Matching
          </div>
          <div className="mt-1 font-display text-2xl font-bold text-text">
            {totalItems}
          </div>
          <div className="text-[10px] text-muted mt-0.5">Across indexed records</div>
        </Card>

        <Card className="p-4 bg-surface/70 border-white/10">
          <div className="text-[11px] font-medium text-danger uppercase tracking-wider">
            Reported
          </div>
          <div className="mt-1 font-display text-2xl font-bold text-danger">
            {reportedCount}
          </div>
          <div className="text-[10px] text-muted mt-0.5">Current page pending</div>
        </Card>

        <Card className="p-4 bg-surface/70 border-white/10">
          <div className="text-[11px] font-medium text-amber uppercase tracking-wider">
            Acknowledged
          </div>
          <div className="mt-1 font-display text-2xl font-bold text-amber">
            {ackCount}
          </div>
          <div className="text-[10px] text-muted mt-0.5">Response dispatched</div>
        </Card>

        <Card className="p-4 bg-surface/70 border-white/10">
          <div className="text-[11px] font-medium text-success uppercase tracking-wider">
            Resolved
          </div>
          <div className="mt-1 font-display text-2xl font-bold text-success">
            {resolvedCount}
          </div>
          <div className="text-[10px] text-muted mt-0.5">Cleared & closed</div>
        </Card>
      </div>

      {/* Filter Controls Bar */}
      <div className="bg-surface/60 p-4 rounded-2xl border border-white/10 flex flex-col md:flex-row md:items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 text-xs font-medium text-muted uppercase tracking-wider">
          <Filter className="w-3.5 h-3.5 text-accent" />
          <span>Filters:</span>
        </div>

        <div className="flex items-center gap-2.5 flex-wrap flex-1 justify-start md:justify-end">
          {/* Status Filter */}
          <select
            value={statusFilter}
            onChange={(e) => handleFilterChange(setStatusFilter, e.target.value)}
            className="bg-ink/80 border border-white/15 rounded-xl px-3 py-1.5 text-xs font-medium text-text focus:outline-none focus:border-accent"
          >
            <option value="all">All Statuses</option>
            <option value="reported">Reported</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="resolved">Resolved</option>
          </select>

          {/* Severity Filter */}
          <select
            value={severityFilter}
            onChange={(e) => handleFilterChange(setSeverityFilter, e.target.value)}
            className="bg-ink/80 border border-white/15 rounded-xl px-3 py-1.5 text-xs font-medium text-text focus:outline-none focus:border-accent"
          >
            <option value="all">All Severities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
            <option value="unknown">Unknown</option>
          </select>

          {/* Junction Filter */}
          <select
            value={junctionFilter}
            onChange={(e) => handleFilterChange(setJunctionFilter, e.target.value)}
            className="bg-ink/80 border border-white/15 rounded-xl px-3 py-1.5 text-xs font-medium text-text focus:outline-none focus:border-accent max-w-xs truncate"
          >
            <option value="all">All Junctions</option>
            {junctionsData?.items?.map((j) => (
              <option key={j.id} value={j.id}>
                #{j.id} — {j.name} ({j.code})
              </option>
            ))}
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

      {/* Main Table / List */}
      {isLoading && items.length === 0 ? (
        <Card className="p-12 text-center flex flex-col items-center justify-center min-h-[350px]">
          <LoadingSpinner size="lg" label="Loading traffic incident records..." />
        </Card>
      ) : isError ? (
        <ErrorState
          title="Failed to Load Incidents"
          message={error?.message || "An unexpected error occurred while fetching incident records."}
          onRetry={() => refetch()}
        />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<AlertTriangle className="w-8 h-8 text-muted" />}
          title="No Incidents Found"
          description={
            hasActiveFilters
              ? "No incident records matched your filter criteria. Try resetting filters."
              : "No active or recorded traffic incidents at this time. Roadways are clear."
          }
          action={
            hasActiveFilters
              ? {
                  label: "Reset Filter Criteria",
                  onClick: handleResetFilters,
                }
              : canWrite()
              ? {
                  label: "Report New Incident",
                  onClick: () => setIsCreateOpen(true),
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
                  <th className="py-3 px-3.5">ID / Reported</th>
                  <th className="py-3 px-3.5">Junction / Location</th>
                  <th className="py-3 px-3.5">Severity</th>
                  <th className="py-3 px-3.5">Status</th>
                  <th className="py-3 px-3.5">Description</th>
                  <th className="py-3 px-3.5">Resolved</th>
                  <th className="py-3 px-3.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {items.map((incident) => {
                  const statusPill = getStatusPill(incident.status);
                  const severityVariant = getSeverityBadgeVariant(incident.severity);
                  const junction = incident.intersection_id
                    ? junctionMap.get(incident.intersection_id)
                    : null;

                  return (
                    <tr
                      key={incident.id}
                      onClick={() => setSelectedIncident(incident)}
                      className="hover:bg-white/5 transition-colors cursor-pointer group"
                    >
                      {/* ID / Timestamp */}
                      <td className="py-3 px-3.5 align-top">
                        <div className="font-mono font-medium text-text flex items-center gap-1">
                          #{incident.id}
                        </div>
                        <div className="text-[11px] text-muted flex items-center gap-1 mt-0.5">
                          <Clock className="w-3 h-3 text-muted/70 flex-shrink-0" />
                          <span>{formatRelativeTime(incident.created_at)}</span>
                        </div>
                        <div className="text-[10px] text-muted/70 font-mono mt-0.5">
                          {formatDateTime(incident.created_at)}
                        </div>
                      </td>

                      {/* Junction */}
                      <td className="py-3 px-3.5 align-top">
                        {junction ? (
                          <div>
                            <span className="font-medium text-text block">
                              {junction.name}
                            </span>
                            <span className="text-[10px] font-mono text-muted">
                              #{junction.id} • {junction.code}
                            </span>
                          </div>
                        ) : incident.intersection_id ? (
                          <span className="font-mono text-muted">
                            Junction #{incident.intersection_id}
                          </span>
                        ) : (
                          <span className="text-muted italic">Non-junction corridor</span>
                        )}

                        {(incident.lat !== null && incident.lat !== undefined && incident.lon !== null && incident.lon !== undefined) && (
                          <div className="text-[10px] font-mono text-accent/80 flex items-center gap-1 mt-0.5">
                            <MapPin className="w-2.5 h-2.5" />
                            <span>{incident.lat.toFixed(4)}, {incident.lon.toFixed(4)}</span>
                          </div>
                        )}
                      </td>

                      {/* Severity */}
                      <td className="py-3 px-3.5 align-top">
                        <Badge variant={severityVariant} className="text-[10px]">
                          {incident.severity}
                        </Badge>
                      </td>

                      {/* Status */}
                      <td className="py-3 px-3.5 align-top">
                        <Badge variant={statusPill.variant} dot className="text-[10px]">
                          {statusPill.label}
                        </Badge>
                      </td>

                      {/* Description */}
                      <td className="py-3 px-3.5 align-top max-w-xs">
                        <p className="text-text line-clamp-2 leading-relaxed">
                          {incident.description || (
                            <span className="text-muted italic">No description provided</span>
                          )}
                        </p>
                      </td>

                      {/* Resolved At */}
                      <td className="py-3 px-3.5 align-top">
                        {incident.resolved_at ? (
                          <div className="text-success font-mono text-[11px] flex items-center gap-1">
                            <Check className="w-3 h-3" />
                            <span>{formatRelativeTime(incident.resolved_at)}</span>
                          </div>
                        ) : (
                          <span className="text-muted font-mono text-[11px]">—</span>
                        )}
                      </td>

                      {/* Actions */}
                      <td
                        className="py-3 px-3.5 align-top text-right"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className="flex items-center justify-end gap-1.5 flex-wrap">
                          {/* Quick transition buttons for officer / admin */}
                          {canWrite() && incident.status === "reported" && (
                            <button
                              type="button"
                              onClick={() => handleStatusTransition(incident.id, "acknowledged")}
                              title="Acknowledge Incident"
                              disabled={updateIncidentMutation.isPending}
                              className="px-2 py-1 rounded bg-amber/15 hover:bg-amber/25 border border-amber/30 text-amber text-[10px] font-medium transition-colors"
                            >
                              Ack
                            </button>
                          )}

                          {canWrite() && (incident.status === "reported" || incident.status === "acknowledged") && (
                            <button
                              type="button"
                              onClick={() => handleStatusTransition(incident.id, "resolved")}
                              title="Resolve Incident"
                              disabled={updateIncidentMutation.isPending}
                              className="px-2 py-1 rounded bg-success/15 hover:bg-success/25 border border-success/30 text-success text-[10px] font-medium transition-colors"
                            >
                              Resolve
                            </button>
                          )}

                          <button
                            type="button"
                            onClick={() => setSelectedIncident(incident)}
                            className="p-1 rounded text-muted hover:text-accent transition-colors"
                            title="Inspect details"
                          >
                            <Eye className="w-4 h-4" />
                          </button>
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
              of <span className="font-mono text-text font-medium">{totalItems}</span> incidents
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

      {/* DETAIL DRAWER */}
      {selectedIncident && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 overflow-hidden flex justify-end"
        >
          {/* Backdrop */}
          <div
            onClick={() => setSelectedIncident(null)}
            className="fixed inset-0 bg-black/70 backdrop-blur-sm transition-opacity"
          />

          {/* Drawer Panel */}
          <div className="relative w-full max-w-xl bg-ink border-l border-white/10 shadow-2xl z-10 overflow-y-auto flex flex-col h-full animate-in slide-in-from-right duration-200">
            {/* Header */}
            <div className="p-5 border-b border-white/10 flex items-center justify-between bg-surface/80 sticky top-0 z-20 backdrop-blur-md">
              <div className="flex items-center gap-2.5 flex-wrap">
                <span className="font-mono font-bold text-text text-lg">
                  Incident #{selectedIncident.id}
                </span>
                <Badge variant={getSeverityBadgeVariant(selectedIncident.severity)}>
                  {selectedIncident.severity}
                </Badge>
                <Badge variant={getStatusPill(selectedIncident.status).variant} dot>
                  {getStatusPill(selectedIncident.status).label}
                </Badge>
              </div>

              <button
                type="button"
                onClick={() => setSelectedIncident(null)}
                className="w-8 h-8 rounded-lg bg-surface hover:bg-white/10 border border-white/10 flex items-center justify-center text-muted hover:text-text transition-colors cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Content */}
            <div className="p-6 space-y-6 flex-1 text-xs sm:text-sm">
              {/* Description */}
              <div className="space-y-2">
                <div className="text-xs uppercase tracking-wider font-semibold text-muted">
                  Incident Description
                </div>
                <Card className="p-4 bg-surface/60 border-white/10 text-text leading-relaxed">
                  {selectedIncident.description || "No descriptive notes recorded."}
                </Card>
              </div>

              {/* Lifecycle Timeline */}
              <div className="space-y-2">
                <div className="text-xs uppercase tracking-wider font-semibold text-muted">
                  Lifecycle Timeline
                </div>
                <Card className="p-4 bg-surface/60 border-white/10 divide-y divide-white/5 space-y-3 font-mono text-xs">
                  <div className="flex items-center justify-between pt-1">
                    <span className="text-muted flex items-center gap-1.5 font-sans">
                      <Clock className="w-3.5 h-3.5 text-accent" />
                      Reported At:
                    </span>
                    <span className="text-text">
                      {formatDateTime(selectedIncident.created_at)}
                    </span>
                  </div>

                  <div className="flex items-center justify-between pt-3">
                    <span className="text-muted flex items-center gap-1.5 font-sans">
                      <Calendar className="w-3.5 h-3.5 text-amber" />
                      Last Updated:
                    </span>
                    <span className="text-text">
                      {formatDateTime(selectedIncident.updated_at)}
                    </span>
                  </div>

                  <div className="flex items-center justify-between pt-3">
                    <span className="text-muted flex items-center gap-1.5 font-sans">
                      <CheckCircle2 className="w-3.5 h-3.5 text-success" />
                      Resolved At:
                    </span>
                    <span className={selectedIncident.resolved_at ? "text-success font-semibold" : "text-muted"}>
                      {selectedIncident.resolved_at
                        ? formatDateTime(selectedIncident.resolved_at)
                        : "Unresolved (Active)"}
                    </span>
                  </div>
                </Card>
              </div>

              {/* Location & Metadata */}
              <div className="space-y-2">
                <div className="text-xs uppercase tracking-wider font-semibold text-muted">
                  Location & Reporter Details
                </div>
                <Card className="p-4 bg-surface/60 border-white/10 grid grid-cols-2 gap-3 text-xs">
                  <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                    <div className="text-[10px] text-muted uppercase mb-0.5">Junction</div>
                    <div className="text-text font-medium">
                      {selectedIncident.intersection_id
                        ? junctionMap.get(selectedIncident.intersection_id)?.name ||
                          `Junction #${selectedIncident.intersection_id}`
                        : "Open Roadway"}
                    </div>
                  </div>

                  <div className="p-2.5 rounded-lg bg-ink/50 border border-white/5">
                    <div className="text-[10px] text-muted uppercase mb-0.5">Reporter User ID</div>
                    <div className="text-text font-mono">
                      {selectedIncident.reported_by ? `#${selectedIncident.reported_by}` : "System Anomaly Sensor"}
                    </div>
                  </div>

                  <div className="col-span-2 p-2.5 rounded-lg bg-ink/50 border border-white/5">
                    <div className="text-[10px] text-muted uppercase mb-0.5">Coordinates (Lat, Lon)</div>
                    <div className="text-accent font-mono">
                      {selectedIncident.lat !== null && selectedIncident.lat !== undefined && selectedIncident.lon !== null && selectedIncident.lon !== undefined
                        ? `${selectedIncident.lat.toFixed(6)}, ${selectedIncident.lon.toFixed(6)}`
                        : "No precise GPS coordinates provided"}
                    </div>
                  </div>
                </Card>
              </div>

              {/* Status Transition & Admin Actions */}
              <div className="space-y-3 pt-2">
                <div className="text-xs uppercase tracking-wider font-semibold text-muted">
                  Supervisory Actions
                </div>

                <RequireRole
                  allowedRoles={["admin", "traffic_officer"]}
                  fallback={
                    <div className="p-3.5 rounded-xl bg-white/5 border border-white/10 text-muted text-xs flex items-center gap-2">
                      <ShieldAlert className="w-4 h-4 text-amber shrink-0" />
                      <span>Read-only clearance. Status transitions and deletions require traffic officer or admin authorization.</span>
                    </div>
                  }
                >
                  <div className="p-4 rounded-xl bg-surface border border-white/10 space-y-3">
                    <div className="text-xs text-muted">
                      Transition incident status:
                    </div>

                    <div className="flex items-center gap-2 flex-wrap">
                      {selectedIncident.status === "reported" && (
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => handleStatusTransition(selectedIncident.id, "acknowledged")}
                          disabled={updateIncidentMutation.isPending}
                          className="border-amber/40 text-amber hover:bg-amber/10"
                        >
                          <Radio className="w-3.5 h-3.5 mr-1" />
                          Acknowledge
                        </Button>
                      )}

                      {selectedIncident.status !== "resolved" && (
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => handleStatusTransition(selectedIncident.id, "resolved")}
                          disabled={updateIncidentMutation.isPending}
                          className="border-success/40 text-success hover:bg-success/10"
                        >
                          <CheckCircle2 className="w-3.5 h-3.5 mr-1" />
                          Resolve Incident
                        </Button>
                      )}

                      {selectedIncident.status === "resolved" && (
                        <div className="text-xs text-success flex items-center gap-1.5 font-medium">
                          <Check className="w-4 h-4" />
                          <span>Incident is marked resolved (closed).</span>
                        </div>
                      )}
                    </div>

                    {/* Admin Delete */}
                    {isAdmin() && (
                      <div className="border-t border-white/10 pt-3 mt-3 flex items-center justify-between">
                        <span className="text-xs text-muted">Admin Privileges:</span>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => handleDelete(selectedIncident.id)}
                          disabled={deleteIncidentMutation.isPending}
                          className="border-danger/40 text-danger hover:bg-danger/10 text-xs"
                        >
                          <Trash2 className="w-3.5 h-3.5 mr-1" />
                          Delete Incident
                        </Button>
                      </div>
                    )}
                  </div>
                </RequireRole>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* CREATE INCIDENT MODAL */}
      {isCreateOpen && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4"
        >
          {/* Backdrop */}
          <div
            onClick={() => setIsCreateOpen(false)}
            className="fixed inset-0 bg-black/75 backdrop-blur-sm transition-opacity"
          />

          {/* Dialog Body */}
          <div className="relative w-full max-w-lg bg-surface border border-white/15 rounded-2xl shadow-2xl p-6 z-10 space-y-5 animate-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between border-b border-white/10 pb-4">
              <div>
                <h2 className="text-lg font-display font-bold text-text">
                  Report Traffic Incident
                </h2>
                <p className="text-xs text-muted mt-0.5">
                  Logged under officer identity: <span className="font-mono text-text">{user?.email}</span>
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsCreateOpen(false)}
                className="w-8 h-8 rounded-lg bg-ink hover:bg-white/10 border border-white/10 flex items-center justify-center text-muted hover:text-text cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {formError && (
              <div className="p-3 rounded-lg bg-danger/15 border border-danger/30 text-danger text-xs flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{formError}</span>
              </div>
            )}

            <form onSubmit={handleCreateSubmit} className="space-y-4 text-xs">
              {/* Junction Dropdown */}
              <div>
                <label className="block text-muted font-medium mb-1">
                  Target Intersection (Optional)
                </label>
                <select
                  value={newJunctionId}
                  onChange={(e) => setNewJunctionId(e.target.value)}
                  className="w-full bg-ink border border-white/15 rounded-xl px-3 py-2 text-text text-xs focus:outline-none focus:border-accent"
                >
                  <option value="">None / Open Highway Segment</option>
                  {junctionsData?.items?.map((j) => (
                    <option key={j.id} value={j.id}>
                      #{j.id} — {j.name} ({j.code})
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                {/* Severity */}
                <div>
                  <label className="block text-muted font-medium mb-1">
                    Severity Level *
                  </label>
                  <select
                    value={newSeverity}
                    onChange={(e) => setNewSeverity(e.target.value)}
                    className="w-full bg-ink border border-white/15 rounded-xl px-3 py-2 text-text text-xs focus:outline-none focus:border-accent"
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                    <option value="critical">Critical</option>
                    <option value="unknown">Unknown</option>
                  </select>
                </div>

                {/* Status */}
                <div>
                  <label className="block text-muted font-medium mb-1">
                    Initial Status *
                  </label>
                  <select
                    value={newStatus}
                    onChange={(e) => setNewStatus(e.target.value)}
                    className="w-full bg-ink border border-white/15 rounded-xl px-3 py-2 text-text text-xs focus:outline-none focus:border-accent"
                  >
                    <option value="reported">Reported</option>
                    <option value="acknowledged">Acknowledged</option>
                    <option value="resolved">Resolved</option>
                  </select>
                </div>
              </div>

              {/* Description */}
              <div>
                <label className="block text-muted font-medium mb-1">
                  Incident Description
                </label>
                <textarea
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  rows={3}
                  maxLength={500}
                  placeholder="Collision blocking north approach, debris scattered..."
                  className="w-full bg-ink border border-white/15 rounded-xl p-3 text-text text-xs focus:outline-none focus:border-accent placeholder:text-muted/60"
                />
              </div>

              {/* Coordinates */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-muted font-medium mb-1">
                    Latitude (-90 to 90)
                  </label>
                  <input
                    type="number"
                    step="any"
                    value={newLat}
                    onChange={(e) => setNewLat(e.target.value)}
                    placeholder="e.g. 40.7128"
                    className="w-full bg-ink border border-white/15 rounded-xl px-3 py-2 text-text text-xs focus:outline-none focus:border-accent font-mono placeholder:text-muted/60"
                  />
                </div>

                <div>
                  <label className="block text-muted font-medium mb-1">
                    Longitude (-180 to 180)
                  </label>
                  <input
                    type="number"
                    step="any"
                    value={newLon}
                    onChange={(e) => setNewLon(e.target.value)}
                    placeholder="e.g. -74.0060"
                    className="w-full bg-ink border border-white/15 rounded-xl px-3 py-2 text-text text-xs focus:outline-none focus:border-accent font-mono placeholder:text-muted/60"
                  />
                </div>
              </div>

              <div className="pt-3 border-t border-white/10 flex items-center justify-end gap-2.5">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setIsCreateOpen(false)}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  disabled={createIncidentMutation.isPending}
                >
                  {createIncidentMutation.isPending ? "Submitting..." : "Submit Incident"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
