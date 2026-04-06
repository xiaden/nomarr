import { beforeEach, describe, expect, it, vi } from "vitest";

import { get, post } from "./client";
import { getModelOutputs, listModels, triggerVramProbe } from "./ml";

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    get: vi.fn(),
    post: vi.fn(),
  };
});

describe("listModels", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls the machine-learning model endpoint", async () => {
    const response: unknown[] = [];
    vi.mocked(get).mockResolvedValue(response);

    await expect(listModels()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/machine-learning/model");
  });
});

describe("getModelOutputs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls the machine-learning model output endpoint", async () => {
    const response: unknown[] = [];
    vi.mocked(get).mockResolvedValue(response);

    await expect(getModelOutputs("model-123")).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/machine-learning/model/model-123/output");
  });
});

describe("triggerVramProbe", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts to the machine-learning vram-probe endpoint", async () => {
    const response = { status: "probe_scheduled" };
    vi.mocked(post).mockResolvedValue(response);

    await expect(triggerVramProbe()).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/machine-learning/vram-probe");
  });
});
