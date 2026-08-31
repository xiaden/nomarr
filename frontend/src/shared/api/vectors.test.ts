import { beforeEach, describe, expect, it, vi } from "vitest";

import { get, post } from "./client";
import {
  getTrackVector,
  getVectorStats,
  listBackbones,
  promoteVectors,
  rebuildVectorIndex,
  searchVectors,
} from "./vectors";

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    get: vi.fn(),
    post: vi.fn(),
  };
});

describe("listBackbones", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the singular vector backbone endpoint", async () => {
    const response = { backbones: [] };
    vi.mocked(get).mockResolvedValue(response);

    await expect(listBackbones()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/vector/backbone");
  });
});

describe("getVectorStats", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the singular vector stats endpoint", async () => {
    const response = { stats: [] };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getVectorStats()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/vector/stats");
  });
});

describe("searchVectors", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts the exact body without library_scope and returns numeric encoded file ids", async () => {
    const response = {
      results: [{ file_id: 42, score: 0.91, vector: [0.1, 0.2, 0.3] }],
    };
    vi.mocked(post).mockResolvedValue(response);

    await expect(searchVectors("effnet", "42", 5, 0.5)).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/vector/search", {
      file_id: "42",
      backbone_id: "effnet",
      limit: 5,
      min_score: 0.5,
    });

    const body = vi.mocked(post).mock.calls[0][1];
    expect(body).not.toHaveProperty("library_scope");
  });

  it("uses backend defaults when limit and min_score are omitted", async () => {
    const response = { results: [] };
    vi.mocked(post).mockResolvedValue(response);

    await expect(searchVectors("yamnet", "99")).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/vector/search", {
      file_id: "99",
      backbone_id: "yamnet",
      limit: 10,
      min_score: 0.0,
    });
  });
});

describe("getTrackVector", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the singular vector track endpoint and returns a numeric encoded file id", async () => {
    const response = { file_id: 42, backbone_id: "effnet", vector: [0.5, 0.5] };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getTrackVector("effnet", "42")).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith(
      "/api/web/vector/track?backbone_id=effnet&file_id=42"
    );
  });
});

describe("promoteVectors", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts the {backbone_id, nlists} body and consumes VectorPromoteResponse", async () => {
    // VectorPromoteResponse{status, backbone_id, message} — vectors_if.py:151-168.
    const response = {
      status: "success",
      backbone_id: "effnet",
      message: "Vectors promoted and index rebuilt for backbone 'effnet'",
    };
    vi.mocked(post).mockResolvedValue(response);

    await expect(promoteVectors("effnet", 100)).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/vector/promote", {
      backbone_id: "effnet",
      nlists: 100,
    });
  });

  it("sends nlists: null when omitted (auto-calculated server-side)", async () => {
    const response = {
      status: "success",
      backbone_id: "yamnet",
      message: "Vectors promoted and index rebuilt for backbone 'yamnet'",
    };
    vi.mocked(post).mockResolvedValue(response);

    await expect(promoteVectors("yamnet")).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/vector/promote", {
      backbone_id: "yamnet",
      nlists: null,
    });
  });
});

describe("rebuildVectorIndex", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts the {backbone_id, nlists} body and consumes VectorRebuildIndexResponse", async () => {
    // VectorRebuildIndexResponse{status, backbone_id, message} — vectors_if.py:183-200.
    const response = {
      status: "success",
      backbone_id: "effnet",
      message: "Vector index rebuilt for backbone 'effnet'",
    };
    vi.mocked(post).mockResolvedValue(response);

    await expect(rebuildVectorIndex("effnet", 250)).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/vector/rebuild-index", {
      backbone_id: "effnet",
      nlists: 250,
    });
  });

  it("sends nlists: null when omitted (auto-calculated server-side)", async () => {
    const response = {
      status: "success",
      backbone_id: "yamnet",
      message: "Vector index rebuilt for backbone 'yamnet'",
    };
    vi.mocked(post).mockResolvedValue(response);

    await expect(rebuildVectorIndex("yamnet")).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/vector/rebuild-index", {
      backbone_id: "yamnet",
      nlists: null,
    });
  });
});
