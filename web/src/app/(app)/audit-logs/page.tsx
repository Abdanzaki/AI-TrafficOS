"use client";

import React, { useState, useMemo } from "react";
import {
  FileText,
  Shield,
  User,
  Clock,
  Terminal,
  Filter,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { RequireRole } from "@/components/RequireRole";
import { useApiQuery } from "@/lib/use-api";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Pagination } from "@/components/ui/Pagination";
import { formatDateTime } from "@/lib/format";

interface AuditLogEntry {
  id: number;
  actor_user_id: number | null;
  action: string;
  entity_type: string | null;
  entity_id: number | null;
  details: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
  updated_at?: string;
}

interface PaginatedAuditLogs {
  items: AuditLogEntry[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

function AuditLogsContent() {
  const [page, setPage] = useState(1);
  const [actionFilter, setActionFilter] = useState("");
  const [entityTypeFilter, setEntityTypeFilter] = useState("");
  const [actorFilter, setActorFilter] = useState<string>("");
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const queryParams = useMemo(() => {
    const params: Record<string, string | number> = {
      page,
      per_page: 20,
    };
    if (actionFilter.trim()) {
      params.action = actionFilter.trim();
    }
    if (entityTypeFilter.trim()) {
      params.entity_type = entityTypeFilter.trim();
    }
    if (actorFilter.trim() && !isNaN(Number(actorFilter.trim()))) {
      params.actor_user_id = Number(actorFilter.trim());
    }
    return params;
  }, [page, actionFilter, entityTypeFilter, actorFilter]);

  const { data, isLoading, error, refetch, isFetching } = useApiQuery<PaginatedAuditLogs>({
    queryKey: ["audit-logs", queryParams],
    endpoint: "/audit-logs",
    params: queryParams,
  });

  const handleClearFilters = () => {
    setActionFilter("");
    setEntityTypeFilter("");
    setActorFilter("");
    setPage(1);
  };

  const hasActiveFilters = Boolean(actionFilter || entityTypeFilter || actorFilter);

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-6 rounded-2xl bg-surface/70 border border-white/10 backdrop-blur-sm">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h1 className="text-2xl font-display font-bold text-text">
              Immutable Audit Ledger
            </h1>
            <Badge variant="teal">Admin Clearance</Badge>
          </div>
          <p className="text-xs sm:text-sm text-muted">
            Cryptographically sealed verification log of authentication events, user updates, and supervisory actuations.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="text-xs text-muted font-mono bg-ink/60 px-3 py-1.5 rounded-lg border border-white/10">
            Recorded Events: {data?.total ?? "..."}
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div className="p-4 rounded-xl bg-surface/50 border border-white/10 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs font-semibold text-text uppercase tracking-wider">
            <Filter className="w-3.5 h-3.5 text-accent" />
            <span>Audit Query Filters</span>
          </div>

          {hasActiveFilters && (
            <button
              type="button"
              onClick={handleClearFilters}
              className="text-xs text-accent hover:underline flex items-center gap-1 cursor-pointer"
            >
              <X className="w-3 h-3" />
              Reset filters
            </button>
          )}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div>
            <label className="block text-[11px] font-mono text-muted mb-1">
              Action Name
            </label>
            <input
              type="text"
              placeholder="e.g. auth.login, user.created"
              value={actionFilter}
              onChange={(e) => {
                setActionFilter(e.target.value);
                setPage(1);
              }}
              className="w-full px-3 py-1.5 bg-ink/70 border border-white/10 rounded-xl text-xs text-text placeholder:text-muted/50 focus:outline-none focus:border-accent"
            />
          </div>

          <div>
            <label className="block text-[11px] font-mono text-muted mb-1">
              Entity Type
            </label>
            <input
              type="text"
              placeholder="e.g. user, signal, incident"
              value={entityTypeFilter}
              onChange={(e) => {
                setEntityTypeFilter(e.target.value);
                setPage(1);
              }}
              className="w-full px-3 py-1.5 bg-ink/70 border border-white/10 rounded-xl text-xs text-text placeholder:text-muted/50 focus:outline-none focus:border-accent"
            />
          </div>

          <div>
            <label className="block text-[11px] font-mono text-muted mb-1">
              Actor User ID
            </label>
            <input
              type="number"
              placeholder="e.g. 1"
              value={actorFilter}
              onChange={(e) => {
                setActorFilter(e.target.value);
                setPage(1);
              }}
              className="w-full px-3 py-1.5 bg-ink/70 border border-white/10 rounded-xl text-xs text-text placeholder:text-muted/50 focus:outline-none focus:border-accent"
            />
          </div>
        </div>
      </div>

      {/* Main Table / State Render */}
      {isLoading ? (
        <div className="min-h-[40vh] flex items-center justify-center">
          <LoadingSpinner size="lg" label="Querying audit records..." />
        </div>
      ) : error ? (
        <ErrorState
          title="Failed to Load Audit Logs"
          message={error.message}
          onRetry={() => refetch()}
        />
      ) : !data || data.items.length === 0 ? (
        <EmptyState
          icon={<FileText className="w-8 h-8 text-accent" />}
          title="No audit events found"
          description={
            hasActiveFilters
              ? "No recorded audit log entries match the specified filters."
              : "There are currently no recorded audit log entries."
          }
          action={
            hasActiveFilters
              ? {
                  label: "Clear Filters",
                  onClick: handleClearFilters,
                }
              : undefined
          }
        />
      ) : (
        <Card className="overflow-hidden border-white/10">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[700px] text-left border-collapse text-xs sm:text-sm">
              <thead>
                <tr className="border-b border-white/10 bg-surface/60 text-muted uppercase text-[11px] font-semibold tracking-wider font-mono">
                  <th className="py-3 px-4 w-8"></th>
                  <th className="py-3 px-4">Action</th>
                  <th className="py-3 px-4">Entity</th>
                  <th className="py-3 px-4">Actor</th>
                  <th className="py-3 px-4">Client IP</th>
                  <th className="py-3 px-4">Timestamp</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5 font-mono text-xs">
                {data.items.map((log) => {
                  const isExpanded = expandedId === log.id;
                  return (
                    <React.Fragment key={log.id}>
                      <tr
                        onClick={() => setExpandedId(isExpanded ? null : log.id)}
                        className="hover:bg-white/[0.02] transition-colors cursor-pointer"
                      >
                        <td className="py-3 px-4 text-muted">
                          {log.details ? (
                            isExpanded ? (
                              <ChevronDown className="w-3.5 h-3.5 text-accent" />
                            ) : (
                              <ChevronRight className="w-3.5 h-3.5 text-muted" />
                            )
                          ) : null}
                        </td>
                        <td className="py-3 px-4">
                          <span className="font-semibold text-accent font-mono">
                            {log.action}
                          </span>
                        </td>
                        <td className="py-3 px-4 text-text">
                          {log.entity_type ? (
                            <span>
                              {log.entity_type} {log.entity_id ? `(#${log.entity_id})` : ""}
                            </span>
                          ) : (
                            <span className="text-muted">—</span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-muted font-sans">
                          {log.actor_user_id ? `User #${log.actor_user_id}` : "System / Daemon"}
                        </td>
                        <td className="py-3 px-4 text-muted/80">
                          {log.ip_address || "—"}
                        </td>
                        <td className="py-3 px-4 text-muted font-mono">
                          {formatDateTime(log.created_at)}
                        </td>
                      </tr>

                      {/* Expanded Details JSON Block */}
                      {isExpanded && (
                        <tr className="bg-ink/60">
                          <td colSpan={6} className="p-4 border-t border-b border-white/5">
                            <div className="space-y-1.5">
                              <div className="flex items-center gap-2 text-[11px] text-muted font-mono uppercase">
                                <Terminal className="w-3.5 h-3.5 text-accent" />
                                <span>Payload Details (#event {log.id})</span>
                              </div>
                              <pre className="p-3 rounded-xl bg-ink/90 border border-white/10 text-[11px] font-mono text-accent/90 overflow-x-auto max-h-48">
                                {JSON.stringify(log.details || {}, null, 2)}
                              </pre>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>

          {data.pages > 1 && (
            <Pagination
              page={page}
              totalPages={data.pages}
              totalRecords={data.total}
              perPage={20}
              onPageChange={setPage}
              recordLabel="audit entries"
            />
          )}
        </Card>
      )}
    </div>
  );
}

export default function AuditLogsPage() {
  return (
    <RequireRole allowedRoles={["admin"]}>
      <AuditLogsContent />
    </RequireRole>
  );
}
