import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, get, post } from "./client";
import { getErroredFiles, getPipelineStatus, writeTags } from "./library";

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    get: vi.fn(),
    post: vi.fn(),
  };
});

describe("writeTags", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts to the write-tag endpoint and returns the start result", async () => {
    const response = { status: "started", task_id: "task123" };
    vi.mocked(post).mockResolvedValue(response);

    await expect(writeTags("library-123")).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/library/library-123/write-tag");
  });

  it("lets ApiError from post bubble up", async () => {
    const error = new ApiError(500, "Tag write failed");
    vi.mocked(post).mockRejectedValue(error);

    await expect(writeTags("library-123")).rejects.toBe(error);
  });
});

describe("getPipelineStatus", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets pipeline status for a library", async () => {
    const response = {
      library_id: "library-123",
      state: "write_ready",
      untagged_count: null,
      uncalibrated_count: null,
      pending_write_count: 12,
      library_auto_write: true,
      file_write_mode: "full" as const,
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getPipelineStatus("library-123")).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/library/library-123/pipeline");
  });
});

describe("getErroredFiles", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the singular errored-file endpoint", async () => {
    const response = { files: [], total: 0 };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getErroredFiles("library-123")).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/library/library-123/errored-file");
  });
});
