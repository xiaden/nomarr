import { beforeEach, describe, expect, it, vi } from "vitest";

import { get } from "./client";
import { listFs } from "./filesystem";

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    get: vi.fn(),
  };
});

describe("listFs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lists the library root when no path is provided", async () => {
    const response = { path: "", entries: [] };
    vi.mocked(get).mockResolvedValue(response);

    await expect(listFs()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/file-system/list");
  });

  it("passes the path through URLSearchParams encoding for slash-separated paths", async () => {
    const response = {
      path: "Music/Rock",
      entries: [{ name: "classic-rock.mp3", is_dir: false }],
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(listFs("Music/Rock")).resolves.toEqual(response);

    // listFs builds the query with URLSearchParams, so "/" becomes %2F and
    // spaces become "+".
    expect(get).toHaveBeenCalledWith("/api/web/file-system/list?path=Music%2FRock");
  });

  it("encodes spaces as + via URLSearchParams", async () => {
    const response = { path: "a b", entries: [] };
    vi.mocked(get).mockResolvedValue(response);

    await expect(listFs("a b")).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/file-system/list?path=a+b");
  });
});
