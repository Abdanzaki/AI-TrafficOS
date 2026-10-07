"use client";

import React, { useState, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  CheckCheck,
  Check,
  AlertOctagon,
  AlertTriangle,
  Info,
  Radio,
  Clock,
  Filter,
  RefreshCw,
  RotateCcw,
  X,
  ChevronLeft,
  ChevronRight,
  ShieldAlert,
  Send,
  SlidersHorizontal,
  Layers,
  MapPin,
  ExternalLink,
} from "lucide-react";
import { useApiQuery, useApiMutation } from "@/lib/use-api";
import { api } from "@/lib/api-client";
import { Card } from "@/components/ui/Card";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { useAuth } from "@/lib/auth";
import {
  formatDateTime,
  formatRelativeTime,
  getSeverityBadgeVariant,
} from "@/lib/format";

// --- Schema matching backend/app/schemas/notification.py ---

export interface NotificationItem {
  id: number;
  user_id?: number | null;
  title: string;
  message: string;
  severity: "info" | "warning" | "error" | "critical" | string;
  is_read: boolean;
  entity_type?: string | null;
  entity_id?: number | null;
  created_at: string;
  updated_at: string;
}

interface PaginatedNotifications {
  items: NotificationItem[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

interface BroadcastPayload {
  title: string;
  message: string;
  severity: string;
  entity_type?: string | null;
  entity_id?: number | null;
}

function getNotificationSeverityConfig(severity: string): {
  icon: React.ReactNode;
  badgeVariant: BadgeVariant;
  textColor: string;
  borderClass: string;
  bgClass: string;
} {
  switch (severity.toLowerCase()) {
    case "critical":
      return {
        icon: <AlertOctagon className="w-4 h-4 text-danger" />,
        badgeVariant: "danger",
        textColor: "text-danger",
        borderClass: "border-danger/40",
        bgClass: "bg-danger/10",
      };
    case "error":
      return {
        icon: <AlertOctagon className="w-4 h-4 text-danger" />,
        badgeVariant: "danger",
        textColor: "text-danger",
        borderClass: "border-danger/30",
        bgClass: "bg-danger/5",
      };
    case "warning":
      return {
        icon: <AlertTriangle className="w-4 h-4 text-amber" />,
        badgeVariant: "amber",
        textColor: "text-amber",
        borderClass: "border-amber/30",
        bgClass: "bg-amber/5",
      };
    case "info":
    default:
      return {
        icon: <Info className="w-4 h-4 text-accent" />,
        badgeVariant: "teal",
        textColor: "text-accent",
        borderClass: "border-accent/30",
        bgClass: "bg-accent/5",
      };
  }
}

export default function NotificationsPage() {
  const queryClient = useQueryClient();
  const { user, isAdmin } = useAuth();

  // Filters & Pagination State
  const [readFilter, setReadFilter] = useState<string>("all"); // "all", "unread", "read"
  const [severityFilter, setSeverityFilter] = useState<string>("all"); // "all", "critical", "error", "warning", "info"
  const [page, setPage] = useState<number>(1);
  const perPage = 15;

  // Bulk operation & feedback state
  const [isMarkingAll, setIsMarkingAll] = useState<boolean>(false);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Admin Broadcast Modal
  const [isBroadcastModalOpen, setIsBroadcastModalOpen] = useState<boolean>(false);
  const [broadcastTitle, setBroadcastTitle] = useState<string>("");
  const [broadcastMessage, setBroadcastMessage] = useState<string>("");
  const [broadcastSeverity, setBroadcastSeverity] = useState<string>("info");
  const [broadcastEntityType, setBroadcastEntityType] = useState<string>("");
  const [broadcastEntityId, setBroadcastEntityId] = useState<string>("");
  const [broadcastError, setBroadcastError] = useState<string | null>(null);

  // Query Params mapping
  const queryParams = useMemo(() => {
    const params: Record<string, string | number | boolean> = {
      page,
      per_page: perPage,
    };
    if (readFilter === "unread") {
      params.is_read = false;
    } else if (readFilter === "read") {
      params.is_read = true;
    }
    if (severityFilter !== "all") {
      params.severity = severityFilter;
    }
    return params;
  }, [page, perPage, readFilter, severityFilter]);

  // Query /notifications/me
  const {
    data: notifData,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useApiQuery<PaginatedNotifications>({
    queryKey: ["notifications-me", page, perPage, readFilter, severityFilter],
    endpoint: "/notifications/me",
    params: queryParams,
    queryOptions: {
      refetchInterval: 15000,
    },
  });

  // Mark single notification read mutation
  const markReadMutation = useApiMutation<NotificationItem, { id: number }>({
    endpoint: ({ id }) => `/notifications/${id}/read`,
    method: "PATCH",
    mutationOptions: {
      onSuccess: (updated) => {
        setActionSuccess(`Marked "${updated.title}" as read.`);
        setActionError(null);
        queryClient.invalidateQueries({ queryKey: ["notifications-me"] });
      },
      onError: (err) => {
        setActionError(err.message || "Failed to mark notification as read.");
      },
    },
  });

  // Create broadcast mutation (admin only)
  const broadcastMutation = useApiMutation<NotificationItem, BroadcastPayload>({
    endpoint: "/notifications/broadcast",
    method: "POST",
    mutationOptions: {
      onSuccess: (created) => {
        setActionSuccess(`Broadcast alert "${created.title}" dispatched across platform.`);
        setActionError(null);
        queryClient.invalidateQueries({ queryKey: ["notifications-me"] });
        setIsBroadcastModalOpen(false);
        // Reset
        setBroadcastTitle("");
        setBroadcastMessage("");
        setBroadcastSeverity("info");
        setBroadcastEntityType("");
        setBroadcastEntityId("");
        setBroadcastError(null);
      },
      onError: (err) => {
        setBroadcastError(err.message || "Failed to broadcast alert.");
      },
    },
  });

  // Mark all currently visible unread notifications as read
  const handleMarkAllRead = async () => {
    const unreadItems = items.filter((n) => !n.is_read);
    if (unreadItems.length === 0) return;

    setIsMarkingAll(true);
    setActionError(null);
    setActionSuccess(null);

    try {
      // NOTE: Backend /notifications does not have a bulk PATCH endpoint,
      // so we iterate over all unread notifications concurrently via PATCH /notifications/{id}/read
      const results = await Promise.allSettled(
        unreadItems.map((n) => api.patch<NotificationItem>(`/notifications/${n.id}/read`, {}))
      );

      const successful = results.filter((r) => r.status === "fulfilled").length;
      setActionSuccess(`Marked ${successful} notification${successful === 1 ? "" : "s"} as read.`);
      queryClient.invalidateQueries({ queryKey: ["notifications-me"] });
    } catch {
      setActionError("An error occurred while marking all notifications as read.");
    } finally {
      setIsMarkingAll(false);
    }
  };

  // Filter change handlers
  const handleFilterChange = (setter: (v: string) => void, val: string) => {
    setter(val);
    setPage(1);
  };

  const handleResetFilters = () => {
    setReadFilter("all");
    setSeverityFilter("all");
    setPage(1);
  };

  const hasActiveFilters = readFilter !== "all" || severityFilter !== "all";

  // Handle Broadcast submit
  const handleBroadcastSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setBroadcastError(null);

    if (!broadcastTitle.trim() || !broadcastMessage.trim()) {
      setBroadcastError("Title and message body are required.");
      return;
    }

    const payload: BroadcastPayload = {
      title: broadcastTitle.trim(),
      message: broadcastMessage.trim(),
      severity: broadcastSeverity,
      entity_type: broadcastEntityType.trim() || undefined,
      entity_id: broadcastEntityId ? parseInt(broadcastEntityId, 10) : undefined,
    };

    broadcastMutation.mutate(payload);
  };

  // Offline detection
  const isNetworkOffline = isError && !notifData && error?.status === 0;

  if (isNetworkOffline) {
    return (
      <div className="max-w-7xl mx-auto space-y-6">
        <ErrorState
          title="Notification Service Unreachable"
          message="Failed to connect to /api/v1/notifications/me. Please check your backend connection."
          onRetry={() => refetch()}
          retryText="Retry Connection"
        />
      </div>
    );
  }

  const items = notifData?.items || [];
  const totalItems = notifData?.total || 0;
  const totalPages = notifData?.pages || 1;

  // Counters
  const unreadCount = items.filter((n) => !n.is_read).length;
  const criticalCount = items.filter((n) => n.severity === "critical" || n.severity === "error").length;
  const broadcastCount = items.filter((n) => n.user_id === null || n.user_id === undefined).length;

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5 mb-1.5 flex-wrap">
            <h1 className="text-2xl sm:text-3xl font-display font-bold text-text tracking-tight">
              Notifications & Operator Alerts
            </h1>
            <Badge variant="teal" dot>
              Event Bus
            </Badge>
            <span className="text-xs text-muted font-mono">
              GET /notifications/me
            </span>
          </div>
          <p className="text-xs sm:text-sm text-muted max-w-2xl leading-relaxed">
            High-priority operator warnings, sensor connectivity alerts, green-wave preemption triggers, and system broadcasts.
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

          {unreadCount > 0 && (
            <Button
              variant="secondary"
              size="sm"
              onClick={handleMarkAllRead}
              disabled={isMarkingAll}
              className="gap-1.5 border-accent/30 text-accent hover:border-accent"
            >
              <CheckCheck className="w-4 h-4" />
              <span>{isMarkingAll ? "Marking..." : "Mark All as Read"}</span>
            </Button>
          )}

          {isAdmin() && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                setBroadcastError(null);
                setIsBroadcastModalOpen(true);
              }}
              className="gap-1.5"
            >
              <Send className="w-4 h-4" />
              <span>Send Broadcast</span>
            </Button>
          )}
        </div>
      </div>

      {/* Global Alerts / Banners */}
      {actionSuccess && (
        <div className="p-3.5 rounded-xl bg-success/10 border border-success/30 text-success text-xs sm:text-sm flex items-center justify-between animate-in fade-in">
          <div className="flex items-center gap-2">
            <Check className="w-4 h-4 shrink-0" />
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
          <div className="text-[11px] font-medium text-muted uppercase tracking-wider">
            Total Indexed
          </div>
          <div className="mt-1 font-display text-2xl font-bold text-text">
            {totalItems}
          </div>
          <div className="text-[10px] text-muted mt-0.5">Matching current filters</div>
        </Card>

        <Card className="p-4 bg-surface/70 border-white/10">
          <div className="text-[11px] font-medium text-amber uppercase tracking-wider">
            Unread Alerts
          </div>
          <div className="mt-1 font-display text-2xl font-bold text-amber">
            {unreadCount}
          </div>
          <div className="text-[10px] text-muted mt-0.5">Pending operator review</div>
        </Card>

        <Card className="p-4 bg-surface/70 border-white/10">
          <div className="text-[11px] font-medium text-danger uppercase tracking-wider">
            Critical Alarms
          </div>
          <div className="mt-1 font-display text-2xl font-bold text-danger">
            {criticalCount}
          </div>
          <div className="text-[10px] text-muted mt-0.5">Urgent priority events</div>
        </Card>

        <Card className="p-4 bg-surface/70 border-white/10">
          <div className="text-[11px] font-medium text-accent uppercase tracking-wider">
            System Broadcasts
          </div>
          <div className="mt-1 font-display text-2xl font-bold text-accent">
            {broadcastCount}
          </div>
          <div className="text-[10px] text-muted mt-0.5">Global operational alerts</div>
        </Card>
      </div>

      {/* FILTER CONTROLS BAR */}
      <div className="bg-surface/60 p-4 rounded-2xl border border-white/10 flex flex-col md:flex-row md:items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 text-xs font-medium text-muted uppercase tracking-wider">
          <Filter className="w-3.5 h-3.5 text-accent" />
          <span>Filter Stream:</span>
        </div>

        <div className="flex items-center gap-2.5 flex-wrap flex-1 justify-start md:justify-end">
          {/* Read / Unread Filter */}
          <select
            value={readFilter}
            onChange={(e) => handleFilterChange(setReadFilter, e.target.value)}
            className="bg-ink/80 border border-white/15 rounded-xl px-3 py-1.5 text-xs font-medium text-text focus:outline-none focus:border-accent"
          >
            <option value="all">All Read States</option>
            <option value="unread">Unread Only</option>
            <option value="read">Read Only</option>
          </select>

          {/* Severity Filter */}
          <select
            value={severityFilter}
            onChange={(e) => handleFilterChange(setSeverityFilter, e.target.value)}
            className="bg-ink/80 border border-white/15 rounded-xl px-3 py-1.5 text-xs font-medium text-text focus:outline-none focus:border-accent"
          >
            <option value="all">All Severities</option>
            <option value="critical">Critical</option>
            <option value="error">Error</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
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

      {/* NOTIFICATIONS STREAM LIST */}
      {isLoading && items.length === 0 ? (
        <Card className="p-12 text-center flex flex-col items-center justify-center min-h-[350px]">
          <LoadingSpinner size="lg" label="Loading operator notifications..." />
        </Card>
      ) : isError ? (
        <ErrorState
          title="Failed to Load Notifications"
          message={error?.message || "An error occurred while fetching your notifications."}
          onRetry={() => refetch()}
        />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Bell className="w-8 h-8 text-muted" />}
          title="No Notifications Found"
          description={
            hasActiveFilters
              ? "No alerts match the chosen filter criteria. Try resetting filters."
              : "All systems nominal. No alerts or broadcast notifications pending."
          }
          action={
            hasActiveFilters
              ? {
                  label: "Reset Filter Criteria",
                  onClick: handleResetFilters,
                }
              : undefined
          }
        />
      ) : (
        <div className="space-y-3">
          {items.map((notif) => {
            const config = getNotificationSeverityConfig(notif.severity);
            const isBroadcast = notif.user_id === null || notif.user_id === undefined;

            return (
              <Card
                key={notif.id}
                className={`p-4 sm:p-5 border transition-all ${
                  notif.is_read
                    ? "bg-surface/50 border-white/5 opacity-85"
                    : `${config.bgClass} ${config.borderClass} shadow-md`
                } relative`}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-start gap-3.5 flex-1">
                    {/* Severity Icon */}
                    <div className="w-9 h-9 rounded-xl bg-ink/70 border border-white/10 flex items-center justify-center shrink-0 mt-0.5">
                      {config.icon}
                    </div>

                    {/* Notification Body */}
                    <div className="space-y-1.5 flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className={`text-sm sm:text-base font-semibold ${notif.is_read ? "text-text/90" : "text-text"}`}>
                          {notif.title}
                        </h3>

                        <Badge variant={config.badgeVariant} className="text-[10px]">
                          {notif.severity}
                        </Badge>

                        {isBroadcast && (
                          <Badge variant="teal" className="text-[10px]">
                            Broadcast
                          </Badge>
                        )}

                        {!notif.is_read && (
                          <span className="w-2 h-2 rounded-full bg-accent animate-pulse" title="Unread" />
                        )}
                      </div>

                      <p className="text-xs sm:text-sm text-muted leading-relaxed max-w-3xl">
                        {notif.message}
                      </p>

                      {/* Metadata: Entity & Timestamps */}
                      <div className="flex items-center gap-3 pt-1 text-[11px] text-muted flex-wrap">
                        <div className="flex items-center gap-1 font-mono">
                          <Clock className="w-3 h-3 text-muted/70" />
                          <span>{formatRelativeTime(notif.created_at)}</span>
                          <span className="text-muted/50">({formatDateTime(notif.created_at)})</span>
                        </div>

                        {notif.entity_type && (
                          <div className="flex items-center gap-1 px-2 py-0.5 rounded bg-ink/60 border border-white/5 font-mono text-[10px] text-text">
                            <Layers className="w-2.5 h-2.5 text-accent" />
                            <span>{notif.entity_type} #{notif.entity_id ?? "—"}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="shrink-0 self-start sm:self-center">
                    {!notif.is_read ? (
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => markReadMutation.mutate({ id: notif.id })}
                        disabled={markReadMutation.isPending}
                        className="text-xs px-3 py-1.5 border-white/15 hover:border-accent/40"
                        title="Mark as Read"
                      >
                        <Check className="w-3.5 h-3.5 mr-1 text-accent" />
                        <span>Mark Read</span>
                      </Button>
                    ) : (
                      <div className="flex items-center gap-1 text-[11px] text-muted font-mono py-1 px-2.5">
                        <Check className="w-3 h-3 text-muted" />
                        <span>Read</span>
                      </div>
                    )}
                  </div>
                </div>
              </Card>
            );
          })}

          {/* Pagination Footer */}
          <Card className="p-4 border-white/10 bg-surface/70 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
            <div className="text-muted">
              Showing{" "}
              <span className="font-mono text-text font-medium">
                {(page - 1) * perPage + 1}
              </span>{" "}
              to{" "}
              <span className="font-mono text-text font-medium">
                {Math.min(page * perPage, totalItems)}
              </span>{" "}
              of <span className="font-mono text-text font-medium">{totalItems}</span> notifications
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
          </Card>
        </div>
      )}

      {/* ADMIN BROADCAST MODAL */}
      {isBroadcastModalOpen && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4"
        >
          <div
            onClick={() => setIsBroadcastModalOpen(false)}
            className="fixed inset-0 bg-black/75 backdrop-blur-sm transition-opacity"
          />

          <div className="relative w-full max-w-lg bg-surface border border-accent/40 rounded-2xl shadow-2xl p-6 z-10 space-y-5 animate-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between border-b border-white/10 pb-4">
              <div>
                <div className="flex items-center gap-2">
                  <Send className="w-5 h-5 text-accent" />
                  <h2 className="text-lg font-display font-bold text-text">
                    Create System Broadcast Alert
                  </h2>
                </div>
                <p className="text-xs text-muted mt-0.5">
                  Delivered system-wide to all operators (Admin Privilege)
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsBroadcastModalOpen(false)}
                className="w-8 h-8 rounded-lg bg-ink hover:bg-white/10 border border-white/10 flex items-center justify-center text-muted hover:text-text cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {broadcastError && (
              <div className="p-3 rounded-lg bg-danger/15 border border-danger/30 text-danger text-xs flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>{broadcastError}</span>
              </div>
            )}

            <form onSubmit={handleBroadcastSubmit} className="space-y-4 text-xs">
              <div>
                <label className="block text-muted font-medium mb-1">
                  Alert Title *
                </label>
                <input
                  type="text"
                  maxLength={200}
                  value={broadcastTitle}
                  onChange={(e) => setBroadcastTitle(e.target.value)}
                  placeholder="e.g. Critical Sensor Gateway Maintenance"
                  className="w-full bg-ink border border-white/15 rounded-xl px-3 py-2 text-text text-xs focus:outline-none focus:border-accent"
                />
              </div>

              <div>
                <label className="block text-muted font-medium mb-1">
                  Severity Classification *
                </label>
                <select
                  value={broadcastSeverity}
                  onChange={(e) => setBroadcastSeverity(e.target.value)}
                  className="w-full bg-ink border border-white/15 rounded-xl px-3 py-2 text-text text-xs focus:outline-none focus:border-accent"
                >
                  <option value="info">Info</option>
                  <option value="warning">Warning</option>
                  <option value="error">Error</option>
                  <option value="critical">Critical</option>
                </select>
              </div>

              <div>
                <label className="block text-muted font-medium mb-1">
                  Message Body *
                </label>
                <textarea
                  rows={3}
                  value={broadcastMessage}
                  onChange={(e) => setBroadcastMessage(e.target.value)}
                  placeholder="Detailed operational notice broadcasted to all active console users..."
                  className="w-full bg-ink border border-white/15 rounded-xl p-3 text-text text-xs focus:outline-none focus:border-accent placeholder:text-muted/60"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-muted font-medium mb-1">
                    Entity Type (Optional)
                  </label>
                  <input
                    type="text"
                    value={broadcastEntityType}
                    onChange={(e) => setBroadcastEntityType(e.target.value)}
                    placeholder="e.g. intersection, signal"
                    className="w-full bg-ink border border-white/15 rounded-xl px-3 py-2 text-text text-xs focus:outline-none focus:border-accent"
                  />
                </div>

                <div>
                  <label className="block text-muted font-medium mb-1">
                    Entity ID (Optional)
                  </label>
                  <input
                    type="number"
                    value={broadcastEntityId}
                    onChange={(e) => setBroadcastEntityId(e.target.value)}
                    placeholder="e.g. 5"
                    className="w-full bg-ink border border-white/15 rounded-xl px-3 py-2 text-text text-xs focus:outline-none focus:border-accent font-mono"
                  />
                </div>
              </div>

              <div className="pt-3 border-t border-white/10 flex items-center justify-end gap-2.5">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setIsBroadcastModalOpen(false)}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  disabled={broadcastMutation.isPending}
                >
                  {broadcastMutation.isPending ? "Broadcasting..." : "Dispatch Broadcast"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
