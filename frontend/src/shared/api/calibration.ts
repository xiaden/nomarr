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
