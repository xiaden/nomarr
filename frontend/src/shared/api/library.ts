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
  id: string;
  name: string;
  root_path: string;
  is_enabled: boolean;
  is_default: boolean;
  created_at?: string | number;
  updated_at?: string | number;
}

function mapLibraryResponse(lib: LibraryResponse): Library {
  return {
    id: lib.id,
    name: lib.name,
    rootPath: lib.root_path,
    isEnabled: lib.is_enabled,
    isDefault: lib.is_default,
    createdAt: lib.created_at,
    updatedAt: lib.updated_at,
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
 * Get a specific library by ID.
 */
export async function getLibrary(id: string): Promise<Library> {
  const response = await get<LibraryResponse>(`/api/web/libraries/${id}`);
  return mapLibraryResponse(response);
}

/**
 * Get the default library.
 */
export async function getDefault(): Promise<Library | null> {
  try {
    const response = await get<LibraryResponse>("/api/web/libraries/default");
    return mapLibraryResponse(response);
  } catch {
    return null;
  }
}

export interface CreateLibraryPayload {
  name: string | null;  // Optional: auto-generated from path if null
  rootPath: string;
  isEnabled?: boolean;
  isDefault?: boolean;
}

/**
 * Create a new library.
 */
export async function create(payload: CreateLibraryPayload): Promise<Library> {
  const response = await post<LibraryResponse>("/api/web/libraries", {
    name: payload.name,
    root_path: payload.rootPath,
    is_enabled: payload.isEnabled ?? true,
    is_default: payload.isDefault ?? false,
  });
  return mapLibraryResponse(response);
}

export interface UpdateLibraryPayload {
  name?: string;
  rootPath?: string;
  isEnabled?: boolean;
  isDefault?: boolean;
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
  if (payload.isDefault !== undefined) body.is_default = payload.isDefault;

  const response = await patch<LibraryResponse>(
    `/api/web/libraries/${id}`,
    body
  );
  return mapLibraryResponse(response);
}

/**
 * Set a library as the default.
 */
export async function setDefault(id: string): Promise<Library> {
  const response = await post<LibraryResponse>(
    `/api/web/libraries/${id}/set-default`
  );
  return mapLibraryResponse(response);
}

/**
 * Delete a library.
 * Cannot delete the default library - set another as default first.
 */
export async function deleteLibrary(id: string): Promise<void> {
  await del(`/api/web/libraries/${id}`);
}

export interface PreviewOptions {
  paths?: string[];
  recursive?: boolean;
}

/**
 * Preview file count for a library path.
 */
export async function preview(
  id: string,
  options?: PreviewOptions
): Promise<{ file_count: number }> {
  const body: Record<string, unknown> = {
    recursive: options?.recursive ?? true,
  };
  if (options?.paths) {
    body.paths = options.paths;
  }

  return post<{ file_count: number }>(
    `/api/web/libraries/${id}/preview`,
    body
  );
}

/**
 * Scan a specific library.
 */
export async function scan(id: string): Promise<ScanResult> {
  return post<ScanResult>(`/api/web/libraries/${id}/scan`, {});
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
