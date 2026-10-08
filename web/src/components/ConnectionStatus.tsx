"use client";

import React, { useState } from "react";
import { useRealtime } from "../lib/realtime";
import { formatDateTime, formatRelativeTime } from "../lib/format";

export interface ConnectionStatusProps {
  className?: string;
}

export const ConnectionStatus: React.FC<ConnectionStatusProps> = ({ className = "" }) => {
  const { status, isStale, lastEventAt, reconnect } = useRealtime();
  const [showTooltip, setShowTooltip] = useState(false);

  // Compute state representation
  let stateKey: "live" | "connecting" | "stale" | "offline";
  if (status === "connected") {
    stateKey = isStale ? "stale" : "live";
  } else if (status === "connecting") {
    stateKey = "connecting";
  } else {
    stateKey = "offline";
  }

  const tooltipText = lastEventAt
    ? `Last event: ${formatDateTime(new Date(lastEventAt))} (${formatRelativeTime(new Date(lastEventAt))})`
    : "No events received yet";

  return (
    <div
      className={`relative inline-flex items-center ${className}`}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      {stateKey === "live" && (
        <span
          data-testid="connection-status-pill"
          data-status="live"
          title={tooltipText}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-mono font-medium tracking-wide bg-[#00D9A8]/10 text-[#00D9A8] border border-[#00D9A8]/40 shadow-sm"
        >
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#00D9A8] opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-[#00D9A8]" />
          </span>
          LIVE
        </span>
      )}

      {stateKey === "connecting" && (
        <span
          data-testid="connection-status-pill"
          data-status="connecting"
          title={tooltipText}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-mono font-medium tracking-wide bg-[#FFB800]/10 text-[#FFB800] border border-[#FFB800]/40 shadow-sm"
        >
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#FFB800] opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-[#FFB800]" />
          </span>
          CONNECTING
        </span>
      )}

      {stateKey === "stale" && (
        <span
          data-testid="connection-status-pill"
          data-status="stale"
          title={tooltipText}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-mono font-medium tracking-wide bg-transparent text-[#FFB800] border border-[#FFB800] shadow-sm"
        >
          <span className="inline-flex rounded-full h-2 w-2 bg-[#FFB800]" />
          STALE
        </span>
      )}

      {stateKey === "offline" && (
        <button
          type="button"
          data-testid="connection-status-pill"
          data-status="offline"
          onClick={() => reconnect()}
          title={`${tooltipText} — Click to reconnect`}
          aria-label="Offline: Click to reconnect"
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-mono font-medium tracking-wide bg-[#FF4D6D]/10 text-[#FF4D6D] border border-[#FF4D6D]/40 hover:bg-[#FF4D6D]/20 hover:border-[#FF4D6D]/70 transition-colors cursor-pointer shadow-sm focus:outline-none focus:ring-1 focus:ring-[#FF4D6D]"
        >
          <span className="inline-flex rounded-full h-2 w-2 bg-[#FF4D6D]" />
          OFFLINE
        </button>
      )}

      {/* Floating Tooltip */}
      {showTooltip && (
        <div
          role="tooltip"
          className="absolute top-full mt-1.5 left-1/2 -translate-x-1/2 z-50 whitespace-nowrap px-2.5 py-1 rounded bg-[#0B1020] text-xs font-mono text-text border border-white/10 shadow-lg pointer-events-none"
        >
          {tooltipText}
          {stateKey === "offline" && (
            <span className="block text-[10px] text-muted text-center mt-0.5">Click to reconnect</span>
          )}
        </div>
      )}
    </div>
  );
};
