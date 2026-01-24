/**
 * Files/Browse API functions.
 */

import { get, post } from "./client";

export interface FileTag {
  key: string;
  value: string;
  type: string;
  is_nomarr: boolean;
}

export interface LibraryFile {
  id: string;
  path: string;
  library_id: string;
  file_size?: number;
  modified_time?: number;
  duration_seconds?: number;
  artist?: string;
  album?: string;
  title?: string;
  calibration?: string;
  scanned_at?: number;
  last_tagged_at?: number;
  tagged: boolean;
  tagged_version?: string;
  skip_auto_tag: boolean;
  created_at?: string | number;
  updated_at?: string | number;
  tags: FileTag[];
}

export interface SearchFilesParams {
  q?: string;
  artist?: string;
  album?: string;
  tagKey?: string;
  tagValue?: string;
  taggedOnly?: boolean;
  limit?: number;
  offset?: number;
}

export interface SearchFilesResponse {
  files: LibraryFile[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * Search library files with optional filtering.
 */
export async function search(params?: SearchFilesParams): Promise<SearchFilesResponse> {
  const queryParams = new URLSearchParams();
  if (params?.q) queryParams.append("q", params.q);
  if (params?.artist) queryParams.append("artist", params.artist);
  if (params?.album) queryParams.append("album", params.album);
  if (params?.tagKey) queryParams.append("tag_key", params.tagKey);
  if (params?.tagValue) queryParams.append("tag_value", params.tagValue);
  if (params?.taggedOnly) queryParams.append("tagged_only", "true");
  if (params?.limit) queryParams.append("limit", params.limit.toString());
  if (params?.offset) queryParams.append("offset", params.offset.toString());

  const query = queryParams.toString();
  const endpoint = query
    ? `/api/web/libraries/files/search?${query}`
    : "/api/web/libraries/files/search";

  return get(endpoint);
}

/**
 * Get files by their IDs with full metadata and tags.
 * Used for batch lookup (e.g., when browsing songs for an entity).
 */
export async function getFilesByIds(fileIds: string[]): Promise<SearchFilesResponse> {
  return post("/api/web/libraries/files/by-ids", { file_ids: fileIds });
}

export interface UniqueTagKeysResponse {
  tag_keys: string[];
  count: number;
}

/**
 * Get unique tag keys for filtering.
 */
export async function getUniqueTagKeys(
  nomarrOnly = false
): Promise<UniqueTagKeysResponse> {
  const queryParams = new URLSearchParams();
  if (nomarrOnly) queryParams.append("nomarr_only", "true");

  const query = queryParams.toString();
  const endpoint = query
    ? `/api/web/libraries/files/tags/unique-keys?${query}`
    : "/api/web/libraries/files/tags/unique-keys";

  return get(endpoint);
}

export interface TagValuesResponse {
  tag_keys: string[]; // Actually values, but backend reuses same DTO
  count: number;
}

/**
 * Get unique values for a specific tag key.
 */
export async function getTagValues(
  tagKey: string,
  nomarrOnly = true
): Promise<TagValuesResponse> {
  const queryParams = new URLSearchParams();
  queryParams.append("tag_key", tagKey);
  if (nomarrOnly) queryParams.append("nomarr_only", "true");

  return get(`/api/web/libraries/files/tags/values?${queryParams.toString()}`);
}

/**
 * Get unique values for a specific tag key (alias for getTagValues).
 */
export async function getUniqueTagValues(
  tagKey: string,
  nomarrOnly = true
): Promise<TagValuesResponse> {
  return getTagValues(tagKey, nomarrOnly);
}
