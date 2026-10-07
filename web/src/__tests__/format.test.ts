import { describe, it, expect } from "vitest";
import {
  formatNumber,
  formatCompactNumber,
  formatPercent,
  formatSpeed,
  formatSeconds,
  formatDuration,
  formatQueueLength,
  formatDateTime,
  formatDate,
  formatTime,
  formatRelativeTime,
  getCongestionStatus,
  getSeverityBadgeVariant,
} from "@/lib/format";

describe("format helpers", () => {
  describe("formatNumber", () => {
    it("handles null, undefined and NaN", () => {
      expect(formatNumber(null)).toBe("—");
      expect(formatNumber(undefined)).toBe("—");
      expect(formatNumber(NaN)).toBe("—");
    });

    it("formats integers and decimals correctly", () => {
      expect(formatNumber(1234)).toBe("1,234");
      expect(formatNumber(1234.567, 2)).toBe("1,234.57");
      expect(formatNumber(0, 0)).toBe("0");
      expect(formatNumber(42.1, 2)).toBe("42.10");
    });
  });

  describe("formatCompactNumber", () => {
    it("handles null, undefined and NaN", () => {
      expect(formatCompactNumber(null)).toBe("—");
      expect(formatCompactNumber(undefined)).toBe("—");
      expect(formatCompactNumber(NaN)).toBe("—");
    });

    it("formats compact numbers", () => {
      expect(formatCompactNumber(500)).toBe("500");
      expect(formatCompactNumber(1500)).toBe("1.5K");
      expect(formatCompactNumber(2500000)).toBe("2.5M");
    });
  });

  describe("formatPercent", () => {
    it("handles invalid inputs", () => {
      expect(formatPercent(null)).toBe("—");
      expect(formatPercent(undefined)).toBe("—");
      expect(formatPercent(NaN)).toBe("—");
    });

    it("formats percentages with specified decimals", () => {
      expect(formatPercent(75.45, 1)).toBe("75.5%");
      expect(formatPercent(100, 0)).toBe("100%");
      expect(formatPercent(0, 1)).toBe("0.0%");
    });
  });

  describe("formatSpeed", () => {
    it("handles invalid inputs", () => {
      expect(formatSpeed(null)).toBe("—");
      expect(formatSpeed(undefined)).toBe("—");
    });

    it("formats speed with km/h unit", () => {
      expect(formatSpeed(45.67)).toBe("45.7 km/h");
      expect(formatSpeed(0)).toBe("0.0 km/h");
    });
  });

  describe("formatSeconds", () => {
    it("handles invalid inputs", () => {
      expect(formatSeconds(null)).toBe("—");
      expect(formatSeconds(undefined)).toBe("—");
      expect(formatSeconds(NaN)).toBe("—");
    });

    it("formats seconds under 1 minute", () => {
      expect(formatSeconds(45)).toBe("45s");
      expect(formatSeconds(12.4)).toBe("12s");
    });

    it("formats minutes and remaining seconds", () => {
      expect(formatSeconds(60)).toBe("1m");
      expect(formatSeconds(125)).toBe("2m 5s");
      expect(formatSeconds(180)).toBe("3m");
    });
  });

  describe("formatDuration", () => {
    it("handles invalid inputs", () => {
      expect(formatDuration(null)).toBe("—");
      expect(formatDuration(undefined)).toBe("—");
      expect(formatDuration(NaN)).toBe("—");
    });

    it("formats seconds, minutes, and hours", () => {
      expect(formatDuration(30)).toBe("30s");
      expect(formatDuration(150)).toBe("2m 30s");
      expect(formatDuration(3600)).toBe("1h");
      expect(formatDuration(3660)).toBe("1h 1m");
      expect(formatDuration(7200)).toBe("2h");
    });
  });

  describe("formatQueueLength", () => {
    it("handles invalid inputs", () => {
      expect(formatQueueLength(null)).toBe("—");
      expect(formatQueueLength(undefined)).toBe("—");
    });

    it("formats queue length with veh suffix", () => {
      expect(formatQueueLength(12.34)).toBe("12.3 veh");
      expect(formatQueueLength(0)).toBe("0.0 veh");
    });
  });

  describe("date & time formatting", () => {
    const testDate = "2026-10-07T14:30:45Z";

    it("formatDateTime formats valid date string and Date object", () => {
      expect(formatDateTime(null)).toBe("—");
      expect(formatDateTime("invalid-date")).toBe("—");
      expect(formatDateTime(testDate)).toContain("Oct");
      expect(formatDateTime(new Date(testDate))).toContain("Oct");
    });

    it("formatDate formats date only", () => {
      expect(formatDate(null)).toBe("—");
      expect(formatDate("invalid-date")).toBe("—");
      const formatted = formatDate(testDate);
      expect(formatted).toContain("Oct");
      expect(formatted).toContain("2026");
    });

    it("formatTime formats time only", () => {
      expect(formatTime(null)).toBe("—");
      expect(formatTime("invalid-date")).toBe("—");
      expect(formatTime(testDate)).toMatch(/\d{2}:\d{2}/);
    });

    it("formatRelativeTime formats relative differences", () => {
      expect(formatRelativeTime(null)).toBe("—");
      expect(formatRelativeTime("invalid-date")).toBe("—");

      const now = Date.now();
      expect(formatRelativeTime(new Date(now - 2000))).toBe("just now");
      expect(formatRelativeTime(new Date(now - 30 * 1000))).toBe("30s ago");
      expect(formatRelativeTime(new Date(now - 5 * 60 * 1000))).toBe("5m ago");
      expect(formatRelativeTime(new Date(now - 3 * 3600 * 1000))).toBe("3h ago");
      expect(formatRelativeTime(new Date(now - 2 * 24 * 3600 * 1000))).toBe("2d ago");
    });
  });

  describe("getCongestionStatus", () => {
    it("returns low/smooth status for < 40 or null/undefined", () => {
      expect(getCongestionStatus(null).level).toBe("low");
      expect(getCongestionStatus(undefined).level).toBe("low");
      expect(getCongestionStatus(NaN).level).toBe("low");
      expect(getCongestionStatus(20).level).toBe("low");
      expect(getCongestionStatus(20).label).toBe("Smooth");
      expect(getCongestionStatus(20).badgeVariant).toBe("teal");
    });

    it("returns medium/moderate status for 40-69", () => {
      const status = getCongestionStatus(55);
      expect(status.level).toBe("medium");
      expect(status.label).toBe("Moderate");
      expect(status.badgeVariant).toBe("amber");
    });

    it("returns high/congested status for >= 70", () => {
      const status = getCongestionStatus(85);
      expect(status.level).toBe("high");
      expect(status.label).toBe("Congested");
      expect(status.badgeVariant).toBe("danger");
    });
  });

  describe("getSeverityBadgeVariant", () => {
    it("maps severity levels to correct badge variants", () => {
      expect(getSeverityBadgeVariant("critical")).toBe("danger");
      expect(getSeverityBadgeVariant("high")).toBe("danger");
      expect(getSeverityBadgeVariant("medium")).toBe("amber");
      expect(getSeverityBadgeVariant("low")).toBe("teal");
      expect(getSeverityBadgeVariant("unknown")).toBe("muted");
      expect(getSeverityBadgeVariant(null)).toBe("muted");
      expect(getSeverityBadgeVariant(undefined)).toBe("muted");
    });
  });
});
