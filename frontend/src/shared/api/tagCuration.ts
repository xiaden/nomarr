/**
 * Tag Curation API functions.
 */

import { get, patch, post } from "./client";
import type { FileTag } from "./files";

// ──────────────────────────────────────────────────────────────────────────────
// Types mirroring backend DTOs (helpers/dto/tag_curation_dto.py)
// ──────────────────────────────────────────────────────────────────────────────

/**
 * A single listed tag value row.
 *
 * `id` is an OPAQUE complete-TagRef wire handle (a versioned, URL-safe
 * base64url string, e.g. `t1....`) that the backend encodes at the HTTP
 * boundary from the full natural identity `(name, value, namespace)`. It
 * contains no storage primary key and must NEVER be decoded, parsed, split,
 * base64-decoded, re-encoded, or reconstructed from `name`/`value`. The row's
 * natural identity for display is carried by the separate `name`/`value`
 * fields; `id` is purely an opaque, refreshable row/action key.
 *
 * Every listed item always carries an `id` (the backend `TagValueItemResponse`
 * requires it), so the frontend never needs to fall back to `value` when `id`
 * is absent.
 */
export interface TagValueItem {
  /** Opaque complete-TagRef handle (string). Forward unchanged; never parse. */
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
  path: string;
}

export interface TagSongsResult {
  songs: TagSongItem[];
  total: number;
}

export interface UpdateFileTagsResult {
  file_id: string;
  name: string;
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
  file_id: number;
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
  const encodedFileId = encodeURIComponent(fileId);
  const endpoint = query
    ? `/api/web/library/file/${encodedFileId}/tag?${query}`
    : `/api/web/library/file/${encodedFileId}/tag`;

  return get(endpoint);
}

// ──────────────────────────────────────────────────────────────────────────────
// Tag Curation API
//
// Wire-handle contract (see artifacts/designs/parts/tag-curation-identity-mismatch/CONTRACTS.md):
//
//   - Every tag identifier on the wire (`TagValueItem.id`, `tag_id`,
//     `source_tag_ids`, `canonical_tag_id`, `source_tag_id`) is an OPAQUE
//     complete-TagRef handle string (e.g. `t1.<base64url>`), never a storage
//     primary key and never the bare natural value. Two tags with identical
//     (name, value) in different namespaces (default vs nom) yield DIFFERENT
//     handles.
//   - The frontend MUST forward these strings UNCHANGED to query params / request
//     bodies and MUST NOT decode, parse, split, base64-decode, re-encode,
//     substring, or reconstruct them. Never derive an id from name/value; never
//     fall back to `value` when an `id` is absent. After a rename the old handle
//     stops resolving (no longer yields songs); a refreshed listing emits the new
//     identity's handle, so treat the id as an opaque, refreshable key.
//   - All wire fields stay strings. No client-side encoding of tag identities.
// ──────────────────────────────────────────────────────────────────────────────

/**
 * Fetch paginated tag values, optionally filtered by name and prefix.
 */
export async function fetchTagValues(
  name?: string,
  prefix?: string,
  limit = 100,
  offset = 0
): Promise<TagListResult> {
  const params = new URLSearchParams();
  if (name) params.append("name", name);
  if (prefix) params.append("prefix", prefix);
  params.append("limit", String(limit));
  params.append("offset", String(offset));
  return get(`/api/web/tag-curation/value?${params.toString()}`);
}

/**
 * Fetch songs associated with a tag, with pagination.
 *
 * `tagId` is an opaque complete-TagRef handle (string). It is URL-encoded only
 * for transit and forwarded unchanged as the path segment; never decode, parse,
 * or reconstruct it from the row's name/value.
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
 *
 * `tagId` is an opaque complete-TagRef handle (string), forwarded unchanged as
 * the request's `tag_id` body field. After a successful rename the old handle no
 * longer resolves (it no longer yields songs); callers must refetch the listing
 * to obtain the new identity's handle.
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
 *
 * `sourceTagIds` and `canonicalTagId` are opaque complete-TagRef handles
 * (strings), forwarded unchanged as `source_tag_ids` / `canonical_tag_id` body
 * fields. `canonicalTagId` may equal the backend id of a listed source tag; the
 * caller (not this client) decides which listed ids are sources vs canonical.
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
 *
 * `sourceTagId` is an opaque complete-TagRef handle (string). It is forwarded
 * unchanged as the request's `source_tag_id` body field; never decode, parse,
 * or reconstruct it from `newValue` or the tag's name. `songIds` are song ids
 * (a distinct boundary contract) and are not reinterpreted as tag ids.
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
