import { beforeEach, describe, expect, it, vi } from "vitest";

import { del, get } from "./client";
import { removeTags, showTags } from "./tags";

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    get: vi.fn(),
    del: vi.fn(),
  };
});

describe("showTags", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets tags for a file with the path encoded in the query", async () => {
    const response = {
      path: "/music/My Track.mp3",
      namespace: "nom",
      tags: { mood: "happy" },
      count: 1,
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(showTags("/music/My Track.mp3")).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith(
      "/api/web/tag/show?path=%2Fmusic%2FMy%20Track.mp3"
    );
  });
});

describe("removeTags", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("removes tags for a file with the path encoded in the query", async () => {
    const response = {
      path: "/music/My Track.mp3",
      namespace: "nom",
      removed: 3,
    };
    vi.mocked(del).mockResolvedValue(response);

    await expect(removeTags("/music/My Track.mp3")).resolves.toEqual(response);

    expect(del).toHaveBeenCalledWith(
      "/api/web/tag/remove?path=%2Fmusic%2FMy%20Track.mp3"
    );
  });
});
