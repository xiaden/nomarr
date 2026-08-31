import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getCollectionOverview,
  getMoodAnalysis,
  getMoodDistribution,
  getTagCorrelations,
  getTagCoOccurrence,
  getTagFrequencies,
} from "./analytics";
import { get, post } from "./client";

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    get: vi.fn(),
    post: vi.fn(),
  };
});

describe("getTagFrequencies", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets tag frequencies with the snake_case limit query and response shape", async () => {
    const response = {
      tag_frequencies: [
        { tag_key: "nom:mood_happy", total_count: 42, unique_values: 3 },
      ],
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getTagFrequencies()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/analytics/tag-frequencies?limit=50");
  });

  it("uses the caller-provided limit", async () => {
    vi.mocked(get).mockResolvedValue({ tag_frequencies: [] });

    await getTagFrequencies(100);

    expect(get).toHaveBeenCalledWith("/api/web/analytics/tag-frequencies?limit=100");
  });
});

describe("getMoodDistribution", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets global mood distribution when no library id is given", async () => {
    const response = {
      mood_distribution: [{ mood: "happy", count: 10, percentage: 33.3 }],
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getMoodDistribution()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/analytics/mood-distribution");
  });

  it("URL-encodes the natural library name in the library_id query", async () => {
    const response = { mood_distribution: [] };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getMoodDistribution("Rock/Acoustic & Chill")).resolves.toEqual(
      response
    );

    expect(get).toHaveBeenCalledWith(
      "/api/web/analytics/mood-distribution?library_id=Rock%2FAcoustic%20%26%20Chill"
    );
  });
});

describe("getTagCorrelations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets tag correlations with the snake_case top_n query", async () => {
    const response = {
      mood_correlations: { happy: { rock: 0.5 } },
      mood_tier_correlations: { strict: { happy: 0.9 } },
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getTagCorrelations()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/analytics/tag-correlations?top_n=20");
  });
});

describe("getTagCoOccurrence", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts the x/y tag spec body to the tag-co-occurrences endpoint", async () => {
    const body = {
      x: [{ key: "mood-strict", value: "happy" }],
      y: [{ key: "genre", value: "rock" }],
    };
    const response = {
      x: [{ key: "mood-strict", value: "happy" }],
      y: [{ key: "genre", value: "rock" }],
      matrix: [
        [3],
      ],
    };
    vi.mocked(post).mockResolvedValue(response);

    await expect(getTagCoOccurrence(body)).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith(
      "/api/web/analytics/tag-co-occurrences",
      body
    );
  });

  it("appends the URL-encoded library_id query when a library is given", async () => {
    const body = {
      x: [{ key: "mood-strict", value: "happy" }],
      y: [{ key: "genre", value: "rock" }],
    };
    vi.mocked(post).mockResolvedValue({ x: [], y: [], matrix: [] });

    await getTagCoOccurrence(body, "My Lib");

    expect(post).toHaveBeenCalledWith(
      "/api/web/analytics/tag-co-occurrences?library_id=My%20Lib",
      body
    );
  });
});

describe("getCollectionOverview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets collection overview with backend-shaped stats and distributions", async () => {
    const response = {
      stats: {
        file_count: 100,
        total_duration_ms: 3600000,
        total_file_size_bytes: 1048576,
        avg_track_length_ms: 240000,
      },
      year_distribution: [{ year: 2020, count: 50 }],
      genre_distribution: [{ genre: "Rock", count: 60 }],
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getCollectionOverview()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/analytics/collection-overview");
  });

  it("URL-encodes the library_id query for a natural library name", async () => {
    vi.mocked(get).mockResolvedValue({
      stats: {
        file_count: 0,
        total_duration_ms: 0,
        total_file_size_bytes: 0,
        avg_track_length_ms: 0,
      },
      year_distribution: [],
      genre_distribution: [],
    });

    await getCollectionOverview("Rock/Acoustic & Chill");

    expect(get).toHaveBeenCalledWith(
      "/api/web/analytics/collection-overview?library_id=Rock%2FAcoustic%20%26%20Chill"
    );
  });
});

describe("getMoodAnalysis", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets mood analysis with backend-shaped response fields", async () => {
    const response = {
      coverage: {
        total_files: 100,
        tiers: { strict: { tagged: 80, percentage: 80 } },
      },
      balance: { strict: [{ mood: "happy", count: 20 }] },
      top_pairs_by_tier: { strict: [{ mood1: "happy", mood2: "chill", count: 5 }] },
      dominant_vibes: [{ mood: "happy", percentage: 40 }],
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getMoodAnalysis()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/analytics/mood-analysis");
  });

  it("URL-encodes the library_id query for a natural library name", async () => {
    vi.mocked(get).mockResolvedValue({
      coverage: { total_files: 0, tiers: {} },
      balance: {},
      top_pairs_by_tier: {},
      dominant_vibes: [],
    });

    await getMoodAnalysis("Rock/Acoustic & Chill");

    expect(get).toHaveBeenCalledWith(
      "/api/web/analytics/mood-analysis?library_id=Rock%2FAcoustic%20%26%20Chill"
    );
  });
});
