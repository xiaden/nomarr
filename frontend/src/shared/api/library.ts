/**
 * Library API functions.
 */

import type { Library, ScanResult } from "../types";

import { del, get, patch, post } from "./client";

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
 * Scan a specific library.
 * @param id - Library ID
 * @param scanType - 'quick' (skip unchanged files) or 'full' (rescan all)
 */
export async function scan(id: string, scanType: "quick" | "full" = "quick"): Promise<ScanResult> {
  // ID is already HTTP-encoded (e.g., "libraries:3970")
  return post<ScanResult>(`/api/web/libraries/${id}/scan?scan_type=${scanType}`, {});
}

export interface CleanupTagsResult {
  orphaned_count: number;
  deleted_count: number;
}

/**
 * Clean up orphaned tags (tags not referenced by any file).
 */
export async function cleanupOrphanedTags(
  dryRun = false
): Promise<CleanupTagsResult> {
  const queryParams = new URLSearchParams();
  if (dryRun) queryParams.append("dry_run", "true");

  const query = queryParams.toString();
  const endpoint = query
    ? `/api/web/libraries/cleanup-tags?${query}`
    : "/api/web/libraries/cleanup-tags";

  return post(endpoint);
}

// ──────────────────────────────────────────────────────────────────────────────
// Tag Reconciliation API
// ──────────────────────────────────────────────────────────────────────────────

export interface ReconcileTagsResult {
  processed: number;
  remaining: number;
  failed: number;
}

/**
 * Reconcile file tags for a library.
 * Writes tags from database to audio files based on the library's file_write_mode.
 */
export async function reconcileTags(
  libraryId: string,
  batchSize = 100
): Promise<ReconcileTagsResult> {
  return post(`/api/web/libraries/${libraryId}/reconcile-tags?batch_size=${batchSize}`);
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

export interface FileTag {
  key: string;
  value: string;
  type: string;
  is_nomarr: boolean;
}

export interface FileTagsResult {
  file_id: string;
  path: string;
  tags: FileTag[];
}

/**
 * Get all tags for a specific file.
 */
export async function getFileTags(
  fileId: string,
  nomarrOnly = false
): Promise<FileTagsResult> {
  const queryParams = new URLSearchParams();
  if (nomarrOnly) queryParams.append("nomarr_only", "true");

  const query = queryParams.toString();
  const endpoint = query
    ? `/api/web/libraries/files/${fileId}/tags?${query}`
    : `/api/web/libraries/files/${fileId}/tags`;

  return get(endpoint);
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