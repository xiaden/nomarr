/**
 * Worker/Admin API functions.
 */

import { post } from "./client";

export interface WorkerResponse {
  status: string;
  message: string;
}

/**
 * Restart the API server.
 */
export async function restart(): Promise<WorkerResponse> {
  return post("/api/web/admin/restart");
}
