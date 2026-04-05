/**
 * Library API functions.
 */

import type { Library, ScanResult } from "../types";

import { del, get, patch, post, put } from "./client";

export interface LibraryStats {
  total_files: number;
  unique_artists: number;
  unique_albums: number;
  total_duration_seconds: number;
}

/**
 * Get library statistics.
 */
export async function getStats(): Promise<LibraryStats> {
  return get("/api/web/libraries/stats");
}

interface LibraryResponse {
  library_id: string;
  name: string;
  root_path: string;
  is_enabled: boolean;
  watch_mode: string;
  file_write_mode: "none" | "minimal" | "full";
  created_at?: string | number;
  updated_at?: string | number;
  scanned_at?: string | null;
  scan_status?: string | null;
  scan_progress?: number | null;
  scan_total?: number | null;
  scan_error?: string | null;
  file_count: number;
  folder_count: number;
}

function mapLibraryResponse(lib: LibraryResponse): Library {
  return {
    library_id: lib.library_id,
    name: lib.name,
    rootPath: lib.root_path,
    isEnabled: lib.is_enabled,
    watchMode: lib.watch_mode,
    fileWriteMode: lib.file_write_mode,
    createdAt: lib.created_at,
    updatedAt: lib.updated_at,
    scannedAt: lib.scanned_at,
    scanStatus: lib.scan_status,
    scanProgress: lib.scan_progress,
    scanTotal: lib.scan_total,
    scanError: lib.scan_error,
    fileCount: lib.file_count,
    folderCount: lib.folder_count,
  };
}

/**
 * List all libraries.
 */
export async function list(enabledOnly = false): Promise<Library[]> {
  const query = enabledOnly ? "?enabled_only=true" : "";
  const response = await get<{ libraries: LibraryResponse[] }>(
    `/api/web/libraries${query}`
  );
  return response.libraries.map(mapLibraryResponse);
}

/**
 * Alias for list() to match older import naming.
 */
export async function getLibraries(enabledOnly = false): Promise<Library[]> {
  return list(enabledOnly);
}

/**
 * Get a specific library by ID.
 */
export async function getLibrary(id: string): Promise<Library> {
  // ID is already HTTP-encoded (e.g., "libraries:3970")
  const response = await get<LibraryResponse>(`/api/web/libraries/${id}`);
  return mapLibraryResponse(response);
}

export interface CreateLibraryPayload {
  name: string | null;  // Optional: auto-generated from path if null
  rootPath: string;
  isEnabled?: boolean;
  watchMode?: string;  // 'off', 'event', or 'poll'
  fileWriteMode?: "none" | "minimal" | "full";  // Tag writing mode
}

/**
 * Create a new library.
 */
export async function create(payload: CreateLibraryPayload): Promise<Library> {
  const response = await post<LibraryResponse>("/api/web/libraries", {
    name: payload.name,
    root_path: payload.rootPath,
    is_enabled: payload.isEnabled ?? true,
    watch_mode: payload.watchMode ?? "off",
    file_write_mode: payload.fileWriteMode ?? "full",
  });
  return mapLibraryResponse(response);
}

export interface UpdateLibraryPayload {
  name?: string;
  rootPath?: string;
  isEnabled?: boolean;
  watchMode?: string;  // 'off', 'event', or 'poll'
  fileWriteMode?: "none" | "minimal" | "full";  // Tag writing mode
}

/**
 * Update a library's properties.
 */
export async function update(
  id: string,
  payload: UpdateLibraryPayload
): Promise<Library> {
  const body: Record<string, unknown> = {};
  if (payload.name !== undefined) body.name = payload.name;
  if (payload.rootPath !== undefined) body.root_path = payload.rootPath;
  if (payload.isEnabled !== undefined) body.is_enabled = payload.isEnabled;
  if (payload.watchMode !== undefined) body.watch_mode = payload.watchMode;
  if (payload.fileWriteMode !== undefined) body.file_write_mode = payload.fileWriteMode;

  // ID is already HTTP-encoded (e.g., "libraries:3970")
  const response = await patch<LibraryResponse>(
    `/api/web/libraries/${id}`,
    body
  );
  return mapLibraryResponse(response);
}

/**
 * Delete a library.
 */
export async function deleteLibrary(id: string): Promise<void> {
  // ID is already HTTP-encoded (e.g., "libraries:3970")
  await del(`/api/web/libraries/${id}`);
}

/**
 * Start a quick scan for a specific library (skips unchanged files).
 * @param id - Library ID
 */
export async function scanQuick(id: string): Promise<ScanResult> {
  // ID is already HTTP-encoded (e.g., "libraries:3970")
  return post<ScanResult>(`/api/web/libraries/${id}/scan/quick`, {});
}

/**
 * Start a full scan for a specific library (rescans all files).
 * @param id - Library ID
 */
export async function scanFull(id: string): Promise<ScanResult> {
  // ID is already HTTP-encoded (e.g., "libraries:3970")
  return post<ScanResult>(`/api/web/libraries/${id}/scan/full`, {});
}

// ──────────────────────────────────────────────────────────────────────────────
// Tag Reconciliation API
// ──────────────────────────────────────────────────────────────────────────────

/**
 * Immediate response returned after starting a background tag-write job.
 * `status` is the job acceptance status (for example, `"started"`).
 * `task_id` is the BTS task identifier used to poll progress via `getReconcileStatus()`.
 */
export interface StartTagWriteResult {
  status: string;
  task_id: string;
}

/**
 * Start a background tag-write job for a library and return immediately.
 * Writes tags from the database to audio files based on the library's `file_write_mode`.
 *
 * @param libraryId - Library ID
 * @returns Immediate job start result. Poll `getReconcileStatus()` with the returned
 *   `task_id` to track background progress.
 */
export async function reconcileTags(
  libraryId: string
): Promise<StartTagWriteResult> {
  return post(`/api/web/libraries/${libraryId}/reconcile-tags`);
}

export interface ReconcileStatusResult {
  pending_count: number;
  in_progress: boolean;
}

/**
 * Get tag reconciliation status for a library.
 */
export async function getReconcileStatus(libraryId: string): Promise<ReconcileStatusResult> {
  return get(`/api/web/libraries/${libraryId}/reconcile-status`);
}

export interface UpdateWriteModeResult {
  file_write_mode: "none" | "minimal" | "full";
  requires_reconciliation: boolean;
  affected_file_count: number;
}

/**
 * Update the file write mode for a library.
 */
export async function updateWriteMode(
  libraryId: string,
  mode: "none" | "minimal" | "full"
): Promise<UpdateWriteModeResult> {
  return patch(`/api/web/libraries/${libraryId}/write-mode?file_write_mode=${mode}`);
}

// ────────────────────────────────────────────────────────────────────────────────
// Recent Activity
// ────────────────────────────────────────────────────────────────────────────────

export interface RecentFile {
  file_id: string;
  path: string;
  title: string | null;
  artist: string | null;
  album: string | null;
  last_tagged_at: number;
}

export interface RecentFilesResult {
  files: RecentFile[];
}

/**
 * Get recently processed files.
 */
export async function getRecentActivity(
  limit = 20,
  libraryId?: string
): Promise<RecentFilesResult> {
  const params = new URLSearchParams();
  params.append("limit", limit.toString());
  if (libraryId) params.append("library_id", libraryId);
  return get(`/api/web/libraries/recent-activity?${params.toString()}`);
}

// ────────────────────────────────────────────────────────────────────────────────
// Vector Search Configuration
// ────────────────────────────────────────────────────────────────────────────────

export interface VectorConfigResponse {
  vector_group_size: number;
  vector_search_thoroughness: number;
  is_group_size_inherited: boolean;
  is_thoroughness_inherited: boolean;
}

export interface VectorConfigUpdate {
  vector_group_size: number | null;
  vector_search_thoroughness: number | null;
}

export interface VectorStatsItem {
  backbone_id: string;
  hot_count: number;
  cold_count: number;
  index_exists: boolean;
}

export interface LibraryVectorStatsResponse {
  library_key: string;
  stats: VectorStatsItem[];
}

/**
 * Get the effective vector search config for a library.
 */
export async function getLibraryVectorConfig(libraryId: string): Promise<VectorConfigResponse> {
  return get(`/api/web/libraries/${libraryId}/vector-config`);
}

/**
 * Update per-library vector search config overrides.
 * Pass null values to clear the override and inherit the global default.
 */
export async function updateLibraryVectorConfig(
  libraryId: string,
  config: VectorConfigUpdate
): Promise<VectorConfigResponse> {
  return put(`/api/web/libraries/${libraryId}/vector-config`, config);
}

/**
 * Get per-library vector statistics (hot/cold counts per backbone, index status).
 */
export async function getLibraryVectorStats(libraryId: string): Promise<LibraryVectorStatsResponse> {
  return get(`/api/web/libraries/${libraryId}/vector-stats`);
}

// ────────────────────────────────────────────────────────────────────────────────
// Errored Files
// ────────────────────────────────────────────────────────────────────────────────

export interface ErroredFileItem {
  file_id: string;
  path: string;
  duration_seconds: number | null;
  artist: string | null;
  title: string | null;
}

export interface ErroredFilesResult {
  total: number;
  files: ErroredFileItem[];
}

/**
 * Get errored files for a library.
 */
export async function getErroredFiles(libraryId: string): Promise<ErroredFilesResult> {
  return get(`/api/web/libraries/${libraryId}/errored-files`);
}

export interface RetryErroredResult {
  retried: number;
}

/**
 * Retry errored files for a library.
 * If fileIds is provided, only those files are retried; otherwise all errored files are retried.
 */
export async function retryErroredFiles(
  libraryId: string,
  fileIds?: string[]
): Promise<RetryErroredResult> {
  const body = fileIds ? { file_ids: fileIds } : {};
  return post(`/api/web/libraries/${libraryId}/retry-errored`, body);
}