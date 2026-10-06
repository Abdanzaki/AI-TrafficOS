"use client";

import React, { useEffect, useState } from "react";
import { getHealth, API_BASE } from "@/lib/api";

export const SystemStatus: React.FC = () => {
  const [status, setStatus] = useState<"checking" | "online" | "offline">("checking");
  const [lastChecked, setLastChecked] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;

    getHealth()
      .then(() => {
        if (!ignore) {
          setStatus("online");
          setLastChecked(new Date().toLocaleTimeString());
        }
      })
      .catch(() => {
        if (!ignore) {
          setStatus("offline");
          setLastChecked(new Date().toLocaleTimeString());
        }
      });

    return () => {
      ignore = true;
    };
  }, []);

  const handleManualCheck = () => {
    setStatus("checking");
    getHealth()
      .then(() => {
        setStatus("online");
        setLastChecked(new Date().toLocaleTimeString());
      })
      .catch(() => {
        setStatus("offline");
        setLastChecked(new Date().toLocaleTimeString());
      });
  };

  return (
    <div
      role="region"
      aria-label="Backend system status"
      className="inline-flex flex-col sm:flex-row items-center gap-3 p-3.5 px-5 rounded-[14px] bg-surface/80 border border-white/10 shadow-md backdrop-blur-sm"
    >
      <div className="flex items-center gap-2.5">
        <span className="relative flex h-3 w-3">
          {status === "online" && (
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-success opacity-75" />
          )}
          {status === "checking" && (
            <span className="animate-pulse absolute inline-flex h-full w-full rounded-full bg-amber opacity-75" />
          )}
          <span
            className={`relative inline-flex rounded-full h-3 w-3 ${
              status === "online"
                ? "bg-success"
                : status === "checking"
                ? "bg-amber"
                : "bg-danger"
            }`}
          />
        </span>

        <span className="text-xs sm:text-sm font-medium text-text">
          {status === "online" && (
            <span className="text-success font-semibold">Backend online</span>
          )}
          {status === "checking" && (
            <span className="text-amber">Connecting to backend service...</span>
          )}
          {status === "offline" && (
            <span className="text-danger">
              Backend offline — start the FastAPI service (Phase 2)
            </span>
          )}
        </span>
      </div>

      <div className="flex items-center gap-2 text-xs text-muted">
        <span className="hidden sm:inline text-white/20">•</span>
        <span className="font-mono text-[11px] text-muted/80">{API_BASE}</span>
        <button
          type="button"
          onClick={handleManualCheck}
          className="ml-1 text-[11px] underline underline-offset-2 hover:text-text transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent rounded"
          title="Retry backend health check"
          aria-label="Retry backend connection check"
        >
          Check now
        </button>
        {lastChecked && (
          <span className="text-[10px] text-muted/60">
            ({lastChecked})
          </span>
        )}
      </div>
    </div>
  );
};
