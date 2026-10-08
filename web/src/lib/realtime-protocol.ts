// Phase 9 WS contract assumptions â adapt here if backend shapes differ.

export const REALTIME_TOPICS = [
  "traffic.update",
  "congestion.change",
  "signal.change",
  "incident.created",
  "incident.updated",
  "emergency.created",
  "emergency.updated",
  "prediction.published",
  "control.decision",
  "notification.created",
  "system.status",
] as const;

export type RealtimeTopic = (typeof REALTIME_TOPICS)[number];

export const WS_CLOSE_AUTH_FAILED = 4401;

// --- Server -> Client Frames ---

export interface ConnectedFrame {
  type: "connection.established" | "connected" | "subscribed" | "subscription.updated";
  server_time?: string;
  heartbeat_interval_ms?: number;
  event_types?: string[];
  role?: string;
  deprecated?: boolean;
  note?: string;
}

export interface EventFrame<T = unknown> {
  type: string;
  event_id: string;
  topic?: string;
  data?: T;
  payload?: T;
  timestamp: string;
  source?: string;
  last_event_id?: string;
}

export interface HeartbeatFrame {
  type: "heartbeat" | "ping";
  timestamp?: string;
}

export interface ResyncFrame {
  type: "resync" | "resync.complete";
  events?: EventFrame[];
  replayed?: number;
  last_event_id?: string;
}

export interface StaleFrame {
  type: "stale";
  message?: string;
}

export interface AuthExpiredFrame {
  type: "auth.expired";
  message?: string;
}

export interface ErrorFrame {
  type: "error";
  code?: string;
  message?: string;
  detail?: string;
}

export type ServerFrame =
  | ConnectedFrame
  | EventFrame
  | HeartbeatFrame
  | ResyncFrame
  | StaleFrame
  | AuthExpiredFrame
  | ErrorFrame;

// --- Client -> Server Frames ---

export interface SubscribeFrame {
  type: "subscribe";
  event_types: string[];
}

export interface UnsubscribeFrame {
  type: "unsubscribe";
  event_types: string[];
}

export interface PongFrame {
  type: "pong";
  timestamp: string;
  server_time?: string;
}

export interface ResyncRequestFrame {
  type: "resync" | "resync_request";
  last_event_id?: string;
}

export type ClientFrame =
  | SubscribeFrame
  | UnsubscribeFrame
  | PongFrame
  | ResyncRequestFrame;

export interface BuildWsUrlOptions {
  token: string;
  event_types?: string[];
  topics?: string[];
  lastEventId?: string | null;
  baseUrl?: string;
}

/**
 * Builds the authenticated WebSocket endpoint URL.
 * Contract: ws(s)://HOST/ws/v1/stream?token=<JWT>&event_types=t1,t2&last_event_id=<id>
 * Derives HOST from baseUrl or NEXT_PUBLIC_API_URL with http -> ws / https -> wss.
 */
export function buildWebSocketUrl({
  token,
  event_types,
  topics,
  lastEventId,
  baseUrl,
}: BuildWsUrlOptions): string {
  let resolvedBase = baseUrl;
  if (!resolvedBase) {
    if (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_API_URL) {
      resolvedBase = process.env.NEXT_PUBLIC_API_URL;
    } else if (typeof window !== "undefined" && window.location?.origin) {
      resolvedBase = window.location.origin;
    } else {
      resolvedBase = "http://localhost:8000";
    }
  }

  // Strip trailing slashes and common API prefixes if mistakenly included in baseUrl
  resolvedBase = resolvedBase.replace(/\/+$/, "").replace(/\/api(\/v\d+)?$/, "");

  // Convert scheme http -> ws, https -> wss
  let wsUrl: string;
  if (resolvedBase.startsWith("https://")) {
    wsUrl = resolvedBase.replace(/^https:\/\//, "wss://");
  } else if (resolvedBase.startsWith("http://")) {
    wsUrl = resolvedBase.replace(/^http:\/\//, "ws://");
  } else if (resolvedBase.startsWith("wss://") || resolvedBase.startsWith("ws://")) {
    wsUrl = resolvedBase;
  } else {
    wsUrl = `ws://${resolvedBase}`;
  }

  const endpoint = `${wsUrl}/ws/v1/stream`;
  const params = new URLSearchParams();
  if (token) {
    params.set("token", token);
  }
  const resolvedTypes = event_types || topics;
  if (resolvedTypes && resolvedTypes.length > 0) {
    params.set("event_types", resolvedTypes.join(","));
  }
  if (lastEventId) {
    params.set("last_event_id", lastEventId);
  }

  const queryString = params.toString();
  return queryString ? `${endpoint}?${queryString}` : endpoint;
}

export function buildSubscribeFrame(eventTypes: string[]): string {
  return JSON.stringify({ type: "subscribe", event_types: eventTypes });
}

export function buildUnsubscribeFrame(eventTypes: string[]): string {
  return JSON.stringify({ type: "unsubscribe", event_types: eventTypes });
}

export function buildPongFrame(timestamp?: string): string {
  return JSON.stringify({
    type: "pong",
    timestamp: timestamp || new Date().toISOString(),
  });
}

export function buildResyncRequestFrame(lastEventId?: string): string {
  return JSON.stringify({
    type: "resync",
    last_event_id: lastEventId,
  });
}

/**
 * Filter topics accessible by user role.
 * - analyst must NOT subscribe to emergency.*, control.decision, or ai-decisions topics.
 * - traffic_officer and admin may subscribe to all topics.
 */
export function getAllowedTopicsForRole(role?: string | null): RealtimeTopic[] {
  if (role === "analyst") {
    return REALTIME_TOPICS.filter(
      (topic) =>
        !topic.startsWith("emergency.") &&
        topic !== "control.decision" &&
        !topic.startsWith("ai-decisions")
    );
  }
  return [...REALTIME_TOPICS];
}

export function isTopicAllowedForRole(topic: string, role?: string | null): boolean {
  if (role === "analyst") {
    if (
      topic.startsWith("emergency.") ||
      topic === "control.decision" ||
      topic.startsWith("ai-decisions")
    ) {
      return false;
    }
  }
  return true;
}
