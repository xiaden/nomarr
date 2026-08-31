import { beforeEach, describe, expect, it, vi } from "vitest";

import { get, post } from "./client";
import { convertPlaylist, getSpotifyStatus } from "./playlistImport";

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    get: vi.fn(),
    post: vi.fn(),
  };
});

describe("convertPlaylist", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts the snake_case convert body and returns the backend-shaped response", async () => {
    const body = {
      playlist_url: "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
      library_id: "My Library",
    };
    const response = {
      playlist_metadata: {
        name: "Chill Mix",
        description: null,
        track_count: 10,
        source_platform: "spotify",
        source_url: body.playlist_url,
      },
      m3u_content: "#EXTM3U\n...",
      total_tracks: 10,
      matched_count: 8,
      exact_matches: 6,
      fuzzy_matches: 2,
      ambiguous_count: 1,
      not_found_count: 1,
      match_rate: 0.8,
      unmatched_tracks: [],
      ambiguous_matches: [],
      all_matches: [],
    };
    vi.mocked(post).mockResolvedValue(response);

    await expect(convertPlaylist(body)).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/playlist-import/convert", body);
  });

  it("sends library_id: null when no library scope is given", async () => {
    const body = { playlist_url: "https://open.spotify.com/playlist/xyz", library_id: null };
    const response = {
      playlist_metadata: {
        name: "Test",
        description: null,
        track_count: 0,
        source_platform: "deezer",
        source_url: body.playlist_url,
      },
      m3u_content: "",
      total_tracks: 0,
      matched_count: 0,
      exact_matches: 0,
      fuzzy_matches: 0,
      ambiguous_count: 0,
      not_found_count: 0,
      match_rate: 0,
      unmatched_tracks: [],
      ambiguous_matches: [],
      all_matches: [],
    };
    vi.mocked(post).mockResolvedValue(response);

    await expect(convertPlaylist(body)).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/playlist-import/convert", {
      playlist_url: "https://open.spotify.com/playlist/xyz",
      library_id: null,
    });
  });
});

describe("getSpotifyStatus", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets both configured and message from the spotify-status endpoint", async () => {
    const response = {
      configured: true,
      message: "Spotify credentials configured - ready to convert Spotify playlists",
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getSpotifyStatus()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/playlist-import/spotify-status");
  });
});
