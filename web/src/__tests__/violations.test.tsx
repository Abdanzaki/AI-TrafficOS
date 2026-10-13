import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ViolationsList, type ViolationItem } from "@/components/violations/ViolationsList";

// Mock Auth
const mockCanWrite = vi.fn().mockReturnValue(true);
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    user: { id: 1, email: "officer@trafficos.local", role: "traffic_officer" },
    canWrite: mockCanWrite,
    isAdmin: () => false,
    isOfficer: () => true,
  }),
}));

// Mock use-api hooks
let mockViolationsReturn: any = null;
let mockJunctionsReturn: any = null;
const mockMutate = vi.fn();

vi.mock("@/lib/use-api", () => ({
  useApiQuery: ({ endpoint }: { endpoint: string }) => {
    if (endpoint === "/junctions") {
      return mockJunctionsReturn;
    }
    if (endpoint === "/violations") {
      return mockViolationsReturn;
    }
    return { data: null, isLoading: false, isError: false, error: null, refetch: vi.fn(), isFetching: false };
  },
  useApiMutation: () => ({
    mutate: mockMutate,
    mutateAsync: vi.fn().mockResolvedValue({}),
    isPending: false,
    error: null,
  }),
}));

const mockViolations: ViolationItem[] = [
  {
    id: 1,
    violation_type: "red_light",
    detected_at: "2026-10-13T10:15:00Z",
    intersection_id: 1,
    camera_id: "CAM-NORTH-01",
    confidence: 0.94,
    status: "recorded",
    evidence_ref: "/evidence/violations/red_light_001.jpg",
    details: {
      lane_id: "lane_1",
      speed_kmh: 52.4,
      crossing_point: [240.5, 410.2],
    },
    created_at: "2026-10-13T10:15:00Z",
    updated_at: "2026-10-13T10:15:00Z",
  },
  {
    id: 2,
    violation_type: "wrong_way",
    detected_at: "2026-10-13T10:20:00Z",
    intersection_id: 1,
    camera_id: "CAM-WEST-02",
    confidence: 0.88,
    status: "reviewed",
    evidence_ref: null,
    details: {
      lane_id: "lane_3",
      angle_diff_deg: 175.2,
    },
    created_at: "2026-10-13T10:20:00Z",
    updated_at: "2026-10-13T10:20:00Z",
  },
  {
    id: 3,
    violation_type: "no_helmet",
    detected_at: "2026-10-13T10:25:00Z",
    intersection_id: 2,
    camera_id: "CAM-EAST-01",
    confidence: 0.82,
    status: "escalated",
    evidence_ref: "/evidence/violations/no_helmet_003.jpg",
    details: {
      rider_association_score: 0.85,
      helmet_classifier_confidence: 0.91,
    },
    created_at: "2026-10-13T10:25:00Z",
    updated_at: "2026-10-13T10:25:00Z",
  },
];

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("ViolationsList Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCanWrite.mockReturnValue(true);

    mockJunctionsReturn = {
      data: {
        items: [
          { id: 1, name: "Market & 4th", code: "J-01" },
          { id: 2, name: "Mission & 16th", code: "J-02" },
        ],
        total: 2,
        page: 1,
        per_page: 100,
        pages: 1,
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    };

    mockViolationsReturn = {
      data: {
        items: mockViolations,
        total: 3,
        page: 1,
        per_page: 15,
        pages: 1,
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    };
  });

  it("renders violations table with mock rows", () => {
    renderWithClient(<ViolationsList />);

    // Assert top disclaimer and table header
    expect(screen.getByText("Batch 2 Perception")).toBeInTheDocument();
    expect(screen.getByText("Violation ID")).toBeInTheDocument();

    // Assert rows
    const row1 = screen.getByTestId("violation-row-1");
    const row2 = screen.getByTestId("violation-row-2");
    const row3 = screen.getByTestId("violation-row-3");
    expect(row1).toBeInTheDocument();
    expect(row2).toBeInTheDocument();
    expect(row3).toBeInTheDocument();

    // Assert violation types rendered in rows
    expect(within(row1).getByText("Red Light Runner")).toBeInTheDocument();
    expect(within(row2).getByText("Wrong-Way Driving")).toBeInTheDocument();
    expect(within(row3).getByText("No Helmet Rider")).toBeInTheDocument();

    // Assert junction names and confidence percentages in rows
    expect(within(row1).getByText("Market & 4th")).toBeInTheDocument();
    expect(within(row1).getByText("94%")).toBeInTheDocument();
    expect(within(row2).getByText("88%")).toBeInTheDocument();
    expect(within(row3).getByText("82%")).toBeInTheDocument();
  });

  it("opens details modal when a violation row is inspected", () => {
    renderWithClient(<ViolationsList />);

    // Click details button for violation 1
    const viewButtons = screen.getAllByTitle("View Details");
    fireEvent.click(viewButtons[0]);

    // Modal should show CV diagnostic telemetry
    expect(screen.getByText("CV Diagnostic Telemetry")).toBeInTheDocument();
    expect(screen.getByText(/lane_1/)).toBeInTheDocument();
    expect(screen.getByText(/speed_kmh/)).toBeInTheDocument();
  });

  it("renders loading state spinner when isLoading is true", () => {
    mockViolationsReturn = {
      data: null,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: true,
    };

    renderWithClient(<ViolationsList />);
    expect(screen.getByLabelText("Loading traffic violations...")).toBeInTheDocument();
  });

  it("renders empty state when no violations exist", () => {
    mockViolationsReturn = {
      data: {
        items: [],
        total: 0,
        page: 1,
        per_page: 15,
        pages: 1,
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    };

    renderWithClient(<ViolationsList />);
    expect(screen.getByText("No Traffic Violations Found")).toBeInTheDocument();
  });

  it("calls mutate when Review action is triggered on a recorded violation", () => {
    renderWithClient(<ViolationsList />);

    // First violation (#1) is "recorded", so it has a Review button
    const reviewButton = screen.getByRole("button", { name: "Review" });
    fireEvent.click(reviewButton);

    expect(mockMutate).toHaveBeenCalledWith({
      id: 1,
      data: { status: "reviewed" },
    });
  });
});
