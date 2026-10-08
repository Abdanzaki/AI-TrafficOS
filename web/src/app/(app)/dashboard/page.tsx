"use client";

import React from "react";
import Link from "next/link";
import {
  Activity,
  AlertTriangle,
  Car,
  FileText,
  Radio,
  Route,
  ShieldCheck,
  Siren,
  SlidersHorizontal,
  Users,
  CheckCircle2,
  Clock,
  Sparkles,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth";
import { useApiQuery } from "@/lib/use-api";
import { useTopic } from "@/lib/realtime";
import { Card } from "@/components/ui/Card";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ErrorState } from "@/components/ui/ErrorState";

interface HealthData {
  status: string;
  timestamp?: string;
  version?: string;
  [key: string]: unknown;
}

export default function DashboardPage() {
  const queryClient = useQueryClient();
  const { user, isAdmin, isOfficer } = useAuth();

  // Invalidate health query whenever system.status real-time event arrives (replaces 15s polling)
  useTopic("system.status", () => {
    queryClient.invalidateQueries({ queryKey: ["backend-health"] });
  });

  const {
    data: health,
    isLoading: healthLoading,
    error: healthError,
    refetch: refetchHealth,
  } = useApiQuery<HealthData>({
    queryKey: ["backend-health"],
    endpoint: "/health",
  });

  const quickNav = [
    {
      title: "Traffic Perception",
      desc: "Live vehicle detection and spatial count sensors",
      href: "/traffic",
      icon: Car,
      color: "text-accent",
    },
    {
      title: "Signals & Telemetry",
      desc: "Optical state detection and phase monitors",
      href: "/signals",
      icon: Radio,
      color: "text-accent",
    },
    {
      title: "Active Control",
      desc: "Supervisory signal overrides and timing adjustments",
      href: "/control",
      icon: SlidersHorizontal,
      color: "text-amber",
      badge: isAdmin() || isOfficer() ? "Write Access" : "Read-only",
      badgeVariant: (isAdmin() || isOfficer() ? "amber" : "muted") as BadgeVariant,
    },
    {
      title: "Incident Flags",
      desc: "Anomalous stall and lane obstruction detection",
      href: "/incidents",
      icon: AlertTriangle,
      color: "text-danger",
    },
    {
      title: "Emergency Corridor",
      desc: "Preemption routing and priority dispatch",
      href: "/emergency",
      icon: Siren,
      color: "text-danger",
      badge: isAdmin() || isOfficer() ? "Write Access" : "Read-only",
      badgeVariant: (isAdmin() || isOfficer() ? "amber" : "muted") as BadgeVariant,
    },
    {
      title: "Routing Guidance",
      desc: "Congestion-aware arterial diversion",
      href: "/routing",
      icon: Route,
      color: "text-accent",
    },
    {
      title: "Audit & Governance",
      desc: "Cryptographic activity verification trail",
      href: "/audit-logs",
      icon: FileText,
      color: "text-muted",
    },
    {
      title: "User Directory",
      desc: "Role assignments and RBAC security policies",
      href: "/users",
      icon: Users,
      color: "text-accent",
      hidden: !isAdmin(),
    },
  ].filter((item) => !item.hidden);

  return (
    <div className="max-w-7xl mx-auto space-y-8">
      {/* Welcome Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-6 sm:p-8 rounded-2xl bg-surface/70 border border-white/10 relative overflow-hidden shadow-lg backdrop-blur-sm">
        <div className="pointer-events-none absolute -right-20 -bottom-20 w-80 h-80 bg-accent/10 blur-[100px] rounded-full" />

        <div className="relative">
          <div className="flex items-center gap-2 mb-2">
            <Badge variant="teal" dot>
              Phase 7 Operational
            </Badge>
            <span className="text-white/20">•</span>
            <span className="text-xs text-muted font-mono">
              FastAPI v1
            </span>
          </div>

          <h1 className="text-2xl sm:text-3xl font-display font-bold text-text tracking-tight">
            Welcome back, {user?.full_name || user?.email}
          </h1>

          <p className="mt-2 text-xs sm:text-sm text-muted max-w-2xl leading-relaxed">
            Traffic operations command interface initialized. Active clearance level:{" "}
            <span className="text-text font-semibold uppercase font-mono">
              {user?.role}
            </span>
            . All actions are logged to the immutable audit ledger.
          </p>
        </div>

        <div className="relative flex items-center gap-3 shrink-0">
          <Button href="/audit-logs" variant="secondary" size="sm">
            <FileText className="w-4 h-4 mr-1.5" />
            Audit Ledger
          </Button>
          {isAdmin() && (
            <Button href="/users" variant="primary" size="sm">
              <Users className="w-4 h-4 mr-1.5" />
              Manage Users
            </Button>
          )}
        </div>
      </div>

      {/* Backend Status Strip */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="p-5 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted font-medium">FastAPI Backend</span>
            <Activity className="w-4 h-4 text-accent" />
          </div>

          <div className="mt-4">
            {healthLoading ? (
              <div className="flex items-center gap-2 text-xs text-muted">
                <LoadingSpinner size="sm" />
                <span>Checking /api/v1/health...</span>
              </div>
            ) : healthError ? (
              <div className="flex items-center justify-between text-xs text-danger">
                <span>Service unreachable</span>
                <button
                  type="button"
                  onClick={() => refetchHealth()}
                  className="underline hover:text-text cursor-pointer"
                >
                  Retry
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2 text-sm font-semibold text-success">
                <CheckCircle2 className="w-4 h-4" />
                <span>{health?.status === "ok" ? "Online & Healthy" : health?.status || "Connected"}</span>
              </div>
            )}
          </div>

          <div className="mt-3 pt-3 border-t border-white/5 text-[11px] text-muted/70 font-mono flex items-center justify-between">
            <span>Target: /api/v1</span>
            <span>HTTP 200</span>
          </div>
        </Card>

        <Card className="p-5 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted font-medium">Clearance Profile</span>
            <ShieldCheck className="w-4 h-4 text-accent" />
          </div>

          <div className="mt-4">
            <div className="text-sm font-semibold text-text capitalize">
              Role: {user?.role.replace("_", " ")}
            </div>
            <div className="text-xs text-muted mt-0.5 truncate font-mono">
              Account: {user?.email}
            </div>
          </div>

          <div className="mt-3 pt-3 border-t border-white/5 text-[11px] text-muted/70 flex items-center justify-between">
            <span>Write Capability:</span>
            <span className={isAdmin() || isOfficer() ? "text-amber font-mono" : "text-muted font-mono"}>
              {isAdmin() || isOfficer() ? "Granted (Officer/Admin)" : "Read-Only (Analyst)"}
            </span>
          </div>
        </Card>

        <Card className="p-5 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted font-medium">Session State</span>
            <Clock className="w-4 h-4 text-accent" />
          </div>

          <div className="mt-4">
            <div className="text-sm font-semibold text-success flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-success animate-pulse" />
              Authenticated (Active JWT)
            </div>
            <div className="text-xs text-muted mt-0.5">
              Silent auto-rotation enabled
            </div>
          </div>

          <div className="mt-3 pt-3 border-t border-white/5 text-[11px] text-muted/70 font-mono flex items-center justify-between">
            <span>Token Storage:</span>
            <span>localStorage</span>
          </div>
        </Card>
      </div>

      {/* Quick Access Grid */}
      <div className="space-y-4">
        <div>
          <h2 className="text-lg font-display font-semibold text-text">
            Operational Surfaces
          </h2>
          <p className="text-xs text-muted mt-1">
            Core functional consoles available for monitoring and actuation.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {quickNav.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.title}
                href={item.href}
                className="group block p-5 rounded-2xl bg-surface/60 border border-white/10 hover:border-accent/40 hover:bg-surface/90 transition-all shadow-sm"
              >
                <div className="flex items-center justify-between mb-3">
                  <div className="w-10 h-10 rounded-xl bg-ink/70 border border-white/10 flex items-center justify-center text-text group-hover:scale-105 transition-transform">
                    <Icon className={`w-5 h-5 ${item.color}`} />
                  </div>
                  {item.badge && (
                    <Badge variant={item.badgeVariant} className="text-[9px]">
                      {item.badge}
                    </Badge>
                  )}
                </div>

                <h3 className="font-display font-semibold text-sm text-text group-hover:text-accent transition-colors">
                  {item.title}
                </h3>

                <p className="mt-1 text-xs text-muted leading-relaxed">
                  {item.desc}
                </p>
              </Link>
            );
          })}
        </div>
      </div>
    </div>
  );
}
