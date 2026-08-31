import { beforeEach, describe, expect, it, vi } from "vitest";

import { get } from "./client";
import { getCounts, getEntity, listAlbumsForArtist, listEntities, listSongsForEntity } from "./metadata";

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

  it("uses the singular song endpoint and returns backend-shaped song_ids pagination", async () => {
    const response = { song_ids: [1, 2, 3], total: 3, limit: 100, offset: 0 };
    vi.mocked(get).mockResolvedValue(response);

    await expect(
      listSongsForEntity("artist", "AC/DC", "Back in Black")
    ).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith(
      "/api/web/metadata/artist/AC%2FDC/song?name=Back+in+Black"
    );
  });

  it("URL-encodes a natural entity id and passes pagination options", async () => {
    const response = { song_ids: [], total: 0, limit: 25, offset: 50 };
    vi.mocked(get).mockResolvedValue(response);

    await expect(
      listSongsForEntity("album", "Highway to Hell", "Highway to Hell", {
        limit: 25,
        offset: 50,
      })
    ).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith(
      "/api/web/metadata/album/Highway%20to%20Hell/song?name=Highway+to+Hell&limit=25&offset=50"
    );
  });

  it("supports a numeric entity id in the encoded path", async () => {
    const response = { song_ids: [9], total: 1, limit: 100, offset: 0 };
    vi.mocked(get).mockResolvedValue(response);

    await expect(listSongsForEntity("artist", 7, "Some Name")).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith(
      "/api/web/metadata/artist/7/song?name=Some+Name"
    );
  });
});

describe("getEntity", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uses the singular entity endpoint with an encoded natural entity id", async () => {
    const response = { entity_id: "AC/DC", display_name: "AC/DC", song_count: 200 };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getEntity("artist", "AC/DC")).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/metadata/artist/AC%2FDC");
  });

  it("supports a numeric entity id in the encoded path", async () => {
    const response = { entity_id: 7, display_name: "Artist 7" };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getEntity("artist", 7)).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/metadata/artist/7");
  });
});

describe("listAlbumsForArtist", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uses the singular artist-to-album traversal endpoint with an encoded natural artist id", async () => {
    const response = [
      { entity_id: 5, display_name: "Back in Black", song_count: 10 },
    ];
    vi.mocked(get).mockResolvedValue(response);

    await expect(listAlbumsForArtist("AC/DC")).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith(
      "/api/web/metadata/artist/AC%2FDC/album?limit=100"
    );
  });

  it("passes a numeric artist id and custom limit", async () => {
    const response = [
      { entity_id: "Some Album", display_name: "Some Album", song_count: 3 },
    ];
    vi.mocked(get).mockResolvedValue(response);

    await expect(listAlbumsForArtist(9, 50)).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith(
      "/api/web/metadata/artist/9/album?limit=50"
    );
  });
});
