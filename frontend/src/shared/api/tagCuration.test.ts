import { beforeEach, describe, expect, it, vi } from "vitest";

import { get, patch, post } from "./client";
import {
  cleanupOrphanedTags,
  fetchTagSongs,
  fetchTagValues,
  getFileTags,
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
});

describe("getFileTags", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the singular file tag endpoint", async () => {
    const response = { file_id: "file-123", path: "/music/test.mp3", tags: [] };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getFileTags("file-123")).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/library/file/file-123/tag");
  });
});

describe("fetchTagValues", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uses the singular tag-curation value endpoint", async () => {
    const response = { tags: [], total: 0 };
    vi.mocked(get).mockResolvedValue(response);

    await expect(fetchTagValues("genre")).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith(expect.stringContaining("/tag-curation/value?"));
  });
});

describe("fetchTagSongs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uses the singular tag-curation song endpoint", async () => {
    const response = { songs: [], total: 0 };
    vi.mocked(get).mockResolvedValue(response);

    await expect(fetchTagSongs("tag-1")).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith(expect.stringContaining("/tag-curation/"));
    expect(get).toHaveBeenCalledWith(expect.stringContaining("/song?"));
  });
});

describe("updateFileTags", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("patches the singular file tag endpoint", async () => {
    const response = { tags: [] };
    vi.mocked(patch).mockResolvedValue(response);

    await expect(updateFileTags("file-1", "genre", ["Rock"])).resolves.toEqual(response);

    expect(patch).toHaveBeenCalledWith(
      expect.stringContaining("/tag-curation/file/"),
      expect.objectContaining({ name: "genre", values: ["Rock"] }),
    );
    expect(patch).toHaveBeenCalledWith(
      expect.stringContaining("/tag"),
      expect.objectContaining({ name: "genre", values: ["Rock"] }),
    );
  });
});
