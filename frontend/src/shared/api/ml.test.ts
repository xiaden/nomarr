import { beforeEach, describe, expect, it, vi } from "vitest";

import { get, patch, post } from "./client";
import {
  getModelOutputs,
  listModels,
  markModelConfigured,
  triggerVramProbe,
  updateOutputLabel,
} from "./ml";

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
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

describe("updateOutputLabel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("patches the model output endpoint with the label body", async () => {
    const response = { status: "updated" };
    vi.mocked(patch).mockResolvedValue(response);

    await expect(
      updateOutputLabel("model-123", "output-456", { label: "happy" })
    ).resolves.toEqual(response);

    expect(patch).toHaveBeenCalledWith(
      "/api/web/machine-learning/model/model-123/output/output-456",
      { label: "happy" }
    );
  });
});

describe("markModelConfigured", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts the boolean value body and returns the string fully_configured flag", async () => {
    const response = { status: "updated", fully_configured: "true" };
    vi.mocked(post).mockResolvedValue(response);

    await expect(markModelConfigured("model-123", { value: true })).resolves.toEqual(
      response
    );

    expect(post).toHaveBeenCalledWith(
      "/api/web/machine-learning/model/model-123/mark-configured",
      { value: true }
    );
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
