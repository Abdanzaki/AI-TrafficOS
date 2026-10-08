import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  RealtimeClient,
  type RealtimeStatus,
} from "../lib/realtime-client";
import {
  buildSubscribeFrame,
  buildUnsubscribeFrame,
  buildWebSocketUrl,
  WS_CLOSE_AUTH_FAILED,
  type EventFrame,
} from "../lib/realtime-protocol";

// Mock WebSocket implementation for headless Vitest
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

  simulateClose(code = 1000, reason = "") {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code, reason } as CloseEvent);
  }

  simulateError(err = new Event("error")) {
    this.onerror?.(err);
  }
}

describe("RealtimeClient & Protocol (Phase 9 WS Contract)", () => {
  const originalWebSocket = global.WebSocket;

  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    (global as unknown as { WebSocket: typeof MockWebSocket }).WebSocket = MockWebSocket;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    global.WebSocket = originalWebSocket;
  });

  it("buildSubscribeFrame and buildUnsubscribeFrame emit 'event_types' key per backend contract", () => {
    const subStr = buildSubscribeFrame(["traffic.update", "congestion.change"]);
    const parsedSub = JSON.parse(subStr);
    expect(parsedSub).toEqual({
      type: "subscribe",
      event_types: ["traffic.update", "congestion.change"],
    });
    expect(parsedSub).not.toHaveProperty("topics");

    const unsubStr = buildUnsubscribeFrame(["traffic.update"]);
    const parsedUnsub = JSON.parse(unsubStr);
    expect(parsedUnsub).toEqual({
      type: "unsubscribe",
      event_types: ["traffic.update"],
    });
    expect(parsedUnsub).not.toHaveProperty("topics");
  });

  it("buildWebSocketUrl constructs URL with JWT token and last_event_id", () => {
    const url = buildWebSocketUrl({
      token: "mock-jwt-token",
      lastEventId: "last-evt-99",
      baseUrl: "http://api.trafficos.local",
    });

    expect(url).toContain("ws://api.trafficos.local/ws/v1/stream");
    expect(url).toContain("token=mock-jwt-token");
    expect(url).toContain("last_event_id=last-evt-99");
  });

  it("parses mocked {'type':'subscribed','event_types':[...]} and {'type':'connection.established'} handshake", () => {
    const client = new RealtimeClient({
      heartbeatIntervalMs: 15000,
    });

    client.connect("jwt-auth-abc");
    const ws = MockWebSocket.instances[0];
    expect(ws).toBeDefined();

    ws.simulateOpen();
    expect(client.getStatus()).toBe("connected");

    // Server sends subscribed handshake frame
    ws.simulateMessage({
      type: "subscribed",
      event_types: ["traffic.update", "congestion.change", "signal.change"],
      heartbeat_interval_ms: 25000,
    });

    expect(client.getStatus()).toBe("connected");
    expect(client.isConnected()).toBe(true);

    // Also support canonical connection.established
    ws.simulateMessage({
      type: "connection.established",
      event_types: ["traffic.update"],
      role: "admin",
      heartbeat_interval_ms: 25000,
    });
    expect(client.getStatus()).toBe("connected");

    client.disconnect();
  });

  it("handles 4401 Close code: halts retries and invokes onAuthFailure callback", () => {
    const onAuthFailure = vi.fn();
    const onStatusChange = vi.fn();

    const client = new RealtimeClient({
      onAuthFailure,
      onStatusChange,
      baseDelayMs: 1000,
    });

    client.connect("expired-jwt");
    const ws = MockWebSocket.instances[0];
    ws.simulateOpen();

    // Server rejects with WS_CLOSE_AUTH_FAILED (4401)
    ws.simulateClose(WS_CLOSE_AUTH_FAILED, "Token expired");

    expect(onAuthFailure).toHaveBeenCalledTimes(1);
    expect(client.getStatus()).toBe("error");

    // Advance time - verify no reconnection attempt was scheduled
    const prevCount = MockWebSocket.instances.length;
    vi.advanceTimersByTime(10000);
    expect(MockWebSocket.instances.length).toBe(prevCount);
  });

  it("handles backoff retries with exponential delay on dropped connections", () => {
    const statuses: RealtimeStatus[] = [];
    const client = new RealtimeClient({
      baseDelayMs: 1000,
      maxDelayMs: 10000,
      enableJitter: false,
      onStatusChange: (s) => statuses.push(s),
    });

    client.connect("jwt-valid");
    expect(MockWebSocket.instances.length).toBe(1);
    const ws1 = MockWebSocket.instances[0];
    ws1.simulateOpen();
    expect(client.getStatus()).toBe("connected");

    // Dropped connection (e.g. code 1006 abnormal closure)
    ws1.simulateClose(1006, "Abnormal closure");
    expect(client.getStatus()).toBe("connecting");

    // Wait 500ms - should not have reconnected yet
    vi.advanceTimersByTime(500);
    expect(MockWebSocket.instances.length).toBe(1);

    // Wait remaining delay to trigger first retry (1000ms total)
    vi.advanceTimersByTime(500);
    expect(MockWebSocket.instances.length).toBe(2);

    const ws2 = MockWebSocket.instances[1];
    // Fail again -> next delay is 2000ms
    ws2.simulateClose(1006);
    vi.advanceTimersByTime(1500);
    expect(MockWebSocket.instances.length).toBe(2);
    vi.advanceTimersByTime(500);
    expect(MockWebSocket.instances.length).toBe(3);

    client.disconnect();
  });

  it("sends last_event_id upon reconnect and applies replayed events in order", () => {
    const client = new RealtimeClient();
    const receivedEvents: string[] = [];

    client.subscribe("traffic.update", (evt) => {
      receivedEvents.push(evt.event_id);
    });

    client.connect("jwt-resync");
    const ws1 = MockWebSocket.instances[0];
    ws1.simulateOpen();

    // Receive first event
    ws1.simulateMessage({
      type: "traffic.update",
      event_id: "evt-001",
      timestamp: new Date().toISOString(),
      payload: { count: 10 },
    });
    expect(client.getLastEventId()).toBe("evt-001");
    expect(receivedEvents).toEqual(["evt-001"]);

    // Disconnect and reconnect manually
    ws1.simulateClose(1006);
    vi.advanceTimersByTime(2000);

    const ws2 = MockWebSocket.instances[1];
    ws2.simulateOpen();

    // Verify resync frame was sent with last_event_id
    const resyncSent = ws2.sentMessages.find((m) => m.includes('"resync"'));
    expect(resyncSent).toBeDefined();
    const parsedResync = JSON.parse(resyncSent!);
    expect(parsedResync.last_event_id).toBe("evt-001");

    // Server delivers replay batch via resync frame
    ws2.simulateMessage({
      type: "resync",
      events: [
        {
          type: "traffic.update",
          event_id: "evt-002",
          timestamp: new Date().toISOString(),
          payload: { count: 20 },
        },
        {
          type: "traffic.update",
          event_id: "evt-003",
          timestamp: new Date().toISOString(),
          payload: { count: 30 },
        },
      ],
      last_event_id: "evt-003",
    });

    expect(receivedEvents).toEqual(["evt-001", "evt-002", "evt-003"]);
    expect(client.getLastEventId()).toBe("evt-003");

    client.disconnect();
  });

  it("deduplicates events received more than once", () => {
    const client = new RealtimeClient();
    let callCount = 0;

    client.subscribe("signal.change", () => {
      callCount++;
    });

    client.connect("jwt-dedupe");
    const ws = MockWebSocket.instances[0];
    ws.simulateOpen();

    const payload = {
      type: "signal.change",
      event_id: "evt-unique-abc",
      timestamp: new Date().toISOString(),
      payload: { phase: "green" },
    };

    // Receive first time
    ws.simulateMessage(payload);
    expect(callCount).toBe(1);

    // Receive duplicate
    ws.simulateMessage(payload);
    expect(callCount).toBe(1);

    // Another event with new ID is processed
    ws.simulateMessage({
      ...payload,
      event_id: "evt-unique-def",
    });
    expect(callCount).toBe(2);

    client.disconnect();
  });

  it("flags stale status after missed heartbeats", () => {
    const staleStates: boolean[] = [];
    const client = new RealtimeClient({
      heartbeatIntervalMs: 2000,
      onStaleChange: (stale) => staleStates.push(stale),
    });

    client.connect("jwt-stale");
    const ws = MockWebSocket.instances[0];
    ws.simulateOpen();
    expect(client.isStale()).toBe(false);

    // Advance past 2 * heartbeatIntervalMs (4000ms) without any message
    vi.advanceTimersByTime(5000);
    expect(client.isStale()).toBe(true);
    expect(staleStates).toContain(true);

    // Receiving a heartbeat/ping refreshes staleness
    ws.simulateMessage({
      type: "heartbeat",
      timestamp: new Date().toISOString(),
    });
    expect(client.isStale()).toBe(false);

    client.disconnect();
  });

  it("sends subscribe and unsubscribe frames with event_types when listeners register/unregister", () => {
    const client = new RealtimeClient();
    client.connect("jwt-sub-test");
    const ws = MockWebSocket.instances[0];
    ws.simulateOpen();

    const unsub = client.subscribe("congestion.change", () => {});

    // Subscribed frame sent
    const subMsg = ws.sentMessages.find((m) => m.includes("congestion.change"));
    expect(subMsg).toBeDefined();
    const parsedSub = JSON.parse(subMsg!);
    expect(parsedSub).toEqual({
      type: "subscribe",
      event_types: ["congestion.change"],
    });

    // Unsubscribe
    unsub();
    const unsubMsg = ws.sentMessages.find((m) => m.includes('"unsubscribe"'));
    expect(unsubMsg).toBeDefined();
    const parsedUnsub = JSON.parse(unsubMsg!);
    expect(parsedUnsub).toEqual({
      type: "unsubscribe",
      event_types: ["congestion.change"],
    });

    client.disconnect();
  });

  it("safely ignores malformed or corrupt JSON messages", () => {
    const client = new RealtimeClient();
    let received = false;

    client.subscribe("traffic.update", () => {
      received = true;
    });

    client.connect("jwt-malformed");
    const ws = MockWebSocket.instances[0];
    ws.simulateOpen();

    // Send garbage strings
    expect(() => {
      ws.simulateMessage("THIS IS NOT JSON {{{");
      ws.simulateMessage("");
      ws.simulateMessage(12345 as unknown as string);
      ws.simulateMessage(null as unknown as string);
      ws.simulateMessage({});
    }).not.toThrow();

    expect(received).toBe(false);
    expect(client.getStatus()).toBe("connected");

    client.disconnect();
  });
});
