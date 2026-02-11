/**
 * Playlist Import API functions.
 *
 * Converts Spotify/Deezer playlists to M3U by matching against local library.
 */

import { get, post } from "./client";

// Match tier indicates how the track was matched
export type MatchTier = "isrc" | "exact" | "fuzzy_high" | "fuzzy_low" | "none";

export interface MatchResultResponse {
  input_title: string;
  input_artist: string;
  matched: boolean;
  tier: MatchTier;
  confidence: number;
  matched_file_path: string | null;
  alternatives_count: number;
}

export interface PlaylistMetadataResponse {
  name: string;
  description: string | null;
  track_count: number;
  platform: string;
  url: string;
}

export interface ConvertPlaylistResponse {
  playlist: PlaylistMetadataResponse;
  results: MatchResultResponse[];
  matched_count: number;
  unmatched_count: number;
  m3u_content: string;
}

export interface SpotifyStatusResponse {
  configured: boolean;
}

export interface ConvertPlaylistRequest {
  url: string;
  library_id: string;
  min_confidence?: number;
  generate_m3u?: boolean;
}

/**
 * Convert a Spotify or Deezer playlist to M3U.
 */
export async function convertPlaylist(
  params: ConvertPlaylistRequest
): Promise<ConvertPlaylistResponse> {
  return post("/api/web/playlist-import/convert", params);
}

/**
 * Check if Spotify credentials are configured.
 */
export async function getSpotifyStatus(): Promise<SpotifyStatusResponse> {
  return get("/api/web/playlist-import/spotify-status");
}
