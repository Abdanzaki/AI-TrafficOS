import {
  type ServerFrame,
  type EventFrame,
  type ConnectedFrame,
  type ResyncFrame,
  type RealtimeTopic,
  WS_CLOSE_AUTH_FAILED,
  buildWebSocketUrl,
  buildSubscribeFrame,
  buildUnsubscribeFrame,
  buildPongFrame,
  buildResyncRequestFrame,
} from "./realtime-protocol";

export type RealtimeStatus = "disconnected" | "connecting" | "connected" | "error";

export type EventListener = (frame: EventFrame) => void;
export type StatusListener = (status: RealtimeStatus) => void;
export type StaleListener = (isStale: boolean) => void;

export interface RealtimeClientOptions {
  baseUrl?: string;
  initialTopics?: string[];
  allowedTopics?: string[];
  heartbeatIntervalMs?: number;
  baseDelayMs?: number;
  maxDelayMs?: number;
  enableJitter?: boolean;
  maxSeenEvents?: number;
  onAuthFailure?: () => void;
  onStatusChange?: (status: RealtimeStatus) => void;
  onStaleChange?: (isStale: boolean) => void;
  onError?: (error: unknown) => void;
}

export class RealtimeClient {
  private ws: WebSocket | null = null;
  private token: string | null = null;
  private status: RealtimeStatus = "disconnected";
  private isIntentionalDisconnect = false;

  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatMonitorTimer: ReturnType<typeof setInterval> | null = null;

  private lastHeartbeatReceivedAt: number | null = null;
  private lastEventId: string | null = null;
  private lastEventAt: number | null = null;
  private wasStale = false;

  private readonly seenEventIds = new Set<string>();
  private readonly topicListeners = new Map<string, Set<EventListener>>();
  private readonly subscribedTopics = new Set<string>();
  private readonly topicLastReceivedAt = new Map<string, number>();

  private statusListeners = new Set<StatusListener>();
  private staleListeners = new Set<StaleListener>();

  private heartbeatIntervalMs: number;
  private readonly baseDelayMs: number;
  private readonly maxDelayMs: number;
  private readonly enableJitter: boolean;
  private readonly maxSeenEvents: number;

  constructor(private readonly options: RealtimeClientOptions = {}) {
    this.heartbeatIntervalMs = options.heartbeatIntervalMs ?? 15000;
    this.baseDelayMs = options.baseDelayMs ?? 1000;
    this.maxDelayMs = options.maxDelayMs ?? 30000;
    this.enableJitter = options.enableJitter ?? true;
    this.maxSeenEvents = options.maxSeenEvents ?? 1000;

    if (options.initialTopics) {
      options.initialTopics.forEach((t) => this.subscribedTopics.add(t));
    }
    if (options.onStatusChange) {
      this.statusListeners.add(options.onStatusChange);
    }
    if (options.onStaleChange) {
      this.staleListeners.add(options.onStaleChange);
    }
  }

  // --- Public Lifecycle API ---

  /**
   * Connect to WebSocket using JWT. Idempotent for React StrictMode double-mounting.
   */
  public connect(jwt: string): void {
    if (!jwt) return;

    // Idempotent guard: if already connected or connecting with identical token, avoid duplicate socket
    if (
      this.token === jwt &&
      (this.status === "connected" || this.status === "connecting") &&
      this.ws &&
      (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    if (this.token !== jwt && this.ws) {
      this.disconnect();
    }

    this.token = jwt;
    this.isIntentionalDisconnect = false;
    this.clearReconnectTimer();
    this.doConnect();
  }

  /**
   * Explicit client-initiated disconnect. Stops retries.
   */
  public disconnect(): void {
    this.isIntentionalDisconnect = true;
    this.clearReconnectTimer();
    this.stopHeartbeatMonitor();

    if (this.ws) {
      try {
        this.ws.close(1000, "Normal Closure");
      } catch {
        // Ignore close errors during disconnect
      }
      this.ws = null;
    }

    this.setStatus("disconnected");
  }

  /**
   * Manual reconnect trigger. Closes current socket (if any) and initiates a fresh handshake.
   */
  public reconnect(): void {
    this.isIntentionalDisconnect = false;
    this.clearReconnectTimer();

    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        // Ignore close errors
      }
      this.ws = null;
    }

    this.reconnectAttempts = 0;
    if (this.token) {
      this.doConnect();
    }
  }

  // --- Topic Subscriptions ---

  /**
   * Subscribes a listener to a specific topic.
   * Sends a subscribe frame to the server if newly added.
   * Returns an unsubscribe function.
   */
  public subscribe(topic: string, callback: EventListener): () => void {
    let listeners = this.topicListeners.get(topic);
    const isFirstListenerForTopic = !listeners || listeners.size === 0;

    if (!listeners) {
      listeners = new Set();
      this.topicListeners.set(topic, listeners);
    }
    listeners.add(callback);
    this.subscribedTopics.add(topic);

    if (isFirstListenerForTopic && this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.send(buildSubscribeFrame([topic]));
    }

    return () => {
      const currentListeners = this.topicListeners.get(topic);
      if (currentListeners) {
        currentListeners.delete(callback);
        if (currentListeners.size === 0) {
          this.topicListeners.delete(topic);
          this.subscribedTopics.delete(topic);
          if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.send(buildUnsubscribeFrame([topic]));
          }
        }
      }
    };
  }

  /**
   * Updates allowed topics (e.g. after role change).
   */
  public updateAllowedTopics(topics: string[]): void {
    const allowed = new Set(topics);
    for (const sub of Array.from(this.subscribedTopics)) {
      if (!allowed.has(sub)) {
        this.subscribedTopics.delete(sub);
        this.topicListeners.delete(sub);
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.send(buildUnsubscribeFrame([sub]));
        }
      }
    }
  }

  // --- Status and Staleness Accessors ---

  public getStatus(): RealtimeStatus {
    return this.status;
  }

  public isConnected(): boolean {
    return this.status === "connected";
  }

  public isStale(): boolean {
    if (this.status !== "connected") {
      return true;
    }
    if (!this.lastHeartbeatReceivedAt) {
      return false;
    }
    return Date.now() - this.lastHeartbeatReceivedAt > 2 * this.heartbeatIntervalMs;
  }

  public isTopicStale(topic: string): boolean {
    if (this.isStale()) {
      return true;
    }
    const last = this.topicLastReceivedAt.get(topic);
    if (last === undefined) {
      return false;
    }
    return Date.now() - last > 2 * this.heartbeatIntervalMs;
  }

  public getLastEventAt(topic?: string): number | null {
    if (topic) {
      return this.topicLastReceivedAt.get(topic) ?? null;
    }
    return this.lastEventAt;
  }

  public getLastEventId(): string | null {
    return this.lastEventId;
  }

  public onStatusChange(listener: StatusListener): () => void {
    this.statusListeners.add(listener);
    return () => {
      this.statusListeners.delete(listener);
    };
  }

  public onStaleChange(listener: StaleListener): () => void {
    this.staleListeners.add(listener);
    return () => {
      this.staleListeners.delete(listener);
    };
  }

  // --- Internal WebSocket Management ---

  private doConnect(): void {
    if (typeof window === "undefined" && typeof WebSocket === "undefined") {
      return;
    }

    this.setStatus("connecting");

    const url = buildWebSocketUrl({
      token: this.token || "",
      event_types: Array.from(this.subscribedTopics),
      lastEventId: this.lastEventId,
      baseUrl: this.options.baseUrl,
    });

    try {
      const socket = new WebSocket(url);
      this.ws = socket;

      socket.onopen = () => {
        if (this.ws !== socket) return;
        this.lastHeartbeatReceivedAt = Date.now();
        this.setStatus("connected");
        this.reconnectAttempts = 0;
        this.startHeartbeatMonitor();

        // Resync request on reconnect if we have a known last_event_id
        if (this.lastEventId) {
          this.send(buildResyncRequestFrame(this.lastEventId));
        }

        // Resubscribe any registered topics (event_types)
        if (this.subscribedTopics.size > 0) {
          this.send(buildSubscribeFrame(Array.from(this.subscribedTopics)));
        }
      };

      socket.onmessage = (event: MessageEvent) => {
        if (this.ws !== socket) return;
        this.handleMessage(event.data);
      };

      socket.onclose = (event: CloseEvent) => {
        if (this.ws !== socket) return;
        this.ws = null;
        this.stopHeartbeatMonitor();

        // Close code 4401 = authentication failure
        if (event.code === WS_CLOSE_AUTH_FAILED) {
          this.setStatus("error");
          this.options.onAuthFailure?.();
          return;
        }

        if (this.isIntentionalDisconnect || event.code === 1000) {
          this.setStatus("disconnected");
          return;
        }

        // Abnormal or dropped connection: transition to connecting and backoff
        this.setStatus("connecting");
        this.scheduleReconnect();
      };

      socket.onerror = (error: Event) => {
        if (this.ws !== socket) return;
        this.options.onError?.(error);
      };
    } catch (err) {
      this.options.onError?.(err);
      this.scheduleReconnect();
    }
  }

  private handleMessage(raw: unknown): void {
    if (typeof raw !== "string") return;

    let frame: ServerFrame;
    try {
      frame = JSON.parse(raw) as ServerFrame;
    } catch {
      // Malformed frame: log and ignore safely
      return;
    }

    if (!frame || typeof frame !== "object" || !("type" in frame)) {
      return;
    }

    // Record server frame arrival timestamp for liveness & staleness
    const now = Date.now();
    this.lastHeartbeatReceivedAt = now;
    this.checkStaleness();

    switch (frame.type) {
      case "connection.established":
      case "connected":
      case "subscribed":
      case "subscription.updated": {
        const connFrame = frame as ConnectedFrame;
        if (connFrame.heartbeat_interval_ms && connFrame.heartbeat_interval_ms > 0) {
          this.heartbeatIntervalMs = connFrame.heartbeat_interval_ms;
          this.startHeartbeatMonitor();
        }
        this.setStatus("connected");
        this.reconnectAttempts = 0;
        break;
      }

      case "heartbeat":
      case "ping": {
        // Reply with pong frame
        this.send(buildPongFrame(frame.timestamp));
        break;
      }

      case "pong": {
        break;
      }

      case "event": {
        this.handleEventFrame(frame as EventFrame);
        break;
      }

      case "resync": {
        const resyncFrame = frame as ResyncFrame;
        if (Array.isArray(resyncFrame.events)) {
          for (const evt of resyncFrame.events) {
            this.handleEventFrame(evt);
          }
        }
        if (resyncFrame.last_event_id) {
          this.lastEventId = resyncFrame.last_event_id;
        }
        break;
      }

      case "stale": {
        this.wasStale = true;
        this.staleListeners.forEach((listener) => {
          try {
            listener(true);
          } catch (err) {
            console.error("Error in stale listener:", err);
          }
        });
        break;
      }

      case "auth.expired": {
        this.setStatus("error");
        this.disconnect();
        this.options.onAuthFailure?.();
        break;
      }

      case "error": {
        this.options.onError?.(frame);
        break;
      }

      default: {
        // Domain events dispatched directly where frame.type is the event type (e.g. traffic.update)
        if ("event_id" in frame || "payload" in frame) {
          const rawEvt = frame as unknown as {
            event_id?: string;
            type?: string;
            topic?: string;
            data?: unknown;
            payload?: unknown;
            timestamp?: string;
            source?: string;
          };
          this.handleEventFrame({
            event_id: rawEvt.event_id || `evt-${Date.now()}`,
            type: rawEvt.type || "event",
            topic: rawEvt.topic || rawEvt.type,
            data: rawEvt.data !== undefined ? rawEvt.data : rawEvt.payload,
            payload: rawEvt.payload,
            timestamp: rawEvt.timestamp || new Date().toISOString(),
            source: rawEvt.source,
          });
        }
        break;
      }
    }
  }

  private handleEventFrame(frame: EventFrame): void {
    const topic = frame.topic || frame.type;
    if (!frame || !frame.event_id || !topic) {
      return;
    }

    // Client-side deduplication check
    if (this.seenEventIds.has(frame.event_id)) {
      return;
    }

    // Register event ID in seen set with LRU eviction
    this.seenEventIds.add(frame.event_id);
    if (this.seenEventIds.size > this.maxSeenEvents) {
      const oldest = this.seenEventIds.values().next().value;
      if (oldest !== undefined) {
        this.seenEventIds.delete(oldest);
      }
    }

    // Update tracking
    const now = Date.now();
    this.lastEventId = frame.event_id;
    this.lastEventAt = now;
    this.topicLastReceivedAt.set(topic, now);

    const normalizedFrame: EventFrame = {
      ...frame,
      topic,
      data: frame.data !== undefined ? frame.data : frame.payload,
    };

    // Route event frame to registered listeners for this topic
    const listeners = this.topicListeners.get(topic);
    if (listeners) {
      listeners.forEach((callback) => {
        try {
          callback(normalizedFrame);
        } catch (err) {
          console.error(`Error in realtime topic listener for ${topic}:`, err);
        }
      });
    }
  }

  private send(data: string): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(data);
      } catch (err) {
        console.error("Failed to send WebSocket frame:", err);
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null || this.isIntentionalDisconnect) {
      return;
    }

    const base = Math.min(
      this.baseDelayMs * Math.pow(2, this.reconnectAttempts),
      this.maxDelayMs
    );
    const jitter = this.enableJitter ? Math.random() * 500 : 0;
    const delay = base + jitter;
    this.reconnectAttempts++;

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.isIntentionalDisconnect && this.token) {
        this.doConnect();
      }
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private startHeartbeatMonitor(): void {
    this.stopHeartbeatMonitor();
    const interval = Math.max(100, Math.floor(this.heartbeatIntervalMs / 2));
    this.heartbeatMonitorTimer = setInterval(() => {
      this.checkStaleness();
    }, interval);
  }

  private stopHeartbeatMonitor(): void {
    if (this.heartbeatMonitorTimer !== null) {
      clearInterval(this.heartbeatMonitorTimer);
      this.heartbeatMonitorTimer = null;
    }
  }

  private checkStaleness(): void {
    const currentStale = this.isStale();
    if (currentStale !== this.wasStale) {
      this.wasStale = currentStale;
      this.staleListeners.forEach((listener) => {
        try {
          listener(currentStale);
        } catch (err) {
          console.error("Error in stale listener:", err);
        }
      });
    }
  }

  private setStatus(newStatus: RealtimeStatus): void {
    if (this.status === newStatus) return;
    this.status = newStatus;
    this.statusListeners.forEach((listener) => {
      try {
        listener(newStatus);
      } catch (err) {
        console.error("Error in status listener:", err);
      }
    });
    this.checkStaleness();
  }
}
