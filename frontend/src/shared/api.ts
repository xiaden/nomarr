/**
 * API client for Nomarr backend.
 *
 * Provides typed methods for all backend endpoints under:
 * - /api/web/* (web UI endpoints: auth, queue, library, analytics, etc.)
 */

import { clearSessionToken, getSessionToken, setSessionToken } from "./auth";
import type { Library, QueueJob, QueueSummary, ScanResult } from "./types";

/**
 * API base URL.
 *
 * In production build (served from Docker/same origin), use relative path.
 * In dev server (npm run dev), Vite's dev mode allows localhost backend calls.
 *
 * Since we always build for production (committed build), this is always empty string.
 * Dev server uses Vite's proxy or CORS to talk to localhost:8356 backend.
 */
export const API_BASE_URL = "";

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
 * Sends credentials to /api/web/auth/login and stores the returned session token.
 *
 * @param password - Admin password
 * @throws Error if login fails or response is invalid
 */
export async function login(password: string): Promise<void> {
  interface LoginResponse {
    session_token: string;
    expires_in: number;
  }

  const response = await request<LoginResponse>("/api/web/auth/login", {
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
    await request("/api/web/auth/logout", {
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
    const path = query ? `/api/web/queue/list?${query}` : "/api/web/queue/list";

    return request(path);
  },

  /**
   * Get queue statistics (counts by status).
   */
  getStatus: async (): Promise<QueueSummary> => {
    return request<QueueSummary>("/api/web/queue/queue-depth");
  },

  /**
   * Get a specific job by ID.
   */
  getJob: async (jobId: number): Promise<QueueJob> => {
    return request<QueueJob>(`/api/web/queue/status/${jobId}`);
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
    return request("/api/web/queue/admin/remove", {
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
    return request("/api/web/queue/admin/flush", {
      method: "POST",
    });
  },

  /**
   * Clear all jobs (except running).
   */
  clearAll: async (): Promise<{ removed: number; status: string }> => {
    return request("/api/web/queue/admin/clear-all", {
      method: "POST",
    });
  },

  /**
   * Clear only completed jobs.
   */
  clearCompleted: async (): Promise<{ removed: number; status: string }> => {
    return request("/api/web/queue/admin/clear-completed", {
      method: "POST",
    });
  },

  /**
   * Clear only error jobs.
   */
  clearErrors: async (): Promise<{ removed: number; status: string }> => {
    return request("/api/web/queue/admin/clear-errors", {
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
    return request("/api/web/queue/admin/reset", {
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
    return request("/api/web/libraries/stats");
  },

  /**
   * List all libraries.
   */
  list: async (enabledOnly = false): Promise<Library[]> => {
    const query = enabledOnly ? "?enabled_only=true" : "";
    const response = await request<{
      libraries: Array<{
        id: number;
        name: string;
        root_path: string;
        is_enabled: boolean;
        is_default: boolean;
        created_at?: string;
        updated_at?: string;
      }>;
    }>(`/api/web/libraries${query}`);

    // Convert snake_case to camelCase
    return response.libraries.map((lib) => ({
      id: lib.id,
      name: lib.name,
      rootPath: lib.root_path,
      isEnabled: lib.is_enabled,
      isDefault: lib.is_default,
      createdAt: lib.created_at,
      updatedAt: lib.updated_at,
    }));
  },

  /**
   * Get a specific library by ID.
   */
  get: async (id: number): Promise<Library> => {
    const response = await request<{
      id: number;
      name: string;
      root_path: string;
      is_enabled: boolean;
      is_default: boolean;
      created_at?: string;
      updated_at?: string;
    }>(`/api/web/libraries/${id}`);

    return {
      id: response.id,
      name: response.name,
      rootPath: response.root_path,
      isEnabled: response.is_enabled,
      isDefault: response.is_default,
      createdAt: response.created_at,
      updatedAt: response.updated_at,
    };
  },

  /**
   * Get the default library.
   */
  getDefault: async (): Promise<Library | null> => {
    try {
      const response = await request<{
        id: number;
        name: string;
        root_path: string;
        is_enabled: boolean;
        is_default: boolean;
        created_at?: string;
        updated_at?: string;
      }>("/api/web/libraries/default");

      return {
        id: response.id,
        name: response.name,
        rootPath: response.root_path,
        isEnabled: response.is_enabled,
        isDefault: response.is_default,
        createdAt: response.created_at,
        updatedAt: response.updated_at,
      };
    } catch {
      return null;
    }
  },

  /**
   * Create a new library.
   */
  create: async (payload: {
    name: string;
    rootPath: string;
    isEnabled?: boolean;
    isDefault?: boolean;
  }): Promise<Library> => {
    const response = await request<{
      id: number;
      name: string;
      root_path: string;
      is_enabled: boolean;
      is_default: boolean;
      created_at?: string;
      updated_at?: string;
    }>("/api/web/libraries", {
      method: "POST",
      body: JSON.stringify({
        name: payload.name,
        root_path: payload.rootPath,
        is_enabled: payload.isEnabled ?? true,
        is_default: payload.isDefault ?? false,
      }),
    });

    return {
      id: response.id,
      name: response.name,
      rootPath: response.root_path,
      isEnabled: response.is_enabled,
      isDefault: response.is_default,
      createdAt: response.created_at,
      updatedAt: response.updated_at,
    };
  },

  /**
   * Update a library's properties.
   */
  update: async (
    id: number,
    payload: {
      name?: string;
      rootPath?: string;
      isEnabled?: boolean;
      isDefault?: boolean;
    }
  ): Promise<Library> => {
    const body: Record<string, unknown> = {};
    if (payload.name !== undefined) body.name = payload.name;
    if (payload.rootPath !== undefined) body.root_path = payload.rootPath;
    if (payload.isEnabled !== undefined) body.is_enabled = payload.isEnabled;
    if (payload.isDefault !== undefined) body.is_default = payload.isDefault;

    const response = await request<{
      id: number;
      name: string;
      root_path: string;
      is_enabled: boolean;
      is_default: boolean;
      created_at?: string;
      updated_at?: string;
    }>(`/api/web/libraries/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });

    return {
      id: response.id,
      name: response.name,
      rootPath: response.root_path,
      isEnabled: response.is_enabled,
      isDefault: response.is_default,
      createdAt: response.created_at,
      updatedAt: response.updated_at,
    };
  },

  /**
   * Set a library as the default.
   */
  setDefault: async (id: number): Promise<Library> => {
    const response = await request<{
      id: number;
      name: string;
      root_path: string;
      is_enabled: boolean;
      is_default: boolean;
      created_at?: string;
      updated_at?: string;
    }>(`/api/web/libraries/${id}/set-default`, {
      method: "POST",
    });

    return {
      id: response.id,
      name: response.name,
      rootPath: response.root_path,
      isEnabled: response.is_enabled,
      isDefault: response.is_default,
      createdAt: response.created_at,
      updatedAt: response.updated_at,
    };
  },

  /**
   * Preview file count for a library path.
   */
  preview: async (
    id: number,
    options?: {
      paths?: string[];
      recursive?: boolean;
    }
  ): Promise<{ file_count: number }> => {
    const body: Record<string, unknown> = {
      recursive: options?.recursive ?? true,
    };
    if (options?.paths) {
      body.paths = options.paths;
    }

    return request<{ file_count: number }>(
      `/api/web/libraries/${id}/preview`,
      {
        method: "POST",
        body: JSON.stringify(body),
      }
    );
  },

  /**
   * Scan a specific library.
   */
  scan: async (
    id: number,
    options?: {
      paths?: string[];
      recursive?: boolean;
      force?: boolean;
      cleanMissing?: boolean;
    }
  ): Promise<ScanResult> => {
    const body: Record<string, unknown> = {
      recursive: options?.recursive ?? true,
      force: options?.force ?? false,
      clean_missing: options?.cleanMissing ?? true,
    };
    if (options?.paths) {
      body.paths = options.paths;
    }

    return request<ScanResult>(`/api/web/libraries/${id}/scan`, {
      method: "POST",
      body: JSON.stringify(body),
    });
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
    return request(`/api/web/analytics/tag-frequencies?limit=${limit}`);
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
    return request("/api/web/analytics/mood-distribution");
  },

  /**
   * Get tag correlations matrix.
   */
  getTagCorrelations: async (topN = 20): Promise<Record<string, unknown>> => {
    return request(`/api/web/analytics/tag-correlations?top_n=${topN}`);
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
      `/api/web/analytics/tag-co-occurrences/${encodeURIComponent(
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
    return request("/api/web/calibration/generate", {
      method: "POST",
      body: JSON.stringify({ save_sidecars: saveSidecars }),
    });
  },

  /**
   * Apply calibration to entire library (queue recalibration jobs).
   */
  apply: async (): Promise<{ queued: number; message: string }> => {
    return request("/api/web/calibration/apply", {
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
    return request("/api/web/calibration/status");
  },

  /**
   * Clear calibration queue.
   */
  clear: async (): Promise<{ cleared: number; message: string }> => {
    return request("/api/web/calibration/clear", {
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
    return request("/api/web/worker/pause", {
      method: "POST",
    });
  },

  /**
   * Resume the worker.
   */
  resumeWorker: async (): Promise<{ status: string; message: string }> => {
    return request("/api/web/worker/resume", {
      method: "POST",
    });
  },

  /**
   * Restart the API server.
   */
  restart: async (): Promise<{ status: string; message: string }> => {
    return request("/api/web/worker/restart", {
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
    return request("/api/web/config");
  },

  /**
   * Update a configuration value.
   */
  update: async (
    key: string,
    value: string
  ): Promise<{ success: boolean; message: string }> => {
    return request("/api/web/config", {
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
    return request("/api/web/navidrome/preview");
  },

  /**
   * Generate Navidrome TOML configuration.
   */
  getConfig: async (): Promise<{
    namespace: string;
    config: string;
  }> => {
    return request("/api/web/navidrome/config");
  },

  /**
   * Preview Smart Playlist query results.
   */
  previewPlaylist: async (
    query: string,
    previewLimit = 10
  ): Promise<Record<string, unknown>> => {
    return request("/api/web/navidrome/playlists/preview", {
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
    return request("/api/web/navidrome/playlists/generate", {
      method: "POST",
      body: JSON.stringify(params),
    });
  },

  /**
   * Get list of all available playlist templates.
   */
  getTemplates: async (): Promise<{
    templates: Array<{
      id: string;
      name: string;
      description: string;
      query: string;
      category?: string;
    }>;
    total_count: number;
  }> => {
    return request("/api/web/navidrome/templates");
  },

  /**
   * Generate all playlist templates as a batch.
   */
  generateTemplates: async (): Promise<{
    templates: Array<{
      id: string;
      name: string;
      filename: string;
      success: boolean;
      error?: string;
    }>;
    total_count: number;
  }> => {
    return request("/api/web/navidrome/templates", {
      method: "POST",
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
    return request(`/api/web/tags/show-tags?path=${encodeURIComponent(path)}`);
  },
};

// ──────────────────────────────────────────────────────────────────────
// Files/Browse API
// ──────────────────────────────────────────────────────────────────────

export const files = {
  /**
   * Search library files with optional filtering.
   */
  search: async (params?: {
    q?: string;
    artist?: string;
    album?: string;
    tagKey?: string;
    tagValue?: string;
    taggedOnly?: boolean;
    limit?: number;
    offset?: number;
  }): Promise<{
    files: Array<{
      id: number;
      path: string;
      library_id: number;
      file_size: number;
      modified_time: number;
      duration_seconds: number;
      artist?: string;
      album?: string;
      title?: string;
      genre?: string;
      year?: number;
      track_number?: number;
      calibration?: string;
      scanned_at?: number;
      last_tagged_at?: number;
      tagged: number;
      tagged_version?: string;
      skip_auto_tag: number;
      tags: Array<{
        key: string;
        value: string;
        type: string;
        is_nomarr: boolean;
      }>;
    }>;
    total: number;
    limit: number;
    offset: number;
  }> => {
    const queryParams = new URLSearchParams();
    if (params?.q) queryParams.append("q", params.q);
    if (params?.artist) queryParams.append("artist", params.artist);
    if (params?.album) queryParams.append("album", params.album);
    if (params?.tagKey) queryParams.append("tag_key", params.tagKey);
    if (params?.tagValue) queryParams.append("tag_value", params.tagValue);
    if (params?.taggedOnly) queryParams.append("tagged_only", "true");
    if (params?.limit) queryParams.append("limit", params.limit.toString());
    if (params?.offset) queryParams.append("offset", params.offset.toString());

    const query = queryParams.toString();
    const endpoint = query
      ? `/api/web/libraries/files/search?${query}`
      : "/api/web/libraries/files/search";

    return request(endpoint);
  },

  /**
   * Get unique tag keys for filtering.
   */
  getUniqueTagKeys: async (
    nomarrOnly = false
  ): Promise<{
    tag_keys: string[];
    count: number;
  }> => {
    const queryParams = new URLSearchParams();
    if (nomarrOnly) queryParams.append("nomarr_only", "true");

    const query = queryParams.toString();
    const endpoint = query
      ? `/api/web/libraries/files/tags/unique-keys?${query}`
      : "/api/web/libraries/files/tags/unique-keys";

    return request(endpoint);
  },

  /**
   * Get unique values for a specific tag key.
   */
  getTagValues: async (
    tagKey: string,
    nomarrOnly = true
  ): Promise<{
    tag_keys: string[]; // Actually values, but backend reuses same DTO
    count: number;
  }> => {
    const queryParams = new URLSearchParams();
    queryParams.append("tag_key", tagKey);
    if (nomarrOnly) queryParams.append("nomarr_only", "true");

    return request(`/api/web/libraries/files/tags/values?${queryParams.toString()}`);
  },
};

// ──────────────────────────────────────────────────────────────────────
// Filesystem API
// ──────────────────────────────────────────────────────────────────────

export const fs = {
  /**
   * List directory contents relative to library root.
   *
   * @param path - Relative path from library root (undefined or empty string for root)
   * @returns Directory listing with entries (directories first, alphabetically sorted)
   * @throws Error on invalid path, directory traversal, or path not found
   */
  listFs: async (
    path?: string
  ): Promise<{
    path: string;
    entries: Array<{ name: string; is_dir: boolean }>;
  }> => {
    const queryParams = new URLSearchParams();
    if (path) {
      queryParams.append("path", path);
    }

    const query = queryParams.toString();
    const endpoint = query ? `/api/web/fs/list?${query}` : "/api/web/fs/list";

    return request(endpoint);
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
  files,
  fs,
};
