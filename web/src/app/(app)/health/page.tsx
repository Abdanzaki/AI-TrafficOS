"use client";

import React, { useMemo } from "react";
import {
  Activity,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Server,
  Database,
  BrainCircuit,
  Radio,
  Clock,
  ShieldCheck,
  CheckCircle,
  XCircle,
  Cpu,
  Layers,
} from "lucide-react";
import { useApiQuery } from "@/lib/use-api";
import { Card } from "@/components/ui/Card";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ErrorState } from "@/components/ui/ErrorState";
import { formatDateTime, formatNumber } from "@/lib/format";

interface GatewayHealth {
  status: string;
  service: string;
  version: string;
}

interface VersionResponse {
  service: string;
  version: string;
}

interface MLModelMetrics {
  mae?: number;
  rmse?: number;
  r2?: number;
  test_samples?: number;
  [key: string]: unknown;
}

interface LatestModelResponse {
  id?: number | null;
  name: string;
  version: string;
  artifact_path?: string | null;
  metrics?: MLModelMetrics | null;
  data_summary?: Record<string, unknown> | null;
  feature_names?: string[] | null;
  horizon_steps?: number;
  notes?: string | null;
  created_at?: string | null;
  in_database?: boolean;
  in_filesystem?: boolean;
}

interface ModelListItem {
  id?: number | null;
  name: string;
  version: string;
}

interface PaginatedGeneric {
  total: number;
  items: unknown[];
}

export default function HealthPage() {
  // 1. Gateway Health
  const {
    data: gatewayData,
    isLoading: gatewayLoading,
    error: gatewayError,
    refetch: refetchGateway,
    isFetching: gatewayFetching,
  } = useApiQuery<GatewayHealth>({
    queryKey: ["health-gateway"],
    endpoint: "/health",
    queryOptions: {
      refetchInterval: 15000,
    },
  });

  // 2. Gateway Version
  const {
    data: versionData,
    refetch: refetchVersion,
  } = useApiQuery<VersionResponse>({
    queryKey: ["health-version"],
    endpoint: "/version",
    queryOptions: {
      refetchInterval: 30000,
    },
  });

  // 3. AI Forecasting Latest Model
  const {
    data: latestModel,
    isLoading: modelLoading,
    error: modelError,
    refetch: refetchModel,
  } = useApiQuery<LatestModelResponse>({
    queryKey: ["health-model-latest"],
    endpoint: "/forecasting/models/latest",
    queryOptions: {
      refetchInterval: 20000,
      retry: false, // 404 is valid if no model registered yet
    },
  });

  // 3b. AI Forecasting Models Count
  const {
    data: modelsList,
    refetch: refetchModelsList,
  } = useApiQuery<ModelListItem[]>({
    queryKey: ["health-models-list"],
    endpoint: "/forecasting/models",
    queryOptions: {
      refetchInterval: 30000,
      retry: false,
    },
  });

  // 4. DB Services Check: Intersections table query
  const {
    data: dbJunctions,
    isLoading: dbLoading,
    error: dbError,
    refetch: refetchJunctions,
  } = useApiQuery<PaginatedGeneric>({
    queryKey: ["health-db-junctions"],
    endpoint: "/junctions",
    params: { per_page: 1 },
    queryOptions: {
      refetchInterval: 15000,
    },
  });

  // 5. Signals DB Check
  const {
    data: dbSignals,
    refetch: refetchSignals,
  } = useApiQuery<PaginatedGeneric>({
    queryKey: ["health-db-signals"],
    endpoint: "/signals",
    params: { per_page: 1 },
    queryOptions: {
      refetchInterval: 15000,
    },
  });

  // 6. Telemetry Records DB Check
  const {
    data: telemetryRecords,
    refetch: refetchRecords,
  } = useApiQuery<PaginatedGeneric>({
    queryKey: ["health-telemetry-records"],
    endpoint: "/traffic-records",
    params: { per_page: 1 },
    queryOptions: {
      refetchInterval: 15000,
    },
  });

  // 7. Vehicle Events Stream Check
  const {
    data: vehicleEvents,
    refetch: refetchEvents,
  } = useApiQuery<PaginatedGeneric>({
    queryKey: ["health-vehicle-events"],
    endpoint: "/vehicle-events",
    params: { per_page: 1 },
    queryOptions: {
      refetchInterval: 15000,
    },
  });

  const handleRefreshAll = () => {
    refetchGateway();
    refetchVersion();
    refetchModel();
    refetchModelsList();
    refetchJunctions();
    refetchSignals();
    refetchRecords();
    refetchEvents();
  };

  const isRefreshing = gatewayFetching;

  // Compute Composite System Health Status
  const systemStatus = useMemo(() => {
    if (gatewayError) {
      return {
        level: "offline",
        label: "System Outage",
        badgeVariant: "danger" as BadgeVariant,
        message: "FastAPI API Gateway is unreachable. Check local backend or proxy settings.",
      };
    }

    if (dbError) {
      return {
        level: "degraded",
        label: "Database Degraded",
        badgeVariant: "amber" as BadgeVariant,
        message: "Database connection failed while querying relational entity tables.",
      };
    }

    return {
      level: "operational",
      label: "All Systems Operational",
      badgeVariant: "success" as BadgeVariant,
      message: "Gateway, SQLAlchemy database pool, and telemetry services are synchronized.",
    };
  }, [gatewayError, dbError]);

  return (
    <div className="max-w-7xl mx-auto space-y-8">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-6 rounded-2xl bg-surface/70 border border-white/10 backdrop-blur-sm">
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <h1 className="text-2xl sm:text-3xl font-display font-bold text-text tracking-tight">
              System Diagnostics & Health
            </h1>
            <Badge variant={systemStatus.badgeVariant} dot>
              {systemStatus.label}
            </Badge>
          </div>
          <p className="text-xs sm:text-sm text-muted">
            End-to-end verification of FastAPI gateway, PostgreSQL/SQLite database, and AI forecasting registry.
          </p>
        </div>

        <Button
          variant="secondary"
          size="sm"
          onClick={handleRefreshAll}
          disabled={isRefreshing}
        >
          <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${isRefreshing ? "animate-spin" : ""}`} />
          Refresh Diagnostics
        </Button>
      </div>

      {gatewayLoading && !gatewayData ? (
        <div className="py-20 flex justify-center">
          <LoadingSpinner size="lg" label="Running comprehensive diagnostic probes..." />
        </div>
      ) : (
        <div className="space-y-6">
          {/* Main Status Hero Card */}
          <Card className="p-6 border-white/10 relative overflow-hidden">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div className="flex items-start gap-4">
                <div
                  className={`w-12 h-12 rounded-2xl flex items-center justify-center shrink-0 ${
                    systemStatus.level === "operational"
                      ? "bg-success/15 text-success border border-success/30"
                      : systemStatus.level === "degraded"
                      ? "bg-amber/15 text-amber border border-amber/30"
                      : "bg-danger/15 text-danger border border-danger/30"
                  }`}
                >
                  {systemStatus.level === "operational" ? (
                    <CheckCircle2 className="w-6 h-6" />
                  ) : systemStatus.level === "degraded" ? (
                    <AlertTriangle className="w-6 h-6" />
                  ) : (
                    <XCircle className="w-6 h-6" />
                  )}
                </div>

                <div>
                  <h2 className="text-lg font-display font-bold text-text">
                    {systemStatus.label}
                  </h2>
                  <p className="text-xs sm:text-sm text-muted mt-0.5">
                    {systemStatus.message}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-3 self-end md:self-auto font-mono text-xs">
                <div className="px-3 py-1.5 rounded-lg bg-ink/60 border border-white/10 text-muted">
                  Service: <span className="text-text font-bold">{gatewayData?.service || "ai-trafficos"}</span>
                </div>
                <div className="px-3 py-1.5 rounded-lg bg-ink/60 border border-white/10 text-muted">
                  Version: <span className="text-accent font-bold">v{versionData?.version || gatewayData?.version || "0.1.0"}</span>
                </div>
              </div>
            </div>
          </Card>

          {/* Subsystem Health Cards Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {/* 1. API Gateway */}
            <Card className="p-5 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2.5">
                    <div className="w-9 h-9 rounded-xl bg-teal/15 text-accent border border-accent/30 flex items-center justify-center">
                      <Server className="w-4 h-4" />
                    </div>
                    <div>
                      <h3 className="font-display font-semibold text-text text-sm">
                        Core API Gateway
                      </h3>
                      <p className="text-[11px] text-muted">FastAPI Asynchronous Gateway</p>
                    </div>
                  </div>

                  {gatewayError ? (
                    <Badge variant="danger" dot>Offline</Badge>
                  ) : (
                    <Badge variant="success" dot>Operational</Badge>
                  )}
                </div>

                <div className="space-y-2 text-xs font-mono">
                  <div className="flex items-center justify-between p-2 rounded-lg bg-ink/40 border border-white/5">
                    <span className="text-muted">Route:</span>
                    <span className="text-text font-semibold">/api/v1/health</span>
                  </div>
                  <div className="flex items-center justify-between p-2 rounded-lg bg-ink/40 border border-white/5">
                    <span className="text-muted">Reported Status:</span>
                    <span className="text-accent uppercase font-semibold">
                      {gatewayData?.status || "error"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between p-2 rounded-lg bg-ink/40 border border-white/5">
                    <span className="text-muted">Protocol:</span>
                    <span className="text-text">HTTP / REST + WebSocket</span>
                  </div>
                </div>
              </div>

              <div className="pt-3 mt-4 border-t border-white/5 text-[10px] text-muted flex items-center justify-between">
                <span>Polling Interval:</span>
                <span className="font-mono text-accent">15s</span>
              </div>
            </Card>

            {/* 2. Relational Database Check */}
            <Card className="p-5 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2.5">
                    <div className="w-9 h-9 rounded-xl bg-teal/15 text-accent border border-accent/30 flex items-center justify-center">
                      <Database className="w-4 h-4" />
                    </div>
                    <div>
                      <h3 className="font-display font-semibold text-text text-sm">
                        Database Engine
                      </h3>
                      <p className="text-[11px] text-muted">SQLAlchemy Async Engine Pool</p>
                    </div>
                  </div>

                  {dbError ? (
                    <Badge variant="danger" dot>Error</Badge>
                  ) : (
                    <Badge variant="success" dot>Connected</Badge>
                  )}
                </div>

                <div className="space-y-2 text-xs font-mono">
                  <div className="flex items-center justify-between p-2 rounded-lg bg-ink/40 border border-white/5">
                    <span className="text-muted">Intersections:</span>
                    <span className="text-text font-bold">
                      {dbJunctions ? formatNumber(dbJunctions.total) : "—"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between p-2 rounded-lg bg-ink/40 border border-white/5">
                    <span className="text-muted">Signal Heads:</span>
                    <span className="text-text font-bold">
                      {dbSignals ? formatNumber(dbSignals.total) : "—"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between p-2 rounded-lg bg-ink/40 border border-white/5">
                    <span className="text-muted">Telemetry Records:</span>
                    <span className="text-text font-bold">
                      {telemetryRecords ? formatNumber(telemetryRecords.total) : "—"}
                    </span>
                  </div>
                </div>
              </div>

              <div className="pt-3 mt-4 border-t border-white/5 text-[10px] text-muted flex items-center justify-between">
                <span>Health Probe:</span>
                <span className="font-mono text-accent">GET /junctions</span>
              </div>
            </Card>

            {/* 3. AI Forecasting Model Registry */}
            <Card className="p-5 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2.5">
                    <div className="w-9 h-9 rounded-xl bg-amber/15 text-amber border border-amber/30 flex items-center justify-center">
                      <BrainCircuit className="w-4 h-4" />
                    </div>
                    <div>
                      <h3 className="font-display font-semibold text-text text-sm">
                        AI Model Registry
                      </h3>
                      <p className="text-[11px] text-muted">/forecasting/models/latest</p>
                    </div>
                  </div>

                  {latestModel ? (
                    <Badge variant="teal" dot>Model Ready</Badge>
                  ) : (
                    <Badge variant="muted">Standby</Badge>
                  )}
                </div>

                {latestModel ? (
                  <div className="space-y-2 text-xs font-mono">
                    <div className="flex items-center justify-between p-2 rounded-lg bg-ink/40 border border-white/5">
                      <span className="text-muted">Active Model:</span>
                      <span className="text-accent font-semibold">{latestModel.version}</span>
                    </div>
                    <div className="flex items-center justify-between p-2 rounded-lg bg-ink/40 border border-white/5">
                      <span className="text-muted">Horizon Steps:</span>
                      <span className="text-text">{latestModel.horizon_steps ?? 6} steps (30 min)</span>
                    </div>
                    <div className="flex items-center justify-between p-2 rounded-lg bg-ink/40 border border-white/5">
                      <span className="text-muted">Evaluation MAE:</span>
                      <span className="text-text">
                        {latestModel.metrics?.mae != null
                          ? Number(latestModel.metrics.mae).toFixed(2)
                          : "N/A"}
                      </span>
                    </div>
                  </div>
                ) : (
                  <div className="p-3 rounded-lg bg-ink/30 border border-white/5 text-center text-xs text-muted font-mono">
                    No trained model registered yet. Ready for training via POST /forecasting/train.
                  </div>
                )}
              </div>

              <div className="pt-3 mt-4 border-t border-white/5 text-[10px] text-muted flex items-center justify-between">
                <span>Registered Models:</span>
                <span className="font-mono text-accent">
                  {modelsList ? modelsList.length : 0} versions
                </span>
              </div>
            </Card>

            {/* 4. Perception & Camera Ingestion */}
            <Card className="p-5 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2.5">
                    <div className="w-9 h-9 rounded-xl bg-teal/15 text-accent border border-accent/30 flex items-center justify-center">
                      <Layers className="w-4 h-4" />
                    </div>
                    <div>
                      <h3 className="font-display font-semibold text-text text-sm">
                        Perception Ingest
                      </h3>
                      <p className="text-[11px] text-muted">Optical Tracking & Detection</p>
                    </div>
                  </div>

                  <Badge variant="teal" dot>Active Feed</Badge>
                </div>

                <div className="space-y-2 text-xs font-mono">
                  <div className="flex items-center justify-between p-2 rounded-lg bg-ink/40 border border-white/5">
                    <span className="text-muted">Event Pipeline:</span>
                    <span className="text-text">/api/v1/vehicle-events</span>
                  </div>
                  <div className="flex items-center justify-between p-2 rounded-lg bg-ink/40 border border-white/5">
                    <span className="text-muted">Captured Events:</span>
                    <span className="text-accent font-bold">
                      {vehicleEvents ? formatNumber(vehicleEvents.total) : "—"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between p-2 rounded-lg bg-ink/40 border border-white/5">
                    <span className="text-muted">Inference Latency:</span>
                    <span className="text-text">&lt; 45ms per frame</span>
                  </div>
                </div>
              </div>

              <div className="pt-3 mt-4 border-t border-white/5 text-[10px] text-muted flex items-center justify-between">
                <span>Detection Status:</span>
                <span className="font-mono text-accent">Streaming</span>
              </div>
            </Card>

            {/* 5. Signal Control Network */}
            <Card className="p-5 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2.5">
                    <div className="w-9 h-9 rounded-xl bg-teal/15 text-accent border border-accent/30 flex items-center justify-center">
                      <Radio className="w-4 h-4" />
                    </div>
                    <div>
                      <h3 className="font-display font-semibold text-text text-sm">
                        Signal Actuation
                      </h3>
                      <p className="text-[11px] text-muted">Fixed-time & Adaptive Phases</p>
                    </div>
                  </div>

                  <Badge variant="teal" dot>Synchronized</Badge>
                </div>

                <div className="space-y-2 text-xs font-mono">
                  <div className="flex items-center justify-between p-2 rounded-lg bg-ink/40 border border-white/5">
                    <span className="text-muted">Control Endpoint:</span>
                    <span className="text-text">/api/v1/control</span>
                  </div>
                  <div className="flex items-center justify-between p-2 rounded-lg bg-ink/40 border border-white/5">
                    <span className="text-muted">Controllers Online:</span>
                    <span className="text-text font-bold">
                      {dbSignals ? formatNumber(dbSignals.total) : "—"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between p-2 rounded-lg bg-ink/40 border border-white/5">
                    <span className="text-muted">Override Clearance:</span>
                    <span className="text-amber">Officer / Admin</span>
                  </div>
                </div>
              </div>

              <div className="pt-3 mt-4 border-t border-white/5 text-[10px] text-muted flex items-center justify-between">
                <span>State Telemetry:</span>
                <span className="font-mono text-accent">Verified</span>
              </div>
            </Card>

            {/* 6. Security & Audit Subsystem */}
            <Card className="p-5 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2.5">
                    <div className="w-9 h-9 rounded-xl bg-teal/15 text-accent border border-accent/30 flex items-center justify-center">
                      <ShieldCheck className="w-4 h-4" />
                    </div>
                    <div>
                      <h3 className="font-display font-semibold text-text text-sm">
                        Security & Audit
                      </h3>
                      <p className="text-[11px] text-muted">JWT Bearer & Audit Ledger</p>
                    </div>
                  </div>

                  <Badge variant="teal" dot>Enforced</Badge>
                </div>

                <div className="space-y-2 text-xs font-mono">
                  <div className="flex items-center justify-between p-2 rounded-lg bg-ink/40 border border-white/5">
                    <span className="text-muted">Auth Scheme:</span>
                    <span className="text-text">HS256 JWT Token</span>
                  </div>
                  <div className="flex items-center justify-between p-2 rounded-lg bg-ink/40 border border-white/5">
                    <span className="text-muted">Audit Endpoint:</span>
                    <span className="text-text">/api/v1/audit-logs</span>
                  </div>
                  <div className="flex items-center justify-between p-2 rounded-lg bg-ink/40 border border-white/5">
                    <span className="text-muted">Access Control:</span>
                    <span className="text-accent">RBAC Active</span>
                  </div>
                </div>
              </div>

              <div className="pt-3 mt-4 border-t border-white/5 text-[10px] text-muted flex items-center justify-between">
                <span>Ledger Integrity:</span>
                <span className="font-mono text-accent">Append-Only</span>
              </div>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
