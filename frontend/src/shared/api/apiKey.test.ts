import { beforeEach, describe, expect, it, vi } from "vitest";

import { getApiKey, regenerateApiKey } from "./apiKey";
import { get, post } from "./client";

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    get: vi.fn(),
    post: vi.fn(),
  };
});

describe("getApiKey", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the current API key from the api-key endpoint", async () => {
    const response = { api_key: "nomarr-secret-key" };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getApiKey()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/api-key");
  });
});

describe("regenerateApiKey", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts to the api-key regenerate endpoint and returns the new key", async () => {
    const response = { api_key: "new-key-456" };
    vi.mocked(post).mockResolvedValue(response);

    await expect(regenerateApiKey()).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/api-key/regenerate");
  });
});
