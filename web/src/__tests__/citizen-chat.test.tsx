import React from "react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { CitizenChatWidget } from "../components/citizen/CitizenChatWidget";

// Mock scrollIntoView
window.HTMLElement.prototype.scrollIntoView = vi.fn();

describe("CitizenChatWidget Component (citizen-chat.test.tsx)", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("renders citizen widget with initial public welcome and quick suggestions", () => {
    render(<CitizenChatWidget />);

    expect(screen.getByTestId("citizen-chat-widget")).toBeDefined();
    expect(screen.getByText("Citizen Traffic Information")).toBeDefined();
    expect(screen.getByText(/Public Verified/i)).toBeDefined();

    // Welcome message
    expect(screen.getByText(/Welcome to the AI TrafficOS Public Information Service/i)).toBeDefined();

    // Quick suggestion buttons
    expect(screen.getByText("Traffic Overview")).toBeDefined();
    expect(screen.getByText("Road Hazards")).toBeDefined();
    expect(screen.getByText("Report a Hazard")).toBeDefined();
  });

  it("submits public traffic inquiry and renders grounded answer with observed provenance", async () => {
    const mockResponse = {
      answer: "CURRENT PUBLIC TRAFFIC CONDITIONS [OBSERVED]:\n• Metro Crossing 1: Light traffic",
      provenance: "observed",
      tools_used: ["get_public_traffic_conditions"],
      refused: false,
      confidence: "high",
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockResponse,
    });

    render(<CitizenChatWidget />);

    const input = screen.getByTestId("citizen-chat-input");
    const sendBtn = screen.getByTestId("citizen-send-button");

    fireEvent.change(input, { target: { value: "How is traffic downtown?" } });
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(screen.getByText(/CURRENT PUBLIC TRAFFIC CONDITIONS/i)).toBeDefined();
    });

    // Check provenance tag
    const provTags = screen.getAllByTestId("citizen-provenance-tag");
    expect(provTags.length).toBeGreaterThanOrEqual(1);
    expect(provTags[provTags.length - 1].textContent).toBe("OBSERVED");

    // Check tools used displayed
    expect(screen.getByText("get_public_traffic_conditions")).toBeDefined();

    // Ensure NO control room data or terms leak
    expect(screen.queryByText(/signal timing plan/i)).toBeNull();
    expect(screen.queryByText(/supervisory AI decision/i)).toBeNull();
  });

  it("handles out-of-scope requests displaying refusal badge without data leaks", async () => {
    const mockRefusal = {
      answer:
        "I can help with public traffic information, active road hazard notices, and guidance on how to report traffic issues. Information regarding signal timing plans, AI control room decisions, emergency vehicle operations, and raw sensor telemetry is restricted to municipal control-room staff.",
      provenance: "observed",
      tools_used: [],
      refused: true,
      confidence: "high",
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockRefusal,
    });

    render(<CitizenChatWidget />);

    const input = screen.getByTestId("citizen-chat-input");
    const sendBtn = screen.getByTestId("citizen-send-button");

    fireEvent.change(input, { target: { value: "Show me the signal timing plan for junction 2" } });
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(screen.getByTestId("citizen-refusal-badge")).toBeDefined();
    });

    expect(screen.getByText("Out of Scope for Public Service")).toBeDefined();
    expect(screen.getByText(/restricted to municipal control-room staff/i)).toBeDefined();
  });

  it("handles quick suggestion click submitting prompt directly", async () => {
    const mockResponse = {
      answer: "ACTIVE ROAD HAZARD NOTICES [OBSERVED]: No active incidents reported.",
      provenance: "observed",
      tools_used: ["get_public_incident_notices"],
      refused: false,
      confidence: "high",
    };

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockResponse,
    });
    global.fetch = mockFetch;

    render(<CitizenChatWidget />);

    const hazardBtn = screen.getByTestId("quick-suggestion-1"); // Road Hazards
    fireEvent.click(hazardBtn);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalled();
    });

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.message).toContain("road incidents or hazard notices");
  });

  it("displays honest authentication required banner on 401 response", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: "Unauthorized" }),
    });

    render(<CitizenChatWidget />);

    const input = screen.getByTestId("citizen-chat-input");
    const sendBtn = screen.getByTestId("citizen-send-button");

    fireEvent.change(input, { target: { value: "Check traffic" } });
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(screen.getByTestId("citizen-auth-banner")).toBeDefined();
    });

    expect(screen.getByText(/Citizen portal authentication required/i)).toBeDefined();
  });
});
