import { beforeEach, describe, expect, it, vi } from "vitest";

import { get } from "./client";
import { getVectorStats, listBackbones } from "./vectors";

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    get: vi.fn(),
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
