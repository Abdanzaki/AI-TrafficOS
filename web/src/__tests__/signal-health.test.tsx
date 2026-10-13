import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  SignalHealthPanel,
  type SignalHealthListResponse,
} from "@/components/SignalHealthPanel";

let mockQueryReturn: any = null;

vi.mock("@/lib/use-api", () => ({
  useApiQuery: () => mockQueryReturn,
}));

const mockHealthySignals: SignalHealthListResponse = {
  items: [
    {
      signal_id: 1,
      signal_code: "SIG-101",
      intersection_id: 1,
      score: 95,
      status_band: "healthy",
      explanation: "Signal SIG-101 evaluated as 'healthy' with score 95/100. Telemetry and cadence nominal.",
      factors: [
        {
          name: "controller_status",
          weight: 0.35,
          raw_value: "active",
          penalty: 0,
          status: "normal",
          description: "Controller hardware reports normal operating status ('active').",
        },
        {
          name: "phase_flapping",
          weight: 0.25,
          raw_value: { rapid_switches: 0, total_switches: 12 },
          penalty: 0,
          status: "normal",
          description: "Phase switching cadence is stable; no rapid flapping.",
        },
        {
          name: "heartbeat_staleness",
          weight: 0.20,
          raw_value: 14.5,
          penalty: 0,
          status: "normal",
          description: "Telemetry heartbeat is fresh (14s ago).",
        },
        {
          name: "anomalous_dwell",
          weight: 0.20,
          raw_value: { anomalous_count: 0, expected_dwell_s: 30 },
          penalty: 0,
          status: "normal",
          description: "Dwell times are consistent with planned phase timing intervals.",
        },
      ],
      provenance: "heuristic",
      evaluated_at: "2026-10-13T12:00:00Z",
    },
    {
      signal_id: 2,
      signal_code: "SIG-202",
      intersection_id: 2,
      score: 42,
      status_band: "at-risk",
      explanation: "Signal SIG-202 evaluated as 'at-risk' with predictive-maintenance score 42/100. Deductions: Phase-flapping detected: 5 rapid transitions.",
      factors: [
        {
          name: "controller_status",
          weight: 0.35,
          raw_value: "active",
          penalty: 0,
          status: "normal",
          description: "Controller hardware active.",
        },
        {
          name: "phase_flapping",
          weight: 0.25,
          raw_value: { rapid_switches: 5, total_switches: 14 },
          penalty: 35,
          status: "critical",
          description: "Phase-flapping detected: 5 rapid transitions (<5s interval).",
        },
        {
          name: "heartbeat_staleness",
          weight: 0.20,
          raw_value: 360,
          penalty: 20,
          status: "warning",
          description: "Stale telemetry: last update was 6 minutes ago.",
        },
        {
          name: "anomalous_dwell",
          weight: 0.20,
          raw_value: { anomalous_count: 0, expected_dwell_s: 30 },
          penalty: 0,
          status: "normal",
          description: "Dwell times nominal.",
        },
      ],
      provenance: "heuristic",
      evaluated_at: "2026-10-13T12:00:00Z",
    },
  ],
  total: 2,
  healthy_count: 1,
  degraded_count: 0,
  at_risk_count: 1,
  provenance: "heuristic",
};

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("SignalHealthPanel Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading spinner while query is in progress", () => {
    mockQueryReturn = {
      data: null,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    };

    renderWithClient(<SignalHealthPanel />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getAllByText("Evaluating signal telemetry health scores...").length).toBeGreaterThanOrEqual(1);
  });

  it("renders error state when backend query fails", () => {
    mockQueryReturn = {
      data: null,
      isLoading: false,
      isError: true,
      error: new Error("Network timeout"),
      refetch: vi.fn(),
      isFetching: false,
    };

    renderWithClient(<SignalHealthPanel />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Failed to Load Signal Health")).toBeInTheDocument();
  });

  it("renders empty state when no signals are recorded", () => {
    mockQueryReturn = {
      data: { items: [], total: 0, healthy_count: 0, degraded_count: 0, at_risk_count: 0, provenance: "heuristic" },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    };

    renderWithClient(<SignalHealthPanel />);
    expect(screen.getByText("No Signal Hardware Monitored")).toBeInTheDocument();
  });

  it("renders signal cards with score badges, status bands, and honest provenance", () => {
    mockQueryReturn = {
      data: mockHealthySignals,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    };

    renderWithClient(<SignalHealthPanel />);

    // Provenance badge
    expect(screen.getByText("Heuristic Model")).toBeInTheDocument();

    // Signal codes
    expect(screen.getByText("SIG-101")).toBeInTheDocument();
    expect(screen.getByText("SIG-202")).toBeInTheDocument();

    // Health scores
    expect(screen.getByText("95 / 100")).toBeInTheDocument();
    expect(screen.getByText("42 / 100")).toBeInTheDocument();

    // Status bands
    expect(screen.getByText("healthy")).toBeInTheDocument();
    expect(screen.getByText("at-risk")).toBeInTheDocument();

    // Counts summary
    expect(screen.getByText("1 Healthy")).toBeInTheDocument();
    expect(screen.getByText("1 At-Risk")).toBeInTheDocument();
  });

  it("expands and collapses factor details when View Factors is clicked", () => {
    mockQueryReturn = {
      data: mockHealthySignals,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    };

    renderWithClient(<SignalHealthPanel />);

    // Initially factor breakdown is hidden
    expect(screen.queryByText("Contributing Risk Factors & Weights")).not.toBeInTheDocument();

    // Click "View Factors" on the second (at-risk) signal
    const viewButtons = screen.getAllByRole("button", { name: /factor breakdown/i });
    fireEvent.click(viewButtons[1]);

    // Should expand factor breakdown
    expect(screen.getByText("Contributing Risk Factors & Weights")).toBeInTheDocument();
    expect(screen.getByText("Phase-Flapping Cadence")).toBeInTheDocument();
    expect(screen.getByText("-35 pts")).toBeInTheDocument();
    expect(screen.getByText("Weight: 25%")).toBeInTheDocument();
    expect(screen.getByText("Provenance: heuristic")).toBeInTheDocument();

    // Click to collapse
    const hideButtons = screen.getAllByRole("button", { name: /factor breakdown/i });
    fireEvent.click(hideButtons[1]);

    expect(screen.queryByText("Contributing Risk Factors & Weights")).not.toBeInTheDocument();
  });
});
