/**
 * Server-Sent Events (SSE) utilities.
 *
 * Provides helpers for connecting to the /api/web/events/status endpoint
 * to receive real-time updates for:
 * - Queue statistics (pending/running/completed counts)
 * - Active job state
 * - Worker state
 */

import { API_BASE_URL } from "./api";
import { getSessionToken } from "./auth";

/**
 * Create an EventSource connection to the status stream.
 *
 * The backend endpoint requires session token as query parameter.
 * Provides real-time updates via Server-Sent Events.
 *
 * @param onMessage - Callback for each SSE message
 * @returns EventSource instance (caller should close when done)
 * @throws Error if not authenticated
 */
export function createStatusEventSource(
  onMessage: (event: MessageEvent) => void
): EventSource {
  const token = getSessionToken();

  if (!token) {
    throw new Error("Cannot create EventSource: not authenticated");
  }

  const url = `${API_BASE_URL}/api/web/events/status?token=${encodeURIComponent(
    token
  )}`;
  const eventSource = new EventSource(url);

  // Set up message handler
  eventSource.onmessage = onMessage;

  // Log connection events
  eventSource.onopen = () => {
    console.log("[SSE] Connected to status stream");
  };

  eventSource.onerror = (error) => {
    console.error("[SSE] Connection error:", error);
    // EventSource will automatically try to reconnect
  };

  return eventSource;
}
