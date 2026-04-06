import { beforeEach, describe, expect, it, vi } from "vitest";

import { get } from "./client";
import { getCounts, listEntities, listSongsForEntity } from "./metadata";

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    get: vi.fn(),
  };
});

describe("getCounts", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the metadata count endpoint", async () => {
    const response = {
      artists: 0,
      albums: 0,
      labels: 0,
      genres: 0,
      years: 0,
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getCounts()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/metadata/count");
  });
});

describe("listEntities", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uses the singular artist metadata endpoint", async () => {
    const response = { entities: [], total: 0, limit: 100, offset: 0 };
    vi.mocked(get).mockResolvedValue(response);

    await expect(listEntities("artist")).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/metadata/artist");
  });

  it("uses the singular album metadata endpoint", async () => {
    const response = { entities: [], total: 0, limit: 100, offset: 0 };
    vi.mocked(get).mockResolvedValue(response);

    await expect(listEntities("album")).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/metadata/album");
  });

  it("includes query params when listing entities with filters", async () => {
    const response = { entities: [], total: 1, limit: 10, offset: 0 };
    vi.mocked(get).mockResolvedValue(response);

    await expect(listEntities("artist", { search: "foo", limit: 10 })).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/metadata/artist?limit=10&search=foo");
  });
});

describe("listSongsForEntity", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uses the singular song endpoint for entity song lists", async () => {
    const response = { songs: [], total: 0 };
    vi.mocked(get).mockResolvedValue(response);

    await expect(listSongsForEntity("artist", "artist-1", "genre")).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith(expect.stringContaining("/song?"));
  });
});
