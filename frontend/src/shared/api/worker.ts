/**
 * Worker/Admin API functions.
 */

import { post } from "./client";

export interface WorkerResponse {
  status: string;
  message: string;
}

/**
 * Pause the worker.
 */
export async function pauseWorker(): Promise<WorkerResponse> {
  return post("/api/web/worker/pause");
}

/**
 * Resume the worker.
 */
export async function resumeWorker(): Promise<WorkerResponse> {
  return post("/api/web/worker/resume");
}

/**
 * Restart the API server.
 */
export async function restart(): Promise<WorkerResponse> {
  return post("/api/web/worker/restart");
}
