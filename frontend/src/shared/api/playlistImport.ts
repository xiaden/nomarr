/**
 * Playlist Import API functions.
 *
 * Converts Spotify/Deezer playlists to M3U by matching against local library.
 */

import { get, post } from "./client";

// Match status from backend
export type MatchStatus = "exact_isrc" | "exact_metadata" | "fuzzy" | "ambiguous" | "not_found";

// Simplified tier for UI display
export type MatchTier = "isrc" | "exact" | "fuzzy_high" | "fuzzy_low" | "none";

export interface PlaylistTrackInputResponse {
  title: string;
  artist: string;
  album: string | null;
  isrc: string | null;
  position: number;
}

export interface MatchedFileInfoResponse {
  path: string;
  file_id: string;
  title: string;
  artist: string;
  album: string | null;
}

export interface MatchResultResponse {
  input_track: PlaylistTrackInputResponse;
  status: MatchStatus;
  confidence: number;
  matched_file: MatchedFileInfoResponse | null;
  alternatives: MatchedFileInfoResponse[];
}

export interface PlaylistMetadataResponse {
  name: string;
  description: string | null;
  track_count: number;
  source_platform: string;
  source_url: string;
}

export interface ConvertPlaylistResponse {
  playlist_metadata: PlaylistMetadataResponse;
  m3u_content: string;
  total_tracks: number;
  matched_count: number;
  exact_matches: number;
  fuzzy_matches: number;
  ambiguous_count: number;
  not_found_count: number;
  match_rate: number;
  unmatched_tracks: PlaylistTrackInputResponse[];
  ambiguous_matches: MatchResultResponse[];
  all_matches: MatchResultResponse[];
}

// Helper to convert backend status to UI tier
export function statusToTier(status: MatchStatus): MatchTier {
  switch (status) {
    case "exact_isrc":
      return "isrc";
    case "exact_metadata":
      return "exact";
    case "fuzzy":
      return "fuzzy_high";
    case "ambiguous":
      return "fuzzy_low";
    case "not_found":
      return "none";
  }
}

export interface SpotifyStatusResponse {
  configured: boolean;
}

export interface ConvertPlaylistRequest {
  playlist_url: string;
  library_id: string | null;
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
