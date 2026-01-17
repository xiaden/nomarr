/**
 * Queue API functions.
 */

import type { QueueJob, QueueSummary } from "../types";

import { get, post } from "./client";

export interface ListJobsParams {
  status?: "pending" | "running" | "done" | "error";
  limit?: number;
  offset?: number;
}

export interface ListJobsResponse {
  jobs: QueueJob[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * List jobs with pagination and filtering.
 */
export async function listJobs(params?: ListJobsParams): Promise<ListJobsResponse> {
  const queryParams = new URLSearchParams();
  if (params?.status) queryParams.append("status", params.status);
  if (params?.limit) queryParams.append("limit", params.limit.toString());
  if (params?.offset) queryParams.append("offset", params.offset.toString());

  const query = queryParams.toString();
  const path = query ? `/api/web/queue/list?${query}` : "/api/web/queue/list";
  return get(path);
}

/**
 * Get queue statistics (counts by status).
 */
export async function getQueueStatus(): Promise<QueueSummary> {
  return get<QueueSummary>("/api/web/queue/queue-depth");
}

/**
 * Get a specific job by ID.
 */
export async function getJob(jobId: string): Promise<QueueJob> {
  return get<QueueJob>(`/api/web/queue/status/${jobId}`);
}

export interface RemoveJobsOptions {
  job_id?: string;
  status?: string;
  all?: boolean;
}

export interface RemoveJobsResponse {
  removed: number;
  status: string;
}

/**
 * Remove jobs from queue.
 */
export async function removeJobs(options: RemoveJobsOptions): Promise<RemoveJobsResponse> {
  return post("/api/web/queue/admin/remove", options);
}

export interface FlushResponse {
  removed: number;
  done: number;
  errors: number;
  status: string;
}

/**
 * Clear all completed and error jobs.
 */
export async function flush(): Promise<FlushResponse> {
  return post("/api/web/queue/admin/flush");
}

/**
 * Clear all jobs (except running).
 */
export async function clearAll(): Promise<RemoveJobsResponse> {
  return post("/api/web/queue/admin/clear-all");
}

/**
 * Clear only completed jobs.
 */
export async function clearCompleted(): Promise<RemoveJobsResponse> {
  return post("/api/web/queue/admin/clear-completed");
}

/**
 * Clear only error jobs.
 */
export async function clearErrors(): Promise<RemoveJobsResponse> {
  return post("/api/web/queue/admin/clear-errors");
}

export interface ResetJobsOptions {
  stuck?: boolean;
  errors?: boolean;
}

export interface ResetJobsResponse {
  status: string;
  message: string;
  reset: number;
}

/**
 * Reset stuck or error jobs back to pending.
 */
export async function resetJobs(options: ResetJobsOptions): Promise<ResetJobsResponse> {
  return post("/api/web/queue/admin/reset", options);
}
