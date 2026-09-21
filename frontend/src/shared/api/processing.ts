/**
 * Processing status API functions.
 *
 * With discovery-based workers, processing state is derived from songs:
 * - pending: Files waiting to be processed (needs_tagging=1)
 * - processed: Files already processed
 * - total: All files in library
 */

import { get } from "./client";

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
 * Per-library pipeline status info for dashboard polling.
 */
export type RecoveryOutcome =
  | "active" | "written" | "partial" | "not_written" | "cancelled" | "conflict"
  | "indeterminate" | "raced" | "failed" | "replacement" | "deferred" | "unavailable" | "evicted";
export type RecoveryEvidence = "fingerprint_same" | "fingerprint_different" | "fingerprint_indeterminate";

export interface PipelineLibrary {
  library_id: string;
  name: string;
  state: string;
  library_auto_write: boolean;
  /** Legacy compatibility projection; normalized fields below are authoritative. */
  write_outcome?: string | null;
  scan_state?: string | null;
  hydration_state?: string | null;
  hydration_count?: number | null;
  tag_write_state?: string | null;
  requested_mode?: "none" | "files" | "database" | null;
  selected_run_counts?: Record<string, number> | null;
  outcome?: RecoveryOutcome | null;
  evidence_class?: RecoveryEvidence | null;
  resumable?: boolean | null;
  recovery_action?: string | null;
  message_code?: string | null;
}

/**
 * Unified work status for the system.
 */
export interface WorkStatus {
  // Scanning status
  is_scanning: boolean;
  scanning_libraries: ScanningLibrary[];
  pipeline_libraries: PipelineLibrary[];

  // ML processing status
  is_processing: boolean;
  pending_files: number;
  processed_files: number;
  total_files: number;

  // Velocity (rolling 5-minute average from server-side timestamps)
  files_per_minute: number;
  estimated_minutes_remaining: number | null;

  // Overall activity indicator — true while any pipeline stage is active
  // (scan, ML processing, calibration, or tag writing) or files are pending.
  is_busy: boolean;
}

/**
 * Get unified work status for the system.
 *
 * Returns status of scanning, ML processing, calibration, tag writing, and
 * overall activity. Use this for polling - poll fast when busy, slow when idle.
 */
export async function getWorkStatus(): Promise<WorkStatus> {
  return get<WorkStatus>("/api/web/machine-learning/work-status");
}
