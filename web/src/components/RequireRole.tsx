"use client";

import React from "react";
import { ShieldAlert, ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useAuth, type UserRole } from "@/lib/auth";
import { LoadingSpinner } from "./ui/LoadingSpinner";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";

export interface RequireRoleProps {
  allowedRoles: UserRole[];
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

export const RequireRole: React.FC<RequireRoleProps> = ({
  allowedRoles,
  children,
  fallback,
}) => {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-[50vh] flex items-center justify-center p-6">
        <LoadingSpinner size="md" label="Verifying role permissions..." />
      </div>
    );
  }

  if (!user || !allowedRoles.includes(user.role)) {
    if (fallback) {
      return <>{fallback}</>;
    }

    return (
      <div className="min-h-[60vh] flex items-center justify-center p-6">
        <div className="max-w-lg w-full p-8 rounded-[14px] bg-surface/80 border border-amber/30 text-center flex flex-col items-center shadow-lg">
          <div className="w-14 h-14 rounded-2xl bg-amber/15 border border-amber/30 flex items-center justify-center text-amber mb-5">
            <ShieldAlert className="w-7 h-7" />
          </div>

          <Badge variant="amber" className="mb-3">
            HTTP 403 Forbidden
          </Badge>

          <h2 className="text-xl sm:text-2xl font-display font-bold text-text">
            Access Restricted
          </h2>

          <p className="mt-3 text-sm text-muted leading-relaxed max-w-sm">
            Your current assigned role (
            <span className="font-semibold text-text font-mono">
              {user?.role || "anonymous"}
            </span>
            ) does not have sufficient clearance to access this control surface.
          </p>

          <div className="mt-4 p-3 rounded-lg bg-ink/60 border border-white/5 w-full text-xs text-muted flex items-center justify-between">
            <span>Required Clearance:</span>
            <span className="font-mono text-accent font-medium">
              {allowedRoles.join(" | ")}
            </span>
          </div>

          <div className="mt-6 flex items-center justify-center gap-3">
            <Button href="/dashboard" variant="secondary" size="sm">
              <ArrowLeft className="w-3.5 h-3.5 mr-1.5" />
              Return to Dashboard
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return <>{children}</>;
};
