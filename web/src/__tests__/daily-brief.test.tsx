import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DailyBriefCard, type DailyBriefData } from "@/components/DailyBriefCard";

let mockQueryReturn: any = null;

vi.mock("@/lib/use-api", () => ({
  useApiQuery: () => mockQueryReturn,
}));

const mockFullBrief: DailyBriefData = {
  generated_at: "2026-10-13T06:00:00Z",
  date: "2026-10-12",
  summary_text: "# Daily Traffic Operations Brief — 2026-10-12\n\n- **Total Incidents:** 3\n- **Total Violations:** 5",
  rephrased: false,
  incidents: {
    provenance: "observed",
    has_data: true,
    count: 3,
    total: 3,
    by_severity: { critical: 1, high: 2 },
    by_type: { critical: 1, high: 2 },
    note: null,
  },
  violations: {
    provenance: "observed",
    has_data: true,
    count: 5,
    total: 5,
    by_type: { red_light: 3, wrong_way: 2 },
    note: null,
  },
  hotspots: {
    provenance: "predicted",
    has_data: true,
    items: [
      {
        intersection_id: 10,
        intersection_name: "Cyber Towers Junction",
        intersection_code: "CYB-01",
        predicted_congestion: 88.5,
        predicted_flow: 420.0,
        confidence: 0.91,
        predicted_for: "2026-10-13T09:00:00Z",
      },
    ],
    note: null,
  },
  trends: {
    provenance: "observed",
    has_sufficient_history: true,
    incident_delta: 1,
    violation_delta: -2,
    direction: "increased",
    note: "Day-over-day changes: +1 incidents, -2 violations compared to prior day.",
  },
};

const mockEmptyBrief: DailyBriefData = {
  generated_at: "2026-10-13T06:00:00Z",
  date: "2026-10-12",
  summary_text: "# Daily Traffic Operations Brief — 2026-10-12\n\nNo data recorded.",
  rephrased: false,
  incidents: {
    provenance: "observed",
    has_data: false,
    count: null,
    total: null,
    by_severity: {},
    by_type: {},
    note: "No incident data recorded for yesterday.",
  },
  violations: {
    provenance: "observed",
    has_data: false,
    count: null,
    total: null,
    by_type: {},
    note: "No violation records found for yesterday.",
  },
  hotspots: {
    provenance: "predicted",
    has_data: false,
    items: [],
    note: "No forward hotspot predictions available for today.",
  },
  trends: {
    provenance: "observed",
    has_sufficient_history: false,
    incident_delta: null,
    violation_delta: null,
    direction: null,
    note: "Insufficient history (<2 days of data) to compute day-over-day trends.",
  },
};

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("DailyBriefCard Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading state cleanly while fetching", () => {
    mockQueryReturn = {
      data: null,
      isLoading: true,
      isFetching: true,
      error: null,
      refetch: vi.fn(),
    };

    renderWithClient(<DailyBriefCard />);
    expect(screen.getByText("Daily Traffic Operations Brief")).toBeInTheDocument();
    expect(screen.getByText(/Aggregating morning telemetry/i)).toBeInTheDocument();
  });

  it("renders full populated daily brief with observed counts and provenance labels", () => {
    mockQueryReturn = {
      data: mockFullBrief,
      isLoading: false,
      isFetching: false,
      error: null,
      refetch: vi.fn(),
    };

    renderWithClient(<DailyBriefCard />);

    // Header metadata
    expect(screen.getByText(/Target: 2026-10-12/)).toBeInTheDocument();
    expect(screen.getByText(/Generated:/)).toBeInTheDocument();

    // Section 1: Incidents
    expect(screen.getByText("Observed Incidents")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("critical: 1")).toBeInTheDocument();
    expect(screen.getByText("high: 2")).toBeInTheDocument();

    // Section 2: Violations
    expect(screen.getByText("Observed Violations")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("red light: 3")).toBeInTheDocument();
    expect(screen.getByText("wrong way: 2")).toBeInTheDocument();

    // Section 3: Hotspots
    expect(screen.getByText("Forecasted Hotspots")).toBeInTheDocument();
    expect(screen.getByText("Cyber Towers Junction")).toBeInTheDocument();
    expect(screen.getByText("89%")).toBeInTheDocument();

    // Section 4: Trends
    expect(screen.getByText("Day-over-Day Trends")).toBeInTheDocument();
    expect(screen.getByText("+1")).toBeInTheDocument();
    expect(screen.getByText("-2")).toBeInTheDocument();

    // Toggle narrative
    const narrativeToggle = screen.getByText("View Grounded Brief Narrative");
    fireEvent.click(narrativeToggle);
    expect(screen.getByText("Hide Grounded Brief Narrative")).toBeInTheDocument();
  });

  it("renders honest 'no data' empty states without fabricated zero measurements", () => {
    mockQueryReturn = {
      data: mockEmptyBrief,
      isLoading: false,
      isFetching: false,
      error: null,
      refetch: vi.fn(),
    };

    renderWithClient(<DailyBriefCard />);

    // Explicit empty state notes
    expect(screen.getByText("No incident data recorded for yesterday.")).toBeInTheDocument();
    expect(screen.getByText("No violation records found for yesterday.")).toBeInTheDocument();
    expect(screen.getByText("No forward hotspot predictions available for today.")).toBeInTheDocument();
    expect(screen.getByText(/Insufficient history/i)).toBeInTheDocument();

    // Asserts no fake numbers presented
    expect(screen.queryByText(/^0$/)).not.toBeInTheDocument();
  });

  it("handles conversational rephrase toggle cleanly", () => {
    mockQueryReturn = {
      data: { ...mockFullBrief, rephrased: true },
      isLoading: false,
      isFetching: false,
      error: null,
      refetch: vi.fn(),
    };

    renderWithClient(<DailyBriefCard />);
    expect(screen.getByText("Gemini Rephrased")).toBeInTheDocument();

    const rephraseBtn = screen.getByTitle(/Toggle grounded conversational rendering/i);
    expect(rephraseBtn).toBeInTheDocument();
    fireEvent.click(rephraseBtn);
  });
});
