/**
 * API client utilities.
 *
 * All request concerns centralized here:
 * - Base URL resolution
 * - Auth header injection
 * - Error normalization
 * - JSON parsing
 * - Optional case conversion
 */

import { clearSessionToken, getSessionToken } from "../auth";

/**
 * API base URL.
 * Empty string for production (same-origin).
 * Vite dev server proxies to backend.
 */
export const API_BASE_URL = "";

/**
 * Convert snake_case keys to camelCase recursively.
 */
export function snakeToCamel<T>(obj: unknown): T {
  if (Array.isArray(obj)) {
    return obj.map(snakeToCamel) as T;
  }
  if (obj !== null && typeof obj === "object") {
    return Object.entries(obj as Record<string, unknown>).reduce(
      (acc, [key, value]) => {
        const camelKey = key.replace(/_([a-z])/g, (_, letter) =>
          letter.toUpperCase()
        );
        acc[camelKey] = snakeToCamel(value);
        return acc;
      },
      {} as Record<string, unknown>
    ) as T;
  }
  return obj as T;
}

/**
 * Normalized API error with status code and message.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly detail?: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Convert response keys from snake_case to camelCase. Default: false */
  transformCase?: boolean;
}

/**
 * Generic request helper.
 *
 * Handles:
 * - JSON serialization of body
 * - Auth header injection
 * - Error normalization (ApiError)
 * - 401/403 session clearing
 * - Optional snake_case → camelCase transform
 */
export async function request<T>(
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  const { body, transformCase = false, ...fetchOptions } = options;
  const url = `${API_BASE_URL}${path}`;

  // Build headers
  const headers: Record<string, string> = {};

  if (fetchOptions.headers) {
    Object.assign(headers, fetchOptions.headers);
  }

  // JSON body handling
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  // Auth header injection
  const token = getSessionToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  try {
    const response = await fetch(url, {
      ...fetchOptions,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

    // Handle auth errors - clear session
    if (response.status === 401 || response.status === 403) {
      clearSessionToken();
      throw new ApiError(response.status, "Unauthorized");
    }

    // Handle other errors
    if (!response.ok) {
      let message = `HTTP ${response.status}: ${response.statusText}`;
      let detail: unknown;
      try {
        const errorData = await response.json();
        if (errorData.detail) {
          message = String(errorData.detail);
          detail = errorData;
        }
      } catch {
        // Response wasn't JSON
      }
      throw new ApiError(response.status, message, detail);
    }

    // Parse JSON response
    const json = await response.json();

    // Optional case transformation
    if (transformCase) {
      return snakeToCamel<T>(json);
    }

    return json as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof Error) {
      throw new ApiError(0, error.message);
    }
    throw new ApiError(0, "Unknown error occurred");
  }
}

/**
 * Helper for GET requests.
 */
export function get<T>(
  path: string,
  options?: Omit<RequestOptions, "method">
): Promise<T> {
  return request<T>(path, { ...options, method: "GET" });
}

/**
 * Helper for POST requests.
 */
export function post<T>(
  path: string,
  body?: unknown,
  options?: Omit<RequestOptions, "method" | "body">
): Promise<T> {
  return request<T>(path, { ...options, method: "POST", body });
}

/**
 * Helper for PUT requests.
 */
export function put<T>(
  path: string,
  body?: unknown,
  options?: Omit<RequestOptions, "method" | "body">
): Promise<T> {
  return request<T>(path, { ...options, method: "PUT", body });
}

/**
 * Helper for PATCH requests.
 */
export function patch<T>(
  path: string,
  body?: unknown,
  options?: Omit<RequestOptions, "method" | "body">
): Promise<T> {
  return request<T>(path, { ...options, method: "PATCH", body });
}

/**
 * Helper for DELETE requests.
 */
export function del<T>(
  path: string,
  options?: Omit<RequestOptions, "method">
): Promise<T> {
  return request<T>(path, { ...options, method: "DELETE" });
}
