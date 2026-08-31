import { beforeEach, describe, expect, it, vi } from "vitest";

import { get, post } from "./client";
import {
  getFilesByIds,
  getMoodValues,
  getTagValues,
  getUniqueTagKeys,
  search,
  searchByTag,
} from "./files";

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    get: vi.fn(),
    post: vi.fn(),
  };
});

describe("search", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the singular file search endpoint with backend-shaped file entries", async () => {
    const response = {
      files: [
        {
          file_id: 42,
          path: "/music/house.mp3",
          library_id: 7,
          duration_seconds: 240.5,
          artist: "Some Artist",
          album: "Some Album",
          title: "House Track",
          calibration_version: "v3.2",
          tagged: true,
          skip_auto_tag: false,
          tags: [],
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(search()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/library/file/search");
  });
});

describe("getFilesByIds", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts numeric encoded file ids to the singular file by-ids endpoint", async () => {
    const response = { files: [], total: 0, limit: 2, offset: 0 };
    vi.mocked(post).mockResolvedValue(response);

    await expect(getFilesByIds([1, 2])).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/library/file/by-ids", {
      file_ids: [1, 2],
    });
  });
});

describe("searchByTag", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts to the singular file by-tag endpoint", async () => {
    const params = { tag_key: "genre", target_value: "house", limit: 10, offset: 0 };
    const response = { files: [], total: 0, limit: 10, offset: 0 };
    vi.mocked(post).mockResolvedValue(response);

    await expect(searchByTag(params)).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/library/file/by-tag", params);
  });
});

describe("getUniqueTagKeys", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the singular file tag unique-keys endpoint", async () => {
    const response = { tag_keys: [], count: 0 };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getUniqueTagKeys()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/library/file/tag/unique-keys");
  });
});

describe("getTagValues", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the singular file tag values endpoint", async () => {
    const response = { tag_keys: [], count: 0 };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getTagValues("genre")).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith(
      "/api/web/library/file/tag/values?tag_key=genre&nomarr_only=true"
    );
  });
});

describe("getMoodValues", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the singular file tag mood-values endpoint", async () => {
    const response = { tag_keys: [], count: 0 };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getMoodValues()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith(
      "/api/web/library/file/tag/mood-values?mood_tier=mood-strict&limit=100"
    );
  });
});
