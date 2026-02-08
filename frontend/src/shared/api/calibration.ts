/**
 * Calibration API functions.
 */

import { get, post } from "./client";

export interface CalibrationData {
  method: string;
  library_size: number;
  min_samples: number;
  calibrations: Record<string, unknown>;
  skipped_tags: number;
}

export interface SavedFiles {
  saved_files: number;
  total_files: number;
  total_labels: number;
}

export interface AffectedLibrary {
  library_id: string;
  name: string;
  outdated_files: number;
  file_write_mode: string;
}

export interface GenerateCalibrationResponse {
  status: string;
  data: CalibrationData;
  saved_files?: SavedFiles;
  requires_reconciliation?: boolean;
  affected_libraries?: AffectedLibrary[];
}

/**
 * Generate new calibration from library data.
 */
export async function generate(
  saveSidecars = true
): Promise<GenerateCalibrationResponse> {
  return post("/api/web/calibration/generate", { save_sidecars: saveSidecars });
}

export interface ApplyCalibrationResponse {
  queued: number;
  message: string;
}

/**
 * Apply calibration to entire library (queue recalibration jobs).
 */
export async function apply(): Promise<ApplyCalibrationResponse> {
  return post("/api/web/calibration/apply");
}

export interface LibraryCalibrationStatus {
  library_id: string;
  library_name: string;
  total_files: number;
  current_count: number;
  outdated_count: number;
  percentage: number;
}

export interface CalibrationStatus {
  global_version: string;
  last_run: number;
  libraries: LibraryCalibrationStatus[];
}

/**
 * Get calibration status with per-library breakdown.
 */
export async function getStatus(): Promise<CalibrationStatus> {
  return get("/api/web/calibration/status");
}


// ============================================================================
// Histogram Calibration (Background Generation)
// ============================================================================

export interface StartHistogramResponse {
  status: "started" | "already_running";
  message: string;
}

export interface HistogramCalibrationResult {
  version: number;
  heads_processed: number;
  heads_success: number;
  heads_failed: number;
  results: Record<string, { p5: number; p95: number; n: number; underflow_count: number; overflow_count: number }>;
}

export interface HistogramCalibrationStatus {
  running: boolean;
  completed: boolean;
  error: string | null;
  result: HistogramCalibrationResult | null;
}

export interface HistogramCalibrationProgress {
  total_heads: number;
  completed_heads: number;
  remaining_heads: number;
  last_updated: number | null;
  is_running: boolean;
}

/**
 * Start histogram-based calibration in background.
 * Returns immediately. Use getHistogramStatus/getHistogramProgress to check progress.
 */
export async function startHistogramCalibration(): Promise<StartHistogramResponse> {
  return post("/api/web/calibration/start-histogram");
}

/**
 * Get status of background histogram calibration.
 * Check running/completed/error state and final result.
 */
export async function getHistogramStatus(): Promise<HistogramCalibrationStatus> {
  return get("/api/web/calibration/histogram-status");
}

/**
 * Get per-head progress of histogram calibration.
 * Use while generation is running to show progress UI.
 */
export async function getHistogramProgress(): Promise<HistogramCalibrationProgress> {
  return get("/api/web/calibration/histogram-progress");
}

// ============================================================================ 
// Convergence Analysis
// ============================================================================ 

export interface HistorySnapshot {
  snapshot_at: number;
  p5: number;
  p95: number;
  n: number;
  p5_delta: number | null;
  p95_delta: number | null;
  n_delta: number | null;
  underflow_count: number;
  overflow_count: number;
}

export interface ConvergenceHeadStatus {
  latest_snapshot: HistorySnapshot;
  p5_delta: number | null;
  p95_delta: number | null;
  n: number;
  converged: boolean;
}

export interface ConvergenceStatusResponse {
  [head_key: string]: ConvergenceHeadStatus;
}

export interface CalibrationHistoryResponse {
  calibration_key: string;
  history: HistorySnapshot[];
}

/**
 * Get latest convergence status for all calibration heads.
 * Returns per-head convergence metrics and status.
 */
export async function getConvergenceStatus(): Promise<ConvergenceStatusResponse> {
  return get("/api/web/calibration/convergence");
}

/**
 * Get calibration convergence history for a specific head.
 * @param calibrationKey Head identifier (e.g., "effnet-20220825:mood_happy")
 * @param limit Max snapshots to return (default 100)
 */
export async function getHistory(
  calibrationKey?: string,
  limit = 100
): Promise<CalibrationHistoryResponse | Record<string, CalibrationHistoryResponse>> {
  if (calibrationKey) {
    return get<CalibrationHistoryResponse>(`/api/web/calibration/history/${calibrationKey}?limit=${limit}`);
  }
  return get(`/api/web/calibration/history?limit=${limit}`);
}