/**
 * Navidrome API functions.
 */

import { get, post } from "./client";

export interface NavidromeTag {
  tag_key: string;
  type: string;
  is_multivalue: boolean;
  summary: string;
  total_count: number;
  short_name: string;
  field_name: string;
  is_versioned: boolean;
}

interface NavidromePreviewRawResponse {
  stats: Record<string, {
    type: string;
    is_multivalue: boolean;
    summary: string;
    total_count: number;
    short_name: string;
    field_name: string;
    is_versioned: boolean;
  }>;
}

export interface NavidromePreviewResponse {
  tags: NavidromeTag[];
}

/**
 * Get preview of tags for Navidrome config.
 * Transforms backend stats dict into sorted tags array.
 */
export async function getPreview(): Promise<NavidromePreviewResponse> {
  const raw = await get<NavidromePreviewRawResponse>("/api/web/navidrome/preview");
  const tags = Object.entries(raw.stats)
    .map(([tag_key, stat]) => ({
      tag_key,
      type: stat.type,
      is_multivalue: stat.is_multivalue,
      summary: stat.summary,
      total_count: stat.total_count,
      short_name: stat.short_name,
      field_name: stat.field_name,
      is_versioned: stat.is_versioned,
    }))
    .sort((a, b) => a.short_name.localeCompare(b.short_name));
  return { tags };
}

export interface NavidromeConfigResponse {
  namespace: string;
  config: string;
}

/**
 * Generate Navidrome TOML configuration.
 */
export async function getConfig(): Promise<NavidromeConfigResponse> {
  return get("/api/web/navidrome/config");
}

export interface PlaylistPreviewResponse {
  total_count: number;
  sample_tracks: Array<Record<string, string>>;
  query: string;
}

/**
 * Preview Smart Playlist query results.
 */
export async function previewPlaylist(
  query: string,
  previewLimit = 10
): Promise<PlaylistPreviewResponse> {
  return post("/api/web/navidrome/playlists/preview", {
    query,
    preview_limit: previewLimit,
  });
}

export interface GeneratePlaylistParams {
  query: string;
  playlist_name: string;
  comment?: string;
  limit?: number;
  sort?: string;
}

export interface GeneratePlaylistResponse {
  playlist_name: string;
  query: string;
  content: string;
}

/**
 * Generate Navidrome Smart Playlist (.nsp).
 */
export async function generatePlaylist(
  params: GeneratePlaylistParams
): Promise<GeneratePlaylistResponse> {
  return post("/api/web/navidrome/playlists/generate", params);
}

export interface PlaylistTemplate {
  id: string;
  name: string;
  description: string;
  query: string;
  category?: string;
}

export interface GetTemplatesResponse {
  templates: PlaylistTemplate[];
  total_count: number;
}

/**
 * Get list of all available playlist templates.
 */
export async function getTemplates(): Promise<GetTemplatesResponse> {
  return get("/api/web/navidrome/templates");
}

export interface GeneratedTemplate {
  id: string;
  name: string;
  filename: string;
  success: boolean;
  error?: string;
}

export interface GenerateTemplatesResponse {
  templates: GeneratedTemplate[];
  total_count: number;
}

/**
 * Generate all playlist templates as a batch.
 */
export async function generateTemplates(): Promise<GenerateTemplatesResponse> {
  return post("/api/web/navidrome/templates");
}


// ── Tag Stats (for rules engine) ──

export interface TagStatEntry {
  key: string;
  type: "float" | "integer" | "string" | "unknown";
  is_multivalue: boolean;
  summary: string;
  total_count: number;
  short_name: string;
  field_name: string;
  is_versioned: boolean;
}

interface TagStatsRawResponse {
  stats: Record<string, {
    type: string;
    is_multivalue: boolean;
    summary: string;
    total_count: number;
    short_name: string;
    field_name: string;
    is_versioned: boolean;
  }>;
}

/**
 * Get tag metadata for the rules engine.
 * Transforms the backend stats dict into a sorted array of TagStatEntry.
 * Sorts by short_name for user-friendly display.
 */
export async function getTagStats(): Promise<TagStatEntry[]> {
  const raw = await get<TagStatsRawResponse>("/api/web/navidrome/preview");
  return Object.entries(raw.stats)
    .map(([key, stat]) => ({
      key,
      type: stat.type as TagStatEntry["type"],
      is_multivalue: stat.is_multivalue,
      summary: stat.summary,
      total_count: stat.total_count,
      short_name: stat.short_name,
      field_name: stat.field_name,
      is_versioned: stat.is_versioned,
    }))
    .sort((a, b) => a.short_name.localeCompare(b.short_name));
}


// ── Tag Values (for rules engine combobox) ──

interface TagValuesRawResponse {
  rel: string;
  values: string[];
}

/**
 * Get distinct values for a specific tag relationship.
 * Used by the rules engine combobox for autocomplete.
 */
export async function getTagValues(rel: string): Promise<string[]> {
  const raw = await get<TagValuesRawResponse>(
    `/api/web/navidrome/tag-values?rel=${encodeURIComponent(rel)}`,
  );
  return raw.values;
}