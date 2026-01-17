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

export interface GenerateCalibrationResponse {
  status: string;
  data: CalibrationData;
  saved_files?: SavedFiles;
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

export interface CalibrationStatus {
  pending: number;
  running: number;
  completed: number;
  errors: number;
  worker_alive: boolean;
  worker_busy: boolean;
}

/**
 * Get calibration queue status.
 */
export async function getStatus(): Promise<CalibrationStatus> {
  return get("/api/web/calibration/status");
}

export interface ClearCalibrationResponse {
  cleared: number;
  message: string;
}

/**
 * Clear calibration queue.
 */
export async function clear(): Promise<ClearCalibrationResponse> {
  return post("/api/web/calibration/clear");
}
