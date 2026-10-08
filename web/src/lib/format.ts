/**
 * Number and date formatting helpers for AI TrafficOS.
 */

export function formatNumber(
  val: number | null | undefined,
  decimals: number = 0
): string {
  if (val === null || val === undefined || isNaN(val)) {
    return "—";
  }
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(val);
}

export function formatCompactNumber(val: number | null | undefined): string {
  if (val === null || val === undefined || isNaN(val)) {
    return "—";
  }
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    compactDisplay: "short",
    maximumFractionDigits: 1,
  }).format(val);
}

export function formatPercent(
  val: number | null | undefined,
  decimals: number = 1
): string {
  if (val === null || val === undefined || isNaN(val)) {
    return "—";
  }
  return `${formatNumber(val, decimals)}%`;
}

export function formatSpeed(val: number | null | undefined): string {
  if (val === null || val === undefined || isNaN(val)) {
    return "—";
  }
  return `${formatNumber(val, 1)} km/h`;
}

export function formatSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || isNaN(seconds)) {
    return "—";
  }
  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  }
  const mins = Math.floor(seconds / 60);
  const remainingSecs = Math.round(seconds % 60);
  return remainingSecs > 0 ? `${mins}m ${remainingSecs}s` : `${mins}m`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || isNaN(seconds)) {
    return "—";
  }
  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  }
  const mins = Math.floor(seconds / 60);
  const remSecs = Math.round(seconds % 60);
  if (mins < 60) {
    return remSecs > 0 ? `${mins}m ${remSecs}s` : `${mins}m`;
  }
  const hours = Math.floor(mins / 60);
  const remMins = mins % 60;
  return remMins > 0 ? `${hours}h ${remMins}m` : `${hours}h`;
}

export function formatQueueLength(val: number | null | undefined): string {
  if (val === null || val === undefined || isNaN(val)) {
    return "—";
  }
  return `${formatNumber(val, 1)} veh`;
}

export function formatDateTime(
  dateVal: string | Date | null | undefined
): string {
  if (!dateVal) return "—";
  const date = typeof dateVal === "string" ? new Date(dateVal) : dateVal;
  if (isNaN(date.getTime())) return "—";

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatDate(
  dateVal: string | Date | null | undefined
): string {
  if (!dateVal) return "—";
  const date = typeof dateVal === "string" ? new Date(dateVal) : dateVal;
  if (isNaN(date.getTime())) return "—";

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

export function formatTime(
  dateVal: string | Date | null | undefined
): string {
  if (!dateVal) return "—";
  const date = typeof dateVal === "string" ? new Date(dateVal) : dateVal;
  if (isNaN(date.getTime())) return "—";

  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatRelativeTime(
  dateVal: string | Date | null | undefined
): string {
  if (!dateVal) return "—";
  const date = typeof dateVal === "string" ? new Date(dateVal) : dateVal;
  if (isNaN(date.getTime())) return "—";

  const diffSec = Math.floor((Date.now() - date.getTime()) / 1000);
  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour}h ago`;
  const diffDay = Math.floor(diffHour / 24);
  return `${diffDay}d ago`;
}

export interface CongestionStatus {
  level: "low" | "medium" | "high";
  label: string;
  colorClass: string;
  bgClass: string;
  hex: string;
  badgeVariant: "teal" | "amber" | "danger";
}

export function getCongestionStatus(percent: number | null | undefined): CongestionStatus {
  if (percent === null || percent === undefined || isNaN(percent) || percent < 40) {
    return {
      level: "low",
      label: "Smooth",
      colorClass: "text-accent",
      bgClass: "bg-accent/15 border-accent/30",
      hex: "#00D9A8",
      badgeVariant: "teal",
    };
  }
  if (percent < 70) {
    return {
      level: "medium",
      label: "Moderate",
      colorClass: "text-amber",
      bgClass: "bg-amber/15 border-amber/30",
      hex: "#FFB800",
      badgeVariant: "amber",
    };
  }
  return {
    level: "high",
    label: "Congested",
    colorClass: "text-danger",
    bgClass: "bg-danger/15 border-danger/30",
    hex: "#FF4D6D",
    badgeVariant: "danger",
  };
}

export function getSeverityBadgeVariant(
  severity: string | null | undefined
): "teal" | "amber" | "danger" | "muted" {
  switch (severity?.toLowerCase()) {
    case "critical":
    case "high":
      return "danger";
    case "medium":
      return "amber";
    case "low":
      return "teal";
    default:
      return "muted";
  }
}
