import { beforeEach, describe, expect, it, vi } from "vitest";

import { get, patch, post } from "./client";
import {
  cleanupOrphanedTags,
  commitPendingTags,
  fetchPendingCount,
  fetchTagSongs,
  fetchTagValues,
  getFileTags,
  mergeTags,
  renameTag,
  splitTag,
  updateFileTags,
} from "./tagCuration";

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
  };
});

// Opaque complete-TagRef wire handles (versioned, URL-safe base64url). These are
// produced by the backend codec from canonical {name, value, namespace} JSON and
// must be treated by the frontend as opaque strings — never decoded, parsed, or
// reconstructed from name/value. The numeric/Unicode natural values below live in
// the *decoded* payload only; on the wire the frontend sees only the opaque handle
// and the separate `value` field.
const HANDLE_ELECTRONIC =
  "t1.eyJuYW1lIjoiZ2VucmUiLCJuYW1lc3BhY2UiOiJkZWZhdWx0IiwidmFsdWUiOiJFbGVjdHJvbmljIn0=";
const HANDLE_UNICODE =
  "t1.eyJuYW1lIjoiZ2VucmUiLCJuYW1lc3BhY2UiOiJkZWZhdWx0IiwidmFsdWUiOiJcdTAwYzlsZWN0cm9uaXF1ZSBcdWQ4M2RcdWRlMDAifQ==";
const HANDLE_NUMERIC =
  "t1.eyJuYW1lIjoiZ2VucmUiLCJuYW1lc3BhY2UiOiJkZWZhdWx0IiwidmFsdWUiOiIxMjAifQ==";
const HANDLE_NOM =
  "t1.eyJuYW1lIjoibW9vZCIsIm5hbWVzcGFjZSI6Im5vbSIsInZhbHVlIjoiSGFwcHkifQ==";

describe("cleanupOrphanedTags", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts to the singular cleanup-tag endpoint", async () => {
    const response = { orphaned_count: 0, deleted_count: 0 };
    vi.mocked(post).mockResolvedValue(response);

    await expect(cleanupOrphanedTags()).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/library/cleanup-tag");
  });

  it("adds ?dry_run=true when dryRun is set", async () => {
    const response = { orphaned_count: 3, deleted_count: 3 };
    vi.mocked(post).mockResolvedValue(response);

    await expect(cleanupOrphanedTags(true)).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/library/cleanup-tag?dry_run=true");
  });
});

describe("getFileTags", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the singular file tag endpoint with a URL-encoded numeric file id", async () => {
    const response = {
      file_id: 42,
      path: "/music/test.mp3",
      tags: [
        { key: "genre", value: "rock", tag_type: "string", is_nomarr: false },
      ],
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getFileTags("42")).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/library/file/42/tag");
  });

  it("adds ?nomarr_only=true when nomarrOnly is set", async () => {
    const response = { file_id: 42, path: "/music/test.mp3", tags: [] };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getFileTags("42", true)).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith(
      "/api/web/library/file/42/tag?nomarr_only=true"
    );
  });
});

describe("fetchTagValues", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uses the singular tag-curation value endpoint with exact query params", async () => {
    const response = {
      tags: [
        { id: "1", name: "genre", value: "rock", song_count: 10 },
        { id: "2", name: "genre", value: "jazz", song_count: 5 },
      ],
      total: 2,
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(
      fetchTagValues("genre", "ro", 100, 0)
    ).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith(
      "/api/web/tag-curation/value?name=genre&prefix=ro&limit=100&offset=0"
    );
  });

  it("omits optional name/prefix and applies default limit/offset", async () => {
    const response = { tags: [], total: 0 };
    vi.mocked(get).mockResolvedValue(response);

    await expect(fetchTagValues()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith(
      "/api/web/tag-curation/value?limit=100&offset=0"
    );
  });
});

describe("fetchTagSongs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uses the singular tag-curation song endpoint with an encoded tag id", async () => {
    const response = {
      songs: [
        {
          file_id: "101",
          title: "Song 1",
          artist: "Artist 1",
          album: "Album 1",
          path: "/music/song1.mp3",
        },
      ],
      total: 1,
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(fetchTagSongs("7", 50, 0)).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith(
      "/api/web/tag-curation/7/song?limit=50&offset=0"
    );
  });

  it("propagates custom limit/offset", async () => {
    const response = { songs: [], total: 0 };
    vi.mocked(get).mockResolvedValue(response);

    await expect(fetchTagSongs("7", 25, 10)).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith(
      "/api/web/tag-curation/7/song?limit=25&offset=10"
    );
  });
});

describe("renameTag", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts snake_case body to the rename endpoint", async () => {
    const response = { moved: 5, merged_into_existing: false };
    vi.mocked(post).mockResolvedValue(response);

    await expect(renameTag("1", "new_value")).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/tag-curation/rename", {
      tag_id: "1",
      new_value: "new_value",
    });
  });
});

describe("mergeTags", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts snake_case body to the merge endpoint", async () => {
    const response = { total_moved: 10, sources_removed: 2 };
    vi.mocked(post).mockResolvedValue(response);

    await expect(mergeTags(["1", "2"], "3")).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/tag-curation/merge", {
      source_tag_ids: ["1", "2"],
      canonical_tag_id: "3",
    });
  });
});

describe("splitTag", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts snake_case body to the split endpoint", async () => {
    const response = { moved: 3, new_tag_created: true };
    vi.mocked(post).mockResolvedValue(response);

    await expect(splitTag("1", ["10", "11"], "new_genre")).resolves.toEqual(
      response
    );

    expect(post).toHaveBeenCalledWith("/api/web/tag-curation/split", {
      source_tag_id: "1",
      song_ids: ["10", "11"],
      new_value: "new_genre",
    });
  });
});

describe("commitPendingTags", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts an empty body when no library is given", async () => {
    const response = { started: true, pending_files: 0 };
    vi.mocked(post).mockResolvedValue(response);

    await expect(commitPendingTags()).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/tag-curation/commit", {});
  });

  it("posts {library_id} when a library is given", async () => {
    const response = { started: true, pending_files: 5 };
    vi.mocked(post).mockResolvedValue(response);

    await expect(commitPendingTags("lib1")).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/tag-curation/commit", {
      library_id: "lib1",
    });
  });
});

describe("fetchPendingCount", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the pending-count endpoint and unwraps count", async () => {
    vi.mocked(get).mockResolvedValue({ count: 10 });

    await expect(fetchPendingCount()).resolves.toBe(10);

    expect(get).toHaveBeenCalledWith("/api/web/tag-curation/pending-count");
  });
});

describe("updateFileTags", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("patches the singular file tag endpoint with an encoded numeric file id", async () => {
    const response = {
      file_id: "42",
      name: "genre",
      tags: [{ key: "genre", value: "rock", tag_type: "string", is_nomarr: false }],
    };
    vi.mocked(patch).mockResolvedValue(response);

    await expect(updateFileTags("42", "genre", ["Rock"])).resolves.toEqual(
      response
    );

    expect(patch).toHaveBeenCalledWith(
      "/api/web/tag-curation/file/42/tag",
      { name: "genre", values: ["Rock"] }
    );
  });
});

describe("opaque complete-TagRef handle propagation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetchTagSongs URL-encodes an opaque handle byte-for-byte into the path", async () => {
    const response = { songs: [], total: 0 };
    vi.mocked(get).mockResolvedValue(response);

    await expect(fetchTagSongs(HANDLE_ELECTRONIC, 50, 0)).resolves.toEqual(
      response
    );

    // encodeURIComponent escapes the base64 '=' padding to %3D so the raw handle
    // survives transit unchanged (the backend URL-decodes it back to the original
    // '='-containing opaque string). No decoding/parsing happens client-side.
    expect(get).toHaveBeenCalledWith(
      `/api/web/tag-curation/${encodeURIComponent(HANDLE_ELECTRONIC)}/song?limit=50&offset=0`
    );
    // Confirm the assertion is concrete (the '=' really is escaped, not left raw).
    expect(encodeURIComponent(HANDLE_ELECTRONIC)).toContain("%3D");
  });

  it("renameTag forwards the opaque handle unchanged as tag_id with a numeric natural new_value string", async () => {
    const response = { moved: 5, merged_into_existing: false };
    vi.mocked(post).mockResolvedValue(response);

    await expect(renameTag(HANDLE_NUMERIC, "120")).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/tag-curation/rename", {
      tag_id: HANDLE_NUMERIC,
      new_value: "120",
    });
    // Both are plain strings — never parsed into numbers or storage ids.
    const [, body] = vi.mocked(post).mock.calls[0] as unknown as [
      unknown,
      { tag_id: unknown; new_value: unknown }
    ];
    expect(typeof body.tag_id).toBe("string");
    expect(typeof body.new_value).toBe("string");
  });

  it("mergeTags forwards distinct opaque handles unchanged for sources and canonical", async () => {
    const response = { total_moved: 10, sources_removed: 1 };
    vi.mocked(post).mockResolvedValue(response);

    await expect(mergeTags([HANDLE_ELECTRONIC, HANDLE_NUMERIC], HANDLE_NOM)).resolves.toEqual(
      response
    );

    expect(post).toHaveBeenCalledWith("/api/web/tag-curation/merge", {
      source_tag_ids: [HANDLE_ELECTRONIC, HANDLE_NUMERIC],
      canonical_tag_id: HANDLE_NOM,
    });
  });

  it("splitTag forwards the opaque source handle and a special-character new value unchanged", async () => {
    const response = { moved: 3, new_tag_created: true };
    vi.mocked(post).mockResolvedValue(response);

    await expect(splitTag(HANDLE_UNICODE, ["10", "11"], "Électronique 😀")).resolves.toEqual(
      response
    );

    expect(post).toHaveBeenCalledWith("/api/web/tag-curation/split", {
      source_tag_id: HANDLE_UNICODE,
      song_ids: ["10", "11"],
      new_value: "Électronique 😀",
    });
  });

  it("fetchTagValues keeps each opaque id distinct from its separate value field (unicode, numeric, nom)", async () => {
    const rows = [
      { id: HANDLE_ELECTRONIC, name: "genre", value: "Electronic", song_count: 4 },
      { id: HANDLE_UNICODE, name: "genre", value: "Électronique 😀", song_count: 2 },
      { id: HANDLE_NUMERIC, name: "genre", value: "120", song_count: 9 },
      { id: HANDLE_NOM, name: "mood", value: "Happy", song_count: 7 },
    ];
    vi.mocked(get).mockResolvedValue({ tags: rows, total: rows.length });

    const result = await fetchTagValues();

    // Ids are opaque handles that never equal their natural value, and identical
    // (name,value) would still differ across namespaces — here value "Happy" in nom
    // has its own id. Every field keeps its declared type (id/value string, count int).
    result.tags.forEach((row) => {
      expect(typeof row.id).toBe("string");
      expect(row.id.startsWith("t1.")).toBe(true);
      expect(typeof row.value).toBe("string");
      expect(typeof row.song_count).toBe("number");
    });
    expect(result.tags.map((t) => t.id)).toEqual([
      HANDLE_ELECTRONIC,
      HANDLE_UNICODE,
      HANDLE_NUMERIC,
      HANDLE_NOM,
    ]);
    expect(result.tags.map((t) => t.id)).not.toEqual(
      result.tags.map((t) => t.value)
    );
  });
});
