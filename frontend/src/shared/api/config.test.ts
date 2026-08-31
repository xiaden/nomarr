import { beforeEach, describe, expect, it, vi } from "vitest";

import { get, post } from "./client";
import {
  getConfig,
  updateConfig,
  type UpdateConfigResponse,
} from "./config";

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    get: vi.fn(),
    post: vi.fn(),
  };
});

describe("getConfig", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the config endpoint", async () => {
    const response = { scan_interval: 60, worker_enabled: true };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getConfig()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/config");
  });
});

describe("updateConfig", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts snake_case body to the config endpoint and returns {status, message}", async () => {
    const response: UpdateConfigResponse = {
      status: "success",
      message: "Config 'scan_interval' updated successfully.",
    };
    vi.mocked(post).mockResolvedValue(response);

    await expect(updateConfig("scan_interval", "60")).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/config", {
      key: "scan_interval",
      value: "60",
    });
  });
});
