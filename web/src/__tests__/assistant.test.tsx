import React from "react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { AssistantChat } from "../components/assistant/AssistantChat";
import { saveStoredConversation, type ConversationSession } from "../lib/assistant";
import { type UserRole } from "../lib/auth";

// Mock scrollIntoView
window.HTMLElement.prototype.scrollIntoView = vi.fn();

// Mock Auth
let mockUser: { id: number; email: string; role: UserRole } | null = {
  id: 1,
  email: "analyst@trafficos.local",
  role: "analyst",
};
const mockLogout = vi.fn();

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    user: mockUser,
    accessToken: "valid-jwt",
    logout: mockLogout,
    isAdmin: () => mockUser?.role === "admin",
    isOfficer: () => mockUser?.role === "traffic_officer",
    canWrite: () => mockUser?.role === "admin" || mockUser?.role === "traffic_officer",
  }),
}));

describe("AssistantChat Component (assistant.test.tsx)", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    mockUser = { id: 1, email: "analyst@trafficos.local", role: "analyst" };
    mockLogout.mockClear();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("restores conversation history from localStorage and aligns user (right) / assistant (left)", async () => {
    const priorSession: ConversationSession = {
      id: "conv-saved-100",
      title: "Prior Analysis",
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      messages: [
        {
          id: "m-u1",
          role: "user",
          content: "What is the speed on Junction 2?",
          timestamp: new Date().toISOString(),
        },
        {
          id: "m-a1",
          role: "assistant",
          content: "Average speed is 48 km/h.",
          timestamp: new Date().toISOString(),
        },
      ],
    };

    saveStoredConversation(1, priorSession);

    render(<AssistantChat />);

    expect(screen.getByText("What is the speed on Junction 2?")).toBeDefined();
    expect(screen.getByText("Average speed is 48 km/h.")).toBeDefined();

    // Check history alignment
    const userMsg = screen.getByTestId("chat-message-user");
    expect(userMsg.className).toContain("justify-end");

    const asstMsg = screen.getByTestId("chat-message-assistant");
    expect(asstMsg.className).toContain("justify-start");
  });

  it("displays honest loading state ('Thinking…') without fake streaming and disables composer", async () => {
    let resolveFetch: (value: Response) => void;
    const fetchPromise = new Promise<Response>((resolve) => {
      resolveFetch = resolve;
    });

    global.fetch = vi.fn().mockReturnValue(fetchPromise);

    render(<AssistantChat />);

    const textarea = screen.getByTestId("assistant-composer-textarea");
    const sendBtn = screen.getByTestId("assistant-send-button");

    fireEvent.change(textarea, { target: { value: "Check signals status" } });
    fireEvent.click(sendBtn);

    // Honest loading state visible
    expect(screen.getByTestId("assistant-thinking-indicator")).toBeDefined();
    expect(screen.getByText("Thinking…")).toBeDefined();

    // Textarea and button disabled during loading
    expect((textarea as HTMLTextAreaElement).disabled).toBe(true);
    expect((sendBtn as HTMLButtonElement).disabled).toBe(true);

    // Resolve fetch
    await act(async () => {
      resolveFetch!({
        ok: true,
        status: 200,
        json: async () => ({
          answer: "All signals are synchronized.",
          conversation_id: "conv-1",
          tool_calls: [],
          provenance: [],
          insufficient_data: false,
          suggested_followups: [],
        }),
      } as unknown as Response);
    });

    await waitFor(() => {
      expect(screen.queryByTestId("assistant-thinking-indicator")).toBeNull();
      expect(screen.getByText("All signals are synchronized.")).toBeDefined();
      expect((textarea as HTMLTextAreaElement).disabled).toBe(false);
    });
  });

  it("handles 401 error: displays sign-in prompt and triggers logout", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: "Token expired" }),
    } as unknown as Response);

    render(<AssistantChat />);

    const textarea = screen.getByTestId("assistant-composer-textarea");
    const sendBtn = screen.getByTestId("assistant-send-button");

    fireEvent.change(textarea, { target: { value: "Hello" } });
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(screen.getByText("Authentication Required")).toBeDefined();
      expect(screen.getByText("Sign In Again")).toBeDefined();
    });

    fireEvent.click(screen.getByText("Sign In Again"));
    expect(mockLogout).toHaveBeenCalledTimes(1);
  });

  it("handles 403 error: displays permission-restriction panel naming user's role", async () => {
    mockUser = { id: 1, email: "analyst@trafficos.local", role: "analyst" };

    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ detail: "Supervisory overrides restricted" }),
    } as unknown as Response);

    render(<AssistantChat />);

    const textarea = screen.getByTestId("assistant-composer-textarea");
    fireEvent.change(textarea, { target: { value: "Override Signal 12" } });
    fireEvent.click(screen.getByTestId("assistant-send-button"));

    await waitFor(() => {
      expect(screen.getByText("Permission Restricted")).toBeDefined();
      expect(screen.getByText(/Role 'analyst' is not authorized/)).toBeDefined();
    });
  });

  it("handles 500 error state and allows user to retry", async () => {
    let callCount = 0;
    global.fetch = vi.fn().mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        return Promise.resolve({
          ok: false,
          status: 500,
          json: async () => ({ detail: "Internal model backend error" }),
        } as unknown as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          answer: "Success on retry!",
          conversation_id: "conv-1",
          tool_calls: [],
          provenance: [],
          insufficient_data: false,
          suggested_followups: [],
        }),
      } as unknown as Response);
    });

    render(<AssistantChat />);

    const textarea = screen.getByTestId("assistant-composer-textarea");
    fireEvent.change(textarea, { target: { value: "Check volume" } });
    fireEvent.click(screen.getByTestId("assistant-send-button"));

    await waitFor(() => {
      expect(screen.getByText("Service Unavailable")).toBeDefined();
      expect(screen.getByTestId("error-retry-button")).toBeDefined();
    });

    // Click retry
    fireEvent.click(screen.getByTestId("error-retry-button"));

    await waitFor(() => {
      expect(screen.getByText("Success on retry!")).toBeDefined();
    });
  });

  it("renders prominent amber 'Limited data' banner when insufficient_data is true", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        answer: "Junction 9 has partial telemetry only.",
        conversation_id: "conv-1",
        tool_calls: [],
        provenance: [],
        insufficient_data: true,
        suggested_followups: [],
      }),
    } as unknown as Response);

    render(<AssistantChat />);

    const textarea = screen.getByTestId("assistant-composer-textarea");
    fireEvent.change(textarea, { target: { value: "How is Junction 9?" } });
    fireEvent.click(screen.getByTestId("assistant-send-button"));

    await waitFor(() => {
      expect(screen.getByTestId("insufficient-data-banner")).toBeDefined();
      expect(screen.getByText("Limited Data Warning")).toBeDefined();
    });
  });

  it("renders 'AI-generated' badge and System Data panel with Observed/Predicted/Recommended chips and legend", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        answer: "Current density is 32 veh/km; predicted to rise to 65 veh/km.",
        conversation_id: "conv-prov-1",
        tool_calls: [
          { tool: "fetch_density", arguments: { junction: 1 }, result_summary: "32 veh/km" },
        ],
        provenance: [
          { segment: "Current density is 32 veh/km", label: "observed" },
          { segment: "predicted to rise to 65 veh/km", label: "predicted" },
          { segment: "Recommend extending green phase", label: "recommended" },
        ],
        insufficient_data: false,
        suggested_followups: [],
      }),
    } as unknown as Response);

    render(<AssistantChat />);

    const textarea = screen.getByTestId("assistant-composer-textarea");
    fireEvent.change(textarea, { target: { value: "Analyze Corridor A" } });
    fireEvent.click(screen.getByTestId("assistant-send-button"));

    await waitFor(() => {
      // AI-generated badge
      expect(screen.getByTestId("ai-generated-badge")).toBeDefined();
      expect(screen.getByTestId("ai-generated-badge").textContent).toBe("AI-generated");

      // System data panel
      expect(screen.getByTestId("system-data-panel")).toBeDefined();
      expect(screen.getByTestId("provenance-chip-observed")).toBeDefined();
      expect(screen.getByTestId("provenance-chip-predicted")).toBeDefined();
      expect(screen.getByTestId("provenance-chip-recommended")).toBeDefined();

      // Legend
      const legend = screen.getByTestId("provenance-legend");
      expect(legend.textContent).toContain("observed = real DB/telemetry");
      expect(legend.textContent).toContain("predicted = ML forecast");
      expect(legend.textContent).toContain("recommended = AI suggestion not a command");
    });
  });

  it("renders suggested followups as clickable chips that send inquiries when clicked", async () => {
    let requestCount = 0;
    global.fetch = vi.fn().mockImplementation(() => {
      requestCount++;
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          answer: `Response to query ${requestCount}`,
          conversation_id: "conv-followups",
          tool_calls: [],
          provenance: [],
          insufficient_data: false,
          suggested_followups: requestCount === 1 ? ["Tell me more about lane 2"] : [],
        }),
      } as unknown as Response);
    });

    render(<AssistantChat />);

    const textarea = screen.getByTestId("assistant-composer-textarea");
    fireEvent.change(textarea, { target: { value: "Initial query" } });
    fireEvent.click(screen.getByTestId("assistant-send-button"));

    await waitFor(() => {
      expect(screen.getByTestId("suggested-followup-0")).toBeDefined();
      expect(screen.getByTestId("suggested-followup-0").textContent).toBe("Tell me more about lane 2");
    });

    // Click followup chip
    fireEvent.click(screen.getByTestId("suggested-followup-0"));

    await waitFor(() => {
      expect(requestCount).toBe(2);
      expect(screen.getByText("Response to query 2")).toBeDefined();
    });
  });

  it("clears conversation and starts a new one with 'New Conversation' button", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        answer: "Chat 1 answer",
        conversation_id: "conv-1",
        tool_calls: [],
        provenance: [],
        insufficient_data: false,
        suggested_followups: [],
      }),
    } as unknown as Response);

    render(<AssistantChat />);

    const textarea = screen.getByTestId("assistant-composer-textarea");
    fireEvent.change(textarea, { target: { value: "First chat" } });
    fireEvent.click(screen.getByTestId("assistant-send-button"));

    await waitFor(() => {
      expect(screen.getByText("Chat 1 answer")).toBeDefined();
    });

    // Click New Conversation button
    fireEvent.click(screen.getByTestId("new-conversation-button"));

    expect(screen.queryByText("Chat 1 answer")).toBeNull();
    expect(screen.getByText("How can I assist traffic operations?")).toBeDefined();
  });

  it("renders malicious HTML inert without executing script tags", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        answer: "Safe message with <script>window.__PWNED__=true;</script> and <img src=x onerror=steal()>",
        conversation_id: "conv-xss",
        tool_calls: [],
        provenance: [],
        insufficient_data: false,
        suggested_followups: [],
      }),
    } as unknown as Response);

    render(<AssistantChat />);

    const textarea = screen.getByTestId("assistant-composer-textarea");
    fireEvent.change(textarea, { target: { value: "Test XSS" } });
    fireEvent.click(screen.getByTestId("assistant-send-button"));

    await waitFor(() => {
      expect(screen.getByText(/Safe message with/)).toBeDefined();
    });

    // Verify window was not pwned
    expect((window as unknown as { __PWNED__?: boolean }).__PWNED__).toBeUndefined();

    // Verify script element does not exist in DOM
    const scripts = document.querySelectorAll("script");
    const evilScript = Array.from(scripts).find((s) => s.textContent?.includes("__PWNED__"));
    expect(evilScript).toBeUndefined();
  });

  it("renders cancelled requests as a neutral dismissed state (not an alarming error card)", async () => {
    let rejectFetch: (reason?: unknown) => void;
    const fetchPromise = new Promise<Response>((_, reject) => {
      rejectFetch = reject;
    });

    global.fetch = vi.fn().mockReturnValue(fetchPromise);

    render(<AssistantChat />);

    const textarea = screen.getByTestId("assistant-composer-textarea");
    fireEvent.change(textarea, { target: { value: "Check telemetry" } });
    fireEvent.click(screen.getByTestId("assistant-send-button"));

    expect(screen.getByTestId("assistant-thinking-indicator")).toBeDefined();

    // Click cancel button
    fireEvent.click(screen.getByText("Cancel"));

    await waitFor(() => {
      // Thinking indicator should be gone
      expect(screen.queryByTestId("assistant-thinking-indicator")).toBeNull();
      // Neutral dismissed container is rendered
      expect(screen.getByTestId("assistant-cancelled-container")).toBeDefined();
      expect(screen.getByTestId("ai-cancelled-badge")).toBeDefined();
      // NOT a red error container
      expect(screen.queryByTestId("assistant-error-container")).toBeNull();
      expect(screen.queryByText("Request Timed Out")).toBeNull();
    });
  });

  it("displays elapsed generation time after the answer", async () => {
    let fakeTime = 1000;
    vi.spyOn(performance, "now").mockImplementation(() => fakeTime);

    global.fetch = vi.fn().mockImplementation(async () => {
      fakeTime += 1400;
      return {
        ok: true,
        status: 200,
        json: async () => ({
          answer: "Traffic volume is nominal.",
          conversation_id: "conv-elapsed",
          tool_calls: [],
          provenance: [],
          insufficient_data: false,
          suggested_followups: [],
        }),
      } as unknown as Response;
    });

    render(<AssistantChat />);

    const textarea = screen.getByTestId("assistant-composer-textarea");
    fireEvent.change(textarea, { target: { value: "Volume status" } });
    fireEvent.click(screen.getByTestId("assistant-send-button"));

    await waitFor(() => {
      expect(screen.getByText("Traffic volume is nominal.")).toBeDefined();
      expect(screen.getByTestId("assistant-elapsed-time")).toBeDefined();
      expect(screen.getByText("Answered in 1.4s")).toBeDefined();
    });
  });
});
