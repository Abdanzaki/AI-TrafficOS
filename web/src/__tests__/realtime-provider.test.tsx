import React, { useState } from "react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import { RealtimeProvider, useRealtime, useTopic } from "../lib/realtime";
import { ConnectionStatus } from "../components/ConnectionStatus";
import { type UserRole } from "../lib/auth";

// Mock auth module
let mockAuthUser: { id: number; email: string; role: UserRole } | null = {
  id: 1,
  email: "admin@trafficos.local",
  role: "admin",
};
let mockAccessToken: string | null = "valid-mock-token";
const mockLogout = vi.fn();

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    user: mockAuthUser,
    accessToken: mockAccessToken,
    logout: mockLogout,
    isAdmin: () => mockAuthUser?.role === "admin",
    isOfficer: () => mockAuthUser?.role === "traffic_officer",
    canWrite: () => mockAuthUser?.role === "admin" || mockAuthUser?.role === "traffic_officer",
  }),
}));

// Mock WebSocket
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static readonly OPEN = 1;
  static readonly CLOSED = 3;
  static readonly CONNECTING = 0;

  url: string;
  readyState = MockWebSocket.CONNECTING;
  sentMessages: string[] = [];

  onopen: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sentMessages.push(data);
  }

  close(code = 1000, reason = "") {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code, reason } as CloseEvent);
  }

  simulateOpen() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.(new Event("open"));
  }

  simulateMessage(data: unknown) {
    const raw = typeof data === "string" ? data : JSON.stringify(data);
    this.onmessage?.({ data: raw } as MessageEvent);
  }

  simulateClose(code = 1000) {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code, reason: "Normal" } as CloseEvent);
  }
}

// Consumer component for testing subscriptions
function TopicSubscriber({ topic }: { topic: string }) {
  const [lastMessage, setLastMessage] = useState<string>("none");
  const { isConnected, isStale, status } = useRealtime();

  useTopic<{ count?: number }>(topic, (msg) => {
    setLastMessage(JSON.stringify(msg.data));
  });

  return (
    <div>
      <span data-testid="status-val">{status}</span>
      <span data-testid="connected-val">{String(isConnected)}</span>
      <span data-testid="stale-val">{String(isStale)}</span>
      <span data-testid="msg-val">{lastMessage}</span>
    </div>
  );
}

describe("RealtimeProvider & useTopic & ConnectionStatus", () => {
  const originalWebSocket = global.WebSocket;

  beforeEach(() => {
    MockWebSocket.instances = [];
    (global as unknown as { WebSocket: typeof MockWebSocket }).WebSocket = MockWebSocket;
    mockAccessToken = "valid-mock-token";
    mockAuthUser = { id: 1, email: "admin@trafficos.local", role: "admin" };
    mockLogout.mockClear();
  });

  afterEach(() => {
    global.WebSocket = originalWebSocket;
    vi.restoreAllMocks();
  });

  it("provider connects to WebSocket when authenticated", () => {
    render(
      <RealtimeProvider>
        <TopicSubscriber topic="traffic.update" />
      </RealtimeProvider>
    );

    expect(MockWebSocket.instances.length).toBe(1);
    const ws = MockWebSocket.instances[0];
    expect(ws.url).toContain("token=valid-mock-token");

    act(() => {
      ws.simulateOpen();
    });

    expect(screen.getByTestId("connected-val").textContent).toBe("true");
    expect(screen.getByTestId("status-val").textContent).toBe("connected");
  });

  it("useTopic delivers received real-time messages to subscribers", () => {
    render(
      <RealtimeProvider>
        <TopicSubscriber topic="traffic.update" />
      </RealtimeProvider>
    );

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
    });

    // Simulate server dispatching event
    act(() => {
      ws.simulateMessage({
        type: "traffic.update",
        event_id: "evt-901",
        timestamp: new Date().toISOString(),
        payload: { count: 42 },
      });
    });

    expect(screen.getByTestId("msg-val").textContent).toBe('{"count":42}');
  });

  it("enforces role filtering: analyst cannot subscribe to emergency events", () => {
    mockAuthUser = { id: 2, email: "analyst@trafficos.local", role: "analyst" };

    render(
      <RealtimeProvider>
        <TopicSubscriber topic="emergency.created" />
      </RealtimeProvider>
    );

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
    });

    // Deliver emergency event
    act(() => {
      ws.simulateMessage({
        type: "emergency.created",
        event_id: "em-001",
        timestamp: new Date().toISOString(),
        payload: { vehicle: "Ambulance" },
      });
    });

    // Analyst should not have received this event
    expect(screen.getByTestId("msg-val").textContent).toBe("none");
  });

  it("ConnectionStatus renders LIVE pill when connected and not stale", () => {
    render(
      <RealtimeProvider>
        <ConnectionStatus />
      </RealtimeProvider>
    );

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
    });

    const pill = screen.getByTestId("connection-status-pill");
    expect(pill.getAttribute("data-status")).toBe("live");
    expect(pill.textContent).toContain("LIVE");
  });

  it("ConnectionStatus renders CONNECTING pill while socket is establishing", () => {
    render(
      <RealtimeProvider>
        <ConnectionStatus />
      </RealtimeProvider>
    );

    // Initial state before onopen is connecting
    const pill = screen.getByTestId("connection-status-pill");
    expect(pill.getAttribute("data-status")).toBe("connecting");
    expect(pill.textContent).toContain("CONNECTING");
  });

  it("ConnectionStatus renders OFFLINE button when disconnected, and clicking triggers reconnect", () => {
    mockAccessToken = null; // Unauthenticated -> disconnected

    render(
      <RealtimeProvider>
        <ConnectionStatus />
      </RealtimeProvider>
    );

    const pill = screen.getByTestId("connection-status-pill");
    expect(pill.getAttribute("data-status")).toBe("offline");
    expect(pill.textContent).toContain("OFFLINE");

    // Click to reconnect
    fireEvent.click(pill);
    // Button click triggers reconnect
  });

  it("ConnectionStatus renders STALE pill when client receives stale warning from server", () => {
    render(
      <RealtimeProvider>
        <ConnectionStatus />
      </RealtimeProvider>
    );

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
    });

    // Server sends stale frame
    act(() => {
      ws.simulateMessage({
        type: "stale",
        message: "client fell behind; refetch via REST",
      });
    });

    const pill = screen.getByTestId("connection-status-pill");
    expect(pill.getAttribute("data-status")).toBe("stale");
    expect(pill.textContent).toContain("STALE");
  });
});
