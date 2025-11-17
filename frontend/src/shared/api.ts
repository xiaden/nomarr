/**
 * API client for Nomarr backend.
 *
 * Provides typed methods for all backend endpoints under:
 * - /web/auth/* (authentication)
 * - /web/api/* (queue, library, workers, etc.)
 */

import { clearSessionToken, getSessionToken, setSessionToken } from "./auth";
import type { QueueJob, QueueSummary } from "./types";

export const API_BASE_URL = "http://localhost:8356";

// ──────────────────────────────────────────────────────────────────────
// HTTP Helper
// ──────────────────────────────────────────────────────────────────────

/**
 * Generic request helper that handles fetch, error handling, and JSON parsing.
 *
 * Automatically includes Authorization header if session token exists.
 * Clears session token on 401/403 responses.
 *
 * @param path - API path (e.g., "/web/auth/login")
 * @param options - Standard fetch options
 * @returns Parsed JSON response as type T
 * @throws Error with message from backend or generic error
 */
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE_URL}${path}`;

  // Build headers
  const headers: Record<string, string> = {};

  // Copy existing headers
  if (options.headers) {
    const existingHeaders = options.headers as Record<string, string>;
    Object.assign(headers, existingHeaders);
  }

  // Add Content-Type for JSON requests
  if (options.body && typeof options.body === "string") {
    headers["Content-Type"] = "application/json";
  }

  // Add Authorization header if token exists
  const token = getSessionToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  try {
    const response = await fetch(url, {
      ...options,
      headers,
    });

    // Handle 401/403 - clear session token
    if (response.status === 401 || response.status === 403) {
      clearSessionToken();
      throw new Error("Unauthorized");
    }

    // Handle other non-OK responses
    if (!response.ok) {
      let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
      try {
        const errorData = await response.json();
        if (errorData.detail) {
          errorMessage = errorData.detail;
        }
      } catch {
        // If error response isn't JSON, use status text
      }
      throw new Error(errorMessage);
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof Error) {
      throw error;
    }
    throw new Error("Unknown error occurred");
  }
}

// ──────────────────────────────────────────────────────────────────────
// Authentication API
// ──────────────────────────────────────────────────────────────────────

/**
 * Login with admin password.
 *
 * Sends credentials to /web/auth/login and stores the returned session token.
 *
 * @param password - Admin password
 * @throws Error if login fails or response is invalid
 */
export async function login(password: string): Promise<void> {
  interface LoginResponse {
    session_token: string;
    expires_in: number;
  }

  const response = await request<LoginResponse>("/web/auth/login", {
    method: "POST",
    body: JSON.stringify({ password }),
  });

  if (!response.session_token) {
    throw new Error("Login response missing session token");
  }

  setSessionToken(response.session_token);
}

/**
 * Logout and invalidate current session token.
 *
 * Clears local session regardless of backend response.
 */
export async function logout(): Promise<void> {
  try {
    await request("/web/auth/logout", {
      method: "POST",
    });
  } catch (error) {
    // Don't throw - just log. The important part is clearing local session.
    console.warn("[Auth] Logout request failed:", error);
  } finally {
    clearSessionToken();
  }
}

// ──────────────────────────────────────────────────────────────────────
// Queue API
// ──────────────────────────────────────────────────────────────────────

export interface GetQueueParams {
  status?: "pending" | "running" | "done" | "error";
  limit?: number;
  offset?: number;
}

export const queue = {
  /**
   * List jobs with pagination and filtering.
   *
   * @param params - Optional filters (status, limit, offset)
   * @returns Jobs list with pagination info
   */
  listJobs: async (params?: {
    status?: string;
    limit?: number;
    offset?: number;
  }): Promise<{
    jobs: QueueJob[];
    total: number;
    limit: number;
    offset: number;
  }> => {
    const queryParams = new URLSearchParams();
    if (params?.status) queryParams.append("status", params.status);
    if (params?.limit) queryParams.append("limit", params.limit.toString());
    if (params?.offset) queryParams.append("offset", params.offset.toString());

    const query = queryParams.toString();
    const path = query ? `/web/api/list?${query}` : "/web/api/list";

    return request(path);
  },

  /**
   * Get queue statistics (counts by status).
   */
  getStatus: async (): Promise<QueueSummary> => {
    return request<QueueSummary>("/web/api/queue-depth");
  },

  /**
   * Get a specific job by ID.
   */
  getJob: async (jobId: number): Promise<QueueJob> => {
    return request<QueueJob>(`/web/api/status/${jobId}`);
  },

  /**
   * Remove jobs from queue.
   *
   * @param options - Can specify job_id, status, or all=true
   */
  removeJobs: async (options: {
    job_id?: number;
    status?: string;
    all?: boolean;
  }): Promise<{ removed: number; status: string }> => {
    return request("/web/api/admin/remove", {
      method: "POST",
      body: JSON.stringify(options),
    });
  },

  /**
   * Clear all completed and error jobs.
   */
  flush: async (): Promise<{
    removed: number;
    done: number;
    errors: number;
    status: string;
  }> => {
    return request("/web/api/admin/flush", {
      method: "POST",
    });
  },

  /**
   * Clear all jobs (except running).
   */
  clearAll: async (): Promise<{ removed: number; status: string }> => {
    return request("/web/api/admin/queue/clear-all", {
      method: "POST",
    });
  },

  /**
   * Clear only completed jobs.
   */
  clearCompleted: async (): Promise<{ removed: number; status: string }> => {
    return request("/web/api/admin/queue/clear-completed", {
      method: "POST",
    });
  },

  /**
   * Clear only error jobs.
   */
  clearErrors: async (): Promise<{ removed: number; status: string }> => {
    return request("/web/api/admin/queue/clear-errors", {
      method: "POST",
    });
  },

  /**
   * Reset stuck or error jobs back to pending.
   */
  resetJobs: async (options: {
    stuck?: boolean;
    errors?: boolean;
  }): Promise<{ status: string; message: string; reset: number }> => {
    return request("/web/api/admin/reset", {
      method: "POST",
      body: JSON.stringify(options),
    });
  },
};

// ──────────────────────────────────────────────────────────────────────
// Library API
// ──────────────────────────────────────────────────────────────────────

export const library = {
  /**
   * Get library statistics.
   */
  getStats: async (): Promise<{
    total_files: number;
    unique_artists: number;
    unique_albums: number;
    total_duration_seconds: number;
  }> => {
    return request("/web/api/library/stats");
  },
};

// ──────────────────────────────────────────────────────────────────────
// Analytics API
// ──────────────────────────────────────────────────────────────────────

export const analytics = {
  /**
   * Get tag frequency statistics.
   */
  getTagFrequencies: async (
    limit = 50
  ): Promise<{
    tag_frequencies: Array<{
      tag_key: string;
      total_count: number;
      unique_values: number;
    }>;
  }> => {
    return request(`/web/api/analytics/tag-frequencies?limit=${limit}`);
  },

  /**
   * Get mood distribution.
   */
  getMoodDistribution: async (): Promise<{
    mood_distribution: Array<{
      mood: string;
      count: number;
      percentage: number;
    }>;
  }> => {
    return request("/web/api/analytics/mood-distribution");
  },

  /**
   * Get tag correlations matrix.
   */
  getTagCorrelations: async (topN = 20): Promise<Record<string, unknown>> => {
    return request(`/web/api/analytics/tag-correlations?top_n=${topN}`);
  },

  /**
   * Get co-occurrences for a specific tag.
   */
  getTagCoOccurrences: async (
    tag: string,
    limit = 10
  ): Promise<{
    tag: string;
    total_occurrences: number;
    co_occurrences: Array<{
      tag: string;
      count: number;
      percentage: number;
    }>;
    top_artists: Array<{
      name: string;
      count: number;
      percentage: number;
    }>;
    top_genres: Array<{
      name: string;
      count: number;
      percentage: number;
    }>;
    limit: number;
  }> => {
    return request(
      `/web/api/analytics/tag-co-occurrences/${encodeURIComponent(
        tag
      )}?limit=${limit}`
    );
  },
};

// ──────────────────────────────────────────────────────────────────────
// Calibration API
// ──────────────────────────────────────────────────────────────────────

export const calibration = {
  /**
   * Generate new calibration from library data.
   */
  generate: async (
    saveSidecars = true
  ): Promise<{
    status: string;
    data: Record<string, unknown>;
    saved_files: unknown;
  }> => {
    return request("/web/api/calibration/generate", {
      method: "POST",
      body: JSON.stringify({ save_sidecars: saveSidecars }),
    });
  },

  /**
   * Apply calibration to entire library (queue recalibration jobs).
   */
  apply: async (): Promise<{ queued: number; message: string }> => {
    return request("/web/api/calibration/apply", {
      method: "POST",
    });
  },

  /**
   * Get calibration queue status.
   */
  getStatus: async (): Promise<{
    pending: number;
    running: number;
    completed: number;
    errors: number;
    worker_alive: boolean;
    worker_busy: boolean;
  }> => {
    return request("/web/api/calibration/status");
  },

  /**
   * Clear calibration queue.
   */
  clear: async (): Promise<{ cleared: number; message: string }> => {
    return request("/web/api/calibration/clear", {
      method: "POST",
    });
  },
};

// ──────────────────────────────────────────────────────────────────────
// Worker/Admin API
// ──────────────────────────────────────────────────────────────────────

export const admin = {
  /**
   * Pause the worker.
   */
  pauseWorker: async (): Promise<{ status: string; message: string }> => {
    return request("/web/api/admin/worker/pause", {
      method: "POST",
    });
  },

  /**
   * Resume the worker.
   */
  resumeWorker: async (): Promise<{ status: string; message: string }> => {
    return request("/web/api/admin/worker/resume", {
      method: "POST",
    });
  },

  /**
   * Restart the API server.
   */
  restart: async (): Promise<{ status: string; message: string }> => {
    return request("/web/api/admin/restart", {
      method: "POST",
    });
  },
};

// ──────────────────────────────────────────────────────────────────────
// Config API
// ──────────────────────────────────────────────────────────────────────

export const config = {
  /**
   * Get current configuration.
   */
  get: async (): Promise<Record<string, unknown>> => {
    return request("/web/api/config");
  },

  /**
   * Update a configuration value.
   */
  update: async (
    key: string,
    value: string
  ): Promise<{ success: boolean; message: string }> => {
    return request("/web/api/config", {
      method: "POST",
      body: JSON.stringify({ key, value }),
    });
  },
};

// ──────────────────────────────────────────────────────────────────────
// Navidrome API
// ──────────────────────────────────────────────────────────────────────

export const navidrome = {
  /**
   * Get preview of tags for Navidrome config.
   */
  getPreview: async (): Promise<{
    namespace: string;
    tag_count: number;
    tags: Array<{
      tag_key: string;
      type: string;
      is_multivalue: boolean;
      summary: string;
      total_count: number;
    }>;
  }> => {
    return request("/web/api/navidrome/preview");
  },

  /**
   * Generate Navidrome TOML configuration.
   */
  getConfig: async (): Promise<{
    namespace: string;
    config: string;
  }> => {
    return request("/web/api/navidrome/config");
  },

  /**
   * Preview Smart Playlist query results.
   */
  previewPlaylist: async (
    query: string,
    previewLimit = 10
  ): Promise<Record<string, unknown>> => {
    return request("/web/api/navidrome/playlists/preview", {
      method: "POST",
      body: JSON.stringify({ query, preview_limit: previewLimit }),
    });
  },

  /**
   * Generate Navidrome Smart Playlist (.nsp).
   */
  generatePlaylist: async (params: {
    query: string;
    playlist_name: string;
    comment?: string;
    limit?: number;
    sort?: string;
  }): Promise<{
    playlist_name: string;
    query: string;
    content: string;
  }> => {
    return request("/web/api/navidrome/playlists/generate", {
      method: "POST",
      body: JSON.stringify(params),
    });
  },
};

// ──────────────────────────────────────────────────────────────────────
// Tags/Inspect API
// ──────────────────────────────────────────────────────────────────────

export const tags = {
  /**
   * Read tags from an audio file.
   */
  showTags: async (
    path: string
  ): Promise<{
    path: string;
    namespace: string;
    tags: Record<string, unknown>;
    count: number;
  }> => {
    return request(`/web/api/show-tags?path=${encodeURIComponent(path)}`);
  },
};

// ──────────────────────────────────────────────────────────────────────
// Export Combined API
// ──────────────────────────────────────────────────────────────────────

export const api = {
  queue,
  library,
  analytics,
  calibration,
  admin,
  config,
  navidrome,
  tags,
};
