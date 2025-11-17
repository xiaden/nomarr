/**
 * React hook for Server-Sent Events (SSE).
 *
 * Manages EventSource lifecycle (connect on mount, disconnect on unmount).
 * Provides real-time updates from /web/events/status endpoint.
 */

import { useEffect, useRef, useState } from "react";

import { createStatusEventSource } from "../shared/sse";

export interface UseSSEOptions {
  /**
   * Callback invoked for each SSE message.
   */
  onMessage: (event: MessageEvent) => void;

  /**
   * Optional callback for connection errors.
   */
  onError?: (error: Event) => void;

  /**
   * Whether to automatically connect on mount.
   * @default true
   */
  enabled?: boolean;
}

export interface UseSSEResult {
  /**
   * Current connection state.
   */
  connected: boolean;

  /**
   * Manually reconnect (if enabled=false or after disconnect).
   */
  reconnect: () => void;

  /**
   * Manually disconnect.
   */
  disconnect: () => void;
}

/**
 * React hook for SSE connection to status stream.
 *
 * @example
 * ```tsx
 * const { connected } = useSSE({
 *   onMessage: (event) => {
 *     const data = JSON.parse(event.data);
 *     console.log('SSE update:', data);
 *   }
 * });
 * ```
 */
export function useSSE(options: UseSSEOptions): UseSSEResult {
  const { onMessage, onError, enabled = true } = options;
  const [connected, setConnected] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  // Store callbacks in refs to avoid reconnecting when they change
  const onMessageRef = useRef(onMessage);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onMessageRef.current = onMessage;
    onErrorRef.current = onError;
  }, [onMessage, onError]);

  const connect = () => {
    // Don't create multiple connections
    if (eventSourceRef.current) {
      return;
    }

    try {
      const eventSource = createStatusEventSource((event) => {
        onMessageRef.current(event);
      });

      // Track connection state
      eventSource.onopen = () => {
        setConnected(true);
      };

      eventSource.onerror = (error) => {
        setConnected(false);
        onErrorRef.current?.(error);
      };

      eventSourceRef.current = eventSource;
    } catch (error) {
      console.error("[useSSE] Failed to create EventSource:", error);
      setConnected(false);
    }
  };

  const disconnect = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
      setConnected(false);
    }
  };

  const reconnect = () => {
    disconnect();
    connect();
  };

  // Auto-connect on mount if enabled
  useEffect(() => {
    if (!enabled) {
      return;
    }

    // Don't create multiple connections
    if (eventSourceRef.current) {
      return;
    }

    let eventSource: EventSource | null = null;

    try {
      eventSource = createStatusEventSource((event) => {
        onMessageRef.current(event);
      });

      // Track connection state
      eventSource.onopen = () => {
        setConnected(true);
      };

      eventSource.onerror = (error) => {
        setConnected(false);
        onErrorRef.current?.(error);
      };

      eventSourceRef.current = eventSource;
    } catch (error) {
      console.error("[useSSE] Failed to create EventSource:", error);
      // Don't set connected state here to avoid lint warning
      // It will remain false from initial state
    }

    // Cleanup on unmount
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
        setConnected(false);
      }
    };
  }, [enabled]);

  return {
    connected,
    reconnect,
    disconnect,
  };
}
