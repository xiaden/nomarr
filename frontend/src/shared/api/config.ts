/**
 * Config API functions.
 */

import { get, post } from "./client";

/**
 * Get current configuration.
 */
export async function getConfig(): Promise<Record<string, unknown>> {
  return get("/api/web/config");
}

export interface UpdateConfigResponse {
  status: string;
  message: string;
}

/**
 * Update a configuration value.
 */
export async function updateConfig(
  key: string,
  value: string
): Promise<UpdateConfigResponse> {
  return post("/api/web/config", { key, value });
}
