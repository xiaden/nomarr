/**
 * Tag Curation API functions.
 */

import { get, patch, post } from "./client";
import type { FileTag } from "./files";

// ──────────────────────────────────────────────────────────────────────────────
// Types mirroring backend DTOs (helpers/dto/tag_curation_dto.py)
// ──────────────────────────────────────────────────────────────────────────────

export interface TagValueItem {
  id: string;
  name: string;
  value: string;
  song_count: number;
}

export interface TagListResult {
  tags: TagValueItem[];
  total: number;
}

export interface RenameResult {
  moved: number;
  merged_into_existing: boolean;
}

export interface MergeResult {
  total_moved: number;
  sources_removed: number;
}

export interface SplitResult {
  moved: number;
  new_tag_created: boolean;
}

export interface CommitResult {
  started: boolean;
  pending_files: number;
}

export interface TagSongItem {
  file_id: string;
  title: string;
  artist: string;
  album: string;
}

export interface TagSongsResult {
  songs: TagSongItem[];
  total: number;
}

export interface UpdateFileTagsResult {
  tags: FileTag[];
}

// ──────────────────────────────────────────────────────────────────────────────
// Migrated from library.ts — URLs unchanged (backend still serves from original paths)
// ──────────────────────────────────────────────────────────────────────────────

export interface CleanupTagsResult {
  orphaned_count: number;
  deleted_count: number;
}

export interface FileTagsResult {
  file_id: string;
  path: string;
  tags: FileTag[];
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
    ? `/api/web/library/cleanup-tag?${query}`
    : "/api/web/library/cleanup-tag";

  return post(endpoint);
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
    ? `/api/web/library/file/${fileId}/tag?${query}`
    : `/api/web/library/file/${fileId}/tag`;

  return get(endpoint);
}

// ──────────────────────────────────────────────────────────────────────────────
// Tag Curation API
// ──────────────────────────────────────────────────────────────────────────────

/**
 * Fetch paginated tag values, optionally filtered by rel and prefix.
 */
export async function fetchTagValues(
  rel?: string,
  prefix?: string,
  limit = 100,
  offset = 0
): Promise<TagListResult> {
  const params = new URLSearchParams();
  if (rel) params.append("rel", rel);
  if (prefix) params.append("prefix", prefix);
  params.append("limit", String(limit));
  params.append("offset", String(offset));
  return get(`/api/web/tag-curation/value?${params.toString()}`);
}

/**
 * Fetch songs associated with a tag, with pagination.
 */
export async function fetchTagSongs(
  tagId: string,
  limit = 50,
  offset = 0
): Promise<TagSongsResult> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  return get(
    `/api/web/tag-curation/${encodeURIComponent(tagId)}/song?${params.toString()}`
  );
}

/**
 * Rename a tag to a new value. Returns move count and whether it merged.
 */
export async function renameTag(
  tagId: string,
  newValue: string
): Promise<RenameResult> {
  return post("/api/web/tag-curation/rename", {
    tag_id: tagId,
    new_value: newValue,
  });
}

/**
 * Merge multiple source tags into a single canonical tag.
 */
export async function mergeTags(
  sourceTagIds: string[],
  canonicalTagId: string
): Promise<MergeResult> {
  return post("/api/web/tag-curation/merge", {
    source_tag_ids: sourceTagIds,
    canonical_tag_id: canonicalTagId,
  });
}

/**
 * Split a subset of songs from a tag into a new tag value.
 */
export async function splitTag(
  sourceTagId: string,
  songIds: string[],
  newValue: string
): Promise<SplitResult> {
  return post("/api/web/tag-curation/split", {
    source_tag_id: sourceTagId,
    song_ids: songIds,
    new_value: newValue,
  });
}

/**
 * Commit pending tag changes to audio files.
 */
export async function commitPendingTags(
  libraryId?: string
): Promise<CommitResult> {
  return post("/api/web/tag-curation/commit", libraryId ? { library_id: libraryId } : {});
}

/**
 * Get the number of files with pending tag write-backs.
 */
export async function fetchPendingCount(): Promise<number> {
  const response = await get<{ count: number }>("/api/web/tag-curation/pending-count");
  return response.count;
}

/**
 * Update the tag values for a specific rel on a file.
 */
export async function updateFileTags(
  fileId: string,
  name: string,
  values: string[]
): Promise<UpdateFileTagsResult> {
  return patch(
    `/api/web/tag-curation/file/${encodeURIComponent(fileId)}/tag`,
    { name, values }
  );
}
