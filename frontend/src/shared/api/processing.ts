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

/**
 * Scanning library info.
 */
export interface ScanningLibrary {
  library_id: string;
  name: string;
  progress: number;
  total: number;
}

/**
 * Unified work status for the system.
 */
export interface WorkStatus {
  // Scanning status
  is_scanning: boolean;
  scanning_libraries: ScanningLibrary[];

  // ML processing status
  is_processing: boolean;
  pending_files: number;
  processed_files: number;
  total_files: number;

  // Overall activity indicator
  is_busy: boolean;
}

/**
 * Get unified work status for the system.
 *
 * Returns status of scanning, ML processing, and overall activity.
 * Use this for polling - poll at 1s when busy, 30s when idle.
 */
export async function getWorkStatus(): Promise<WorkStatus> {
  return get<WorkStatus>("/api/web/work-status");
}
