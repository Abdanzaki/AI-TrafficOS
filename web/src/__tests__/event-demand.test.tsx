import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  EventDemandForecast,
  type EventDemandResponse,
} from "@/components/EventDemandForecast";

let mockJunctionsReturn: any = null;
const mockMutate = vi.fn();
let mockMutationState: any = {
  data: null,
  isPending: false,
  isError: false,
  error: null,
};

vi.mock("@/lib/use-api", () => ({
  useApiQuery: () => mockJunctionsReturn,
  useApiMutation: () => ({
    mutate: mockMutate,
    mutateAsync: vi.fn(),
    data: mockMutationState.data,
    isPending: mockMutationState.isPending,
    isError: mockMutationState.isError,
    error: mockMutationState.error,
  }),
}));

const mockForecastResult: EventDemandResponse = {
  event_name: "Premier League Derby",
  starts_at: "2026-10-15T18:00:00Z",
  expected_attendance: 20000,
  provenance: "parametric-heuristic",
  model_type: "parametric-heuristic",
  documentation: "Parametric heuristic model estimating additional peak vehicular arrivals.",
  total_peak_vehicles: {
    low: 2333,
    base: 5000,
    high: 9750,
  },
  assumptions: [
    {
      parameter: "mode_share",
      description: "Proportion of attendees traveling via private vehicle",
      range_or_value: "Low: 35%, Base: 50%, High: 65%",
      low: 0.35,
      base: 0.50,
      high: 0.65,
      formula: "attendance * mode_share",
    },
    {
      parameter: "vehicle_occupancy",
      description: "Average vehicle occupancy rate",
      range_or_value: "Low: 1.8, Base: 1.5, High: 1.2",
      low: 1.8,
      base: 1.5,
      high: 1.2,
      formula: "vehicles / occupancy",
    },
  ],
  junctions: [
    {
      junction_id: 1,
      junction_name: "Stadium Gateway Junction",
      junction_code: "STAD-01",
      distance_km: 0.0,
      spatial_weight: 0.75,
      baseline_flow: 180.0,
      baseline_status: "observed",
      baseline_note: null,
      scenarios: {
        low: {
          uplift_vehicles: 1750,
          projected_total_flow: 1930.0,
          uplift_percentage: 972.2,
        },
        base: {
          uplift_vehicles: 3750,
          projected_total_flow: 3930.0,
          uplift_percentage: 2083.3,
        },
        high: {
          uplift_vehicles: 7313,
          projected_total_flow: 7493.0,
          uplift_percentage: 4062.8,
        },
      },
      confidence_interval: [1750, 7313],
    },
    {
      junction_id: 2,
      junction_name: "Unmonitored Arterial Junction",
      junction_code: "ART-99",
      distance_km: 1.45,
      spatial_weight: 0.25,
      baseline_flow: null,
      baseline_status: "no_baseline_data",
      baseline_note: "No historical telemetry observations recorded for junction 2.",
      scenarios: {
        low: {
          uplift_vehicles: 583,
          projected_total_flow: null,
          uplift_percentage: null,
        },
        base: {
          uplift_vehicles: 1250,
          projected_total_flow: null,
          uplift_percentage: null,
        },
        high: {
          uplift_vehicles: 2438,
          projected_total_flow: null,
          uplift_percentage: null,
        },
      },
      confidence_interval: [583, 2438],
    },
  ],
};

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("EventDemandForecast Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockJunctionsReturn = {
      data: {
        items: [
          { id: 1, name: "Stadium Gateway Junction", code: "STAD-01" },
          { id: 2, name: "Unmonitored Arterial Junction", code: "ART-99" },
        ],
        total: 2,
      },
      isLoading: false,
    };
    mockMutationState = {
      data: null,
      isPending: false,
      isError: false,
      error: null,
    };
  });

  it("renders form controls properly", () => {
    renderWithClient(<EventDemandForecast />);

    expect(screen.getByText("Event Traffic Demand Forecasting")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("e.g. City Marathon")).toBeInTheDocument();
    expect(screen.getByText("Select junction...")).toBeInTheDocument();
    expect(screen.getByText("Forecast Demand Uplift")).toBeInTheDocument();
  });

  it("validates form inputs on submission", () => {
    renderWithClient(<EventDemandForecast />);

    // Attempt submit without selecting junction
    const submitBtn = screen.getByText("Forecast Demand Uplift");
    fireEvent.click(submitBtn);

    expect(screen.getByText("Please select a target physical junction.")).toBeInTheDocument();
    expect(mockMutate).not.toHaveBeenCalled();
  });

  it("renders forecast results with scenarios, confidence interval, and assumptions", () => {
    mockMutationState.data = mockForecastResult;

    renderWithClient(<EventDemandForecast />);

    // Provenance badge
    expect(screen.getByText("parametric-heuristic")).toBeInTheDocument();
    expect(screen.getByText(/Premier League Derby — Demand Uplift Projection/i)).toBeInTheDocument();

    // Total peak vehicles
    expect(screen.getByText("+2,333")).toBeInTheDocument();
    expect(screen.getByText("+5,000")).toBeInTheDocument();
    expect(screen.getByText("+9,750")).toBeInTheDocument();

    // Junction 1 with real observed baseline
    expect(screen.getByText("#1 — Stadium Gateway Junction")).toBeInTheDocument();
    expect(screen.getByText("Observed Baseline: 180 veh/hr")).toBeInTheDocument();
    expect(screen.getByText("+3,750 veh")).toBeInTheDocument();
    expect(screen.getByText(/\[1,750 — 7,313 additional peak vehicles\]/)).toBeInTheDocument();

    // Junction 2 with empty baseline handling
    expect(screen.getByText("#2 — Unmonitored Arterial Junction")).toBeInTheDocument();
    expect(screen.getByText("No Baseline Telemetry")).toBeInTheDocument();
    expect(screen.getByText(/No historical telemetry observations recorded/i)).toBeInTheDocument();

    // Assumptions Table
    expect(screen.getByText("mode_share")).toBeInTheDocument();
    expect(screen.getByText("vehicle_occupancy")).toBeInTheDocument();
    expect(screen.getByText("Low: 35%, Base: 50%, High: 65%")).toBeInTheDocument();
  });
});
