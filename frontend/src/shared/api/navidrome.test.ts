import { beforeEach, describe, expect, it, vi } from "vitest";

import { get, post } from "./client";
import {
  generatePlaylist,
  generateTemplates,
  getConfig,
  getNavidromeStatus,
  getPreview,
  getTagValues,
  getTemplates,
  pingNavidrome,
  previewPlaylist,
  pushStaticPlaylist,
  triggerPersonalPlaylists,
} from "./navidrome";

// Mock at the wire layer: the client's `get`/`post` helpers are the request
// boundary, so asserting the exact path/body passed to them (and the
// verbatim-shaped response they resolve to) proves each client function sends
// and consumes the exact backend contract from navidrome_types.py /
// navidrome_if.py.
vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    get: vi.fn(),
    post: vi.fn(),
  };
});

describe("getTagValues", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uses the singular navidrome tag-value endpoint", async () => {
    vi.mocked(get).mockResolvedValue({ name: "genre", values: ["Rock"] });

    await expect(getTagValues("genre")).resolves.toEqual(["Rock"]);

    expect(get).toHaveBeenCalledWith("/api/web/navidrome/tag-value?name=genre");
  });
});

describe("getPreview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("consumes the {stats} dict and projects sorted tags (PreviewTagStatsResponse)", async () => {
    // PreviewTagStatsResponse{stats:dict} — the client consumes the raw stats
    // dict and transforms it into a sorted {tags} array.
    const raw = {
      stats: {
        "nom:mood": {
          type: "string",
          is_multivalue: false,
          summary: "Mood",
          total_count: 5,
          short_name: "Mood",
          field_name: "mood",
          is_versioned: false,
        },
        bpm: {
          type: "float",
          is_multivalue: false,
          summary: "BPM",
          total_count: 8,
          short_name: "BPM",
          field_name: "bpm",
          is_versioned: true,
        },
      },
    };
    vi.mocked(get).mockResolvedValue(raw);

    const result = await getPreview();

    // Sorted by short_name: BPM before Mood.
    expect(result.tags.map((t) => t.short_name)).toEqual(["BPM", "Mood"]);
    expect(result.tags[0]).toEqual({
      tag_key: "bpm",
      type: "float",
      is_multivalue: false,
      summary: "BPM",
      total_count: 8,
      short_name: "BPM",
      field_name: "bpm",
      is_versioned: true,
    });

    expect(get).toHaveBeenCalledWith("/api/web/navidrome/preview");
  });
});

describe("getConfig", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the config endpoint returning {config} with NO namespace field", async () => {
    // NavidromeConfigResponse{config:str} — no `namespace` field.
    const response = { config: "[Server]\nAddress = \"127.0.0.1\"" };
    vi.mocked(get).mockResolvedValue(response);

    const result = await getConfig();

    expect(result).toEqual({ config: response.config });
    expect(result).not.toHaveProperty("namespace");
    expect(get).toHaveBeenCalledWith("/api/web/navidrome/config");
  });
});

describe("previewPlaylist", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts the exact preview body and consumes PlaylistPreviewResponse", async () => {
    // PlaylistPreviewResponse{total_count, sample_tracks, query}
    const response = {
      total_count: 2,
      sample_tracks: [{ path: "/a.mp3", title: "A", artist: "X", album: "Y" }],
      query: 'tag:nom:mood = "happy"',
    };
    vi.mocked(post).mockResolvedValue(response);

    await expect(previewPlaylist('tag:nom:mood = "happy"', 10)).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/navidrome/playlist/preview", {
      query: 'tag:nom:mood = "happy"',
      preview_limit: 10,
    });
  });
});

describe("generatePlaylist", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts the exact generate body and returns playlist_structure with no content/query/playlist_name", async () => {
    // GeneratePlaylistResponse{playlist_structure} — backend navidrome_types.py:137-146.
    // The response type has NO content/query/playlist_name (M-7); the consumer
    // reads `playlist_structure` (see useNavidromeData.test.ts).
    const structure = { name: "My Playlist", all: [{ op: { mood: "happy" } }] };
    const response = { playlist_structure: structure };
    vi.mocked(post).mockResolvedValue(response);

    const result = await generatePlaylist({
      query: 'tag:nom:mood = "happy"',
      playlist_name: "My Playlist",
      comment: "",
      sort: "title",
      limit: 50,
    });

    expect(result).toEqual(response);
    expect(result).not.toHaveProperty("content");
    expect(result).not.toHaveProperty("query");
    expect(result).not.toHaveProperty("playlist_name");
    expect(result.playlist_structure).toEqual(structure);

    expect(post).toHaveBeenCalledWith("/api/web/navidrome/playlist/generate", {
      query: 'tag:nom:mood = "happy"',
      playlist_name: "My Playlist",
      comment: "",
      sort: "title",
      limit: 50,
    });
  });
});

describe("getTemplates", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("consumes GetTemplateSummaryResponse with template_id/name/description (no total_count/query/category/id)", async () => {
    // GetTemplateSummaryResponse{templates:[{template_id,name,description}]}
    // — backend navidrome_types.py:171-182.
    const response = {
      templates: [
        { template_id: "tpl-1", name: "Rock", description: "Rock playlist" },
        { template_id: "tpl-2", name: "Chill", description: "Chill playlist" },
      ],
    };
    vi.mocked(get).mockResolvedValue(response);

    const result = await getTemplates();

    expect(result).toEqual(response);
    expect(result).not.toHaveProperty("total_count");
    expect(result.templates[0]).toEqual({ template_id: "tpl-1", name: "Rock", description: "Rock playlist" });
    expect(result.templates[0]).not.toHaveProperty("id");
    expect(result.templates[0]).not.toHaveProperty("query");
    expect(result.templates[0]).not.toHaveProperty("category");

    expect(get).toHaveBeenCalledWith("/api/web/navidrome/template");
  });
});

describe("generateTemplates", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts to the template endpoint and returns files_generated", async () => {
    // GenerateTemplateFilesResponse{files_generated:dict} — navidrome_types.py:185-188.
    const response = { files_generated: { "tpl-1": "/tmp/rock.nsp" } };
    vi.mocked(post).mockResolvedValue(response);

    await expect(generateTemplates()).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/navidrome/template");
  });
});

describe("pushStaticPlaylist", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts the static body and consumes portable TrackDescriptor songs", async () => {
    // PushStaticPlaylistResponse{playlist_name, songs:[TrackDescriptor], track_count}
    const response = {
      playlist_name: "Vector Search Playlist",
      songs: [
        {
          title: "Song",
          artist: "Artist",
          album: "Album",
          album_artist: "Artist",
          duration_ms: 240000,
          track_number: 1,
          disc_number: 1,
          year: 2020,
          nomarr_file_key: "abc",
        },
      ],
      track_count: 1,
    };
    vi.mocked(post).mockResolvedValue(response);

    await expect(pushStaticPlaylist(["42"], "Vector Search Playlist")).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/navidrome/playlist/push", {
      file_ids: ["42"],
      playlist_name: "Vector Search Playlist",
    });
  });
});

describe("triggerPersonalPlaylists", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts the exact {top_plays} body and consumes TriggerPersonalPlaylistsResponse", async () => {
    // PersonalPlaylistsRequest{top_plays:[{file_id,playcount,last_played}]} (min_length 1)
    // — navidrome_types.py:283-288.
    const response = {
      status: "ok",
      message: "",
      playlists: [
        {
          playlist_name: "Top Tracks",
          playlist_type: "top_tracks",
          songs: [
            {
              title: "Song",
              artist: "Artist",
              album: "Album",
              album_artist: "Artist",
              duration_ms: 240000,
              track_number: 1,
              disc_number: 1,
              year: 2020,
              nomarr_file_key: "abc",
            },
          ],
          track_count: 1,
        },
      ],
    };
    vi.mocked(post).mockResolvedValue(response);

    const result = await triggerPersonalPlaylists([
      { file_id: "42", playcount: 5, last_played: 1700000000000 },
    ]);

    expect(result).toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/navidrome/generate-personal-playlists", {
      top_plays: [{ file_id: "42", playcount: 5, last_played: 1700000000000 }],
    });
  });
});

describe("pingNavidrome", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts to the ping endpoint and consumes PingResponse with nullable error", async () => {
    // PingResponse{ok, error|None}
    const response = { ok: true, error: null };
    vi.mocked(post).mockResolvedValue(response);

    await expect(pingNavidrome()).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/navidrome/ping");
  });
});

describe("getNavidromeStatus", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the status endpoint and consumes NavidromeStatusResponse{configured}", async () => {
    // NavidromeStatusResponse{configured:bool}
    const response = { configured: true };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getNavidromeStatus()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/navidrome/status");
  });
});
