import { beforeEach, describe, expect, it, vi } from "vitest";

import { get } from "./client";
import { getTagValues, getTemplates } from "./navidrome";

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    get: vi.fn(),
  };
});

describe("getTagValues", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uses the singular navidrome tag-value endpoint", async () => {
    vi.mocked(get).mockResolvedValue({ name: "genre", values: ["Rock"] });

    await expect(getTagValues("genre")).resolves.toEqual(["Rock"]);

    expect(get).toHaveBeenCalledWith(expect.stringContaining("/tag-value?rel=genre"));
  });
});

describe("getTemplates", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the singular navidrome template endpoint", async () => {
    const response = { templates: [], total_count: 0 };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getTemplates()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/navidrome/template");
  });
});
