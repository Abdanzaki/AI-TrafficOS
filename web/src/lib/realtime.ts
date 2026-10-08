"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useAuth } from "./auth";
import {
  RealtimeClient,
  type RealtimeStatus,
  type RealtimeClientOptions,
} from "./realtime-client";
import {
  getAllowedTopicsForRole,
  isTopicAllowedForRole,
  type EventFrame,
} from "./realtime-protocol";

export type { RealtimeStatus };

export interface RealtimeMessage<T = unknown> {
  topic: string;
  data: T;
  timestamp: string;
  event_id?: string;
}

export interface RealtimeContextValue {
  status: RealtimeStatus;
  isConnected: boolean;
  isStale: boolean;
  lastEvent: RealtimeMessage | null;
  lastEventAt: number | null;
  isTopicStale: (topic: string) => boolean;
  getTopicLastEventAt: (topic: string) => number | null;
  subscribe: <T = unknown>(
    topic: string,
    callback: (message: RealtimeMessage<T>) => void
  ) => () => void;
  reconnect: () => void;
  client: RealtimeClient | null;
}

const RealtimeContext = createContext<RealtimeContextValue>({
  status: "disconnected",
  isConnected: false,
  isStale: false,
  lastEvent: null,
  lastEventAt: null,
  isTopicStale: () => true,
  getTopicLastEventAt: () => null,
  subscribe: () => () => {},
  reconnect: () => {},
  client: null,
});

export interface RealtimeProviderProps {
  children: ReactNode;
  clientOptions?: Partial<RealtimeClientOptions>;
}

export function RealtimeProvider({ children, clientOptions }: RealtimeProviderProps) {
  const { accessToken, user, logout } = useAuth();

  const [status, setStatus] = useState<RealtimeStatus>("disconnected");
  const [isStale, setIsStale] = useState<boolean>(false);
  const [lastEvent, setLastEvent] = useState<RealtimeMessage | null>(null);
  const [lastEventAt, setLastEventAt] = useState<number | null>(null);

  const clientRef = useRef<RealtimeClient | null>(null);

  // Compute permitted topic filters for active user role
  const allowedTopics = useMemo(() => {
    return getAllowedTopicsForRole(user?.role);
  }, [user?.role]);

  // Logout callback ref to avoid recreating client on auth re-renders
  const logoutRef = useRef(logout);
  useEffect(() => {
    logoutRef.current = logout;
  }, [logout]);

  // Instantiate client on first render (client-side only) so child effects can subscribe
  if (!clientRef.current && typeof window !== "undefined") {
    clientRef.current = new RealtimeClient({
      initialTopics: allowedTopics,
      onAuthFailure: () => {
        logoutRef.current();
      },
      onStatusChange: (newStatus) => {
        setStatus(newStatus);
      },
      onStaleChange: (stale) => {
        setIsStale(stale);
      },
      ...clientOptions,
    });
  }

  // Cleanup on provider unmount
  useEffect(() => {
    return () => {
      if (clientRef.current) {
        clientRef.current.disconnect();
        clientRef.current = null;
      }
    };
  }, []);

  // Sync role-based permitted topics when role changes
  useEffect(() => {
    if (clientRef.current) {
      clientRef.current.updateAllowedTopics(allowedTopics);
    }
  }, [allowedTopics]);

  // React to accessToken changes: connect when authenticated, disconnect on logout
  useEffect(() => {
    if (typeof window === "undefined") return;
    const client = clientRef.current;
    if (!client) return;

    if (accessToken) {
      client.connect(accessToken);
    } else {
      client.disconnect();
      setStatus("disconnected");
      setIsStale(false);
      setLastEvent(null);
      setLastEventAt(null);
    }
  }, [accessToken]);

  const subscribe = useCallback(
    <T = unknown>(
      topic: string,
      callback: (message: RealtimeMessage<T>) => void
    ): (() => void) => {
      // Guard against analyst subscribing to unauthorized topics
      if (!isTopicAllowedForRole(topic, user?.role)) {
        return () => {};
      }

      const client = clientRef.current;
      if (!client) {
        return () => {};
      }

      const wrappedCallback = (frame: EventFrame) => {
        const topic = frame.topic || frame.type;
        const data = (frame.data !== undefined ? frame.data : frame.payload) as T;
        const msg: RealtimeMessage<T> = {
          topic,
          data,
          timestamp: frame.timestamp,
          event_id: frame.event_id,
        };
        setLastEvent(msg as RealtimeMessage);
        setLastEventAt(Date.now());
        callback(msg);
      };

      return client.subscribe(topic, wrappedCallback);
    },
    [user?.role]
  );

  const reconnect = useCallback(() => {
    if (clientRef.current) {
      clientRef.current.reconnect();
    }
  }, []);

  const isTopicStale = useCallback((topic: string): boolean => {
    return clientRef.current ? clientRef.current.isTopicStale(topic) : true;
  }, []);

  const getTopicLastEventAt = useCallback((topic: string): number | null => {
    return clientRef.current ? clientRef.current.getLastEventAt(topic) : null;
  }, []);

  const value = useMemo<RealtimeContextValue>(() => {
    return {
      status,
      isConnected: status === "connected",
      isStale,
      lastEvent,
      lastEventAt,
      isTopicStale,
      getTopicLastEventAt,
      subscribe,
      reconnect,
      client: clientRef.current,
    };
  }, [
    status,
    isStale,
    lastEvent,
    lastEventAt,
    isTopicStale,
    getTopicLastEventAt,
    subscribe,
    reconnect,
  ]);

  return React.createElement(RealtimeContext.Provider, { value }, children);
}

/**
 * Access real-time status and subscription utilities.
 */
export function useRealtime(): RealtimeContextValue {
  return useContext(RealtimeContext);
}

/**
 * Hook to subscribe to a real-time topic.
 * Uses a stable callback ref so listeners are not churned on re-renders.
 */
export function useTopic<T = unknown>(
  topic: string,
  callback: (message: RealtimeMessage<T>) => void
): void {
  const { subscribe } = useRealtime();
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    const unsubscribe = subscribe<T>(topic, (message) => {
      callbackRef.current(message);
    });
    return unsubscribe;
  }, [subscribe, topic]);
}
