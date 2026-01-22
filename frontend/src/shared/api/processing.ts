/**
 * Processing status API functions.
 *
 * With discovery-based workers, processing state is derived from library_files:
 * - pending: Files waiting to be processed (needs_tagging=1)
 * - processed: Files already processed
 * - total: All files in library
 */

import { get } from "./client";

export interface ProcessingStatus {
  pending: number;
  processed: number;
  total: number;
}

/**
 * Get current processing status.
 *
 * Returns counts of pending, processed, and total files.
 */
export async function getProcessingStatus(): Promise<ProcessingStatus> {
  return get<ProcessingStatus>("/api/web/processing/status");
}
