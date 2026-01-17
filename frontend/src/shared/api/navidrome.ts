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
}

export interface NavidromePreviewResponse {
  namespace: string;
  tag_count: number;
  tags: NavidromeTag[];
}

/**
 * Get preview of tags for Navidrome config.
 */
export async function getPreview(): Promise<NavidromePreviewResponse> {
  return get("/api/web/navidrome/preview");
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

/**
 * Preview Smart Playlist query results.
 */
export async function previewPlaylist(
  query: string,
  previewLimit = 10
): Promise<Record<string, unknown>> {
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
