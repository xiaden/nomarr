/**
 * Calibration API functions.
 */

import { del, get, post } from "./client";

export interface ApplyCalibrationResponse {
  processed: number;
  failed: number;
  total: number;
  message: string;
}

export interface StartApplyResponse {
  status: "started" | "already_running";
  message: string;
}

export interface ApplyCombinedStatus {
  status: "idle" | "running" | "completed" | "failed";
  result: ApplyCalibrationResponse | null;
  error: string | null;
  total_files: number;
  completed_files: number;
  current_file: string | null;
  is_running: boolean;
}

/**
 * Start calibration apply in background. Returns immediately.
 */
export async function startApplyCalibration(): Promise<StartApplyResponse> {
  return post("/api/web/calibration/apply/start");
}

/**
 * Get combined status and per-file progress of background calibration apply.
 */
export async function getApplyCombinedStatus(): Promise<ApplyCombinedStatus> {
  return get("/api/web/calibration/apply/status");
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

export interface HistogramCombinedStatus {
  running: boolean;
  completed: boolean;
  error: string | null;
  result: HistogramCalibrationResult | null;
  total_heads: number;
  completed_heads: number;
  remaining_heads: number;
  last_updated: number | null;
  is_running: boolean;
  /** Name of head currently being processed */
  current_head: string | null;
  /** Index of current head (1-based) */
  current_head_index: number | null;
}

/**
 * Start histogram-based calibration in background.
 * Returns immediately. Use getHistogramCombinedStatus to check progress.
 */
export async function startHistogramCalibration(): Promise<StartHistogramResponse> {
  return post("/api/web/calibration/histogram/start");
}

/**
 * Get combined status and per-head progress of background histogram calibration.
 */
export async function getHistogramCombinedStatus(): Promise<HistogramCombinedStatus> {
  return get("/api/web/calibration/histogram/status");
}

// ======================================================
// Histogram Data (Distribution Visualization)
// ======================================================

export interface HistogramBin {
  val: number;
  count: number;
}

export interface HistogramSpec {
  lo: number;
  hi: number;
  bins: number;
  bin_width: number;
}

export interface HeadHistogramResponse {
  model_key: string;
  head_name: string;
  label: string;
  histogram_bins: HistogramBin[];
  p5: number;
  p95: number;
  n: number;
  histogram_spec: HistogramSpec;
  calibration_def_hash?: string;
  version?: number;
  underflow_count?: number;
  overflow_count?: number;
}

export interface AllCalibrationStatesResponse {
  calibrations: HeadHistogramResponse[];
}

/**
 * Get all calibration states with histogram bins (per-label).
 * Returns 22 items (one per label) instead of 12 (per head).
 */
export async function getAllHistograms(): Promise<AllCalibrationStatesResponse> {
  return get<AllCalibrationStatesResponse>("/api/web/calibration/histogram");
}

export interface ClearCalibrationResponse {
  files_updated: number;
  meta_keys_cleared: number;
}

/**
 * Clear all calibration data from the database.
 * Truncates calibration collections, clears meta keys, and nulls file calibration hashes.
 */
export async function clearCalibration(): Promise<ClearCalibrationResponse> {
  return del("/api/web/calibration");
}