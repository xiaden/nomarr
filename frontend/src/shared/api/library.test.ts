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

    await expect(writeTags("My Library")).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/library/My%20Library/write-tag");
  });

  it("URL-encodes special characters in the natural library name", async () => {
    const response = { status: "started", task_id: "task123" };
    vi.mocked(post).mockResolvedValue(response);

    await expect(writeTags("Rock/Acoustic & Chill")).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith(
      "/api/web/library/Rock%2FAcoustic%20%26%20Chill/write-tag",
    );
  });

  it("URL-encodes Unicode names (UTF-8 percent-escaped)", async () => {
    const response = { status: "started", task_id: "task123" };
    vi.mocked(post).mockResolvedValue(response);

    await expect(writeTags("École de Musique")).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith(
      "/api/web/library/%C3%89cole%20de%20Musique/write-tag",
    );
  });

  it("doubly-encodes literal percent signs in the natural name", async () => {
    const response = { status: "started", task_id: "task123" };
    vi.mocked(post).mockResolvedValue(response);

    await expect(writeTags("100% Pure")).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith(
      "/api/web/library/100%25%20Pure/write-tag",
    );
  });

  it("lets ApiError from post bubble up", async () => {
    const error = new ApiError(500, "Tag write failed");
    vi.mocked(post).mockRejectedValue(error);

    await expect(writeTags("My Library")).rejects.toBe(error);
  });
});

describe("getPipelineStatus", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets pipeline status for a library with the full four-axis shape", async () => {
    const response = {
      library_id: "My Library",
      scan_state: "idle",
      ml_state: "idle",
      calibration_state: "idle",
      tag_write_state: "idle",
      untagged_count: null,
      uncalibrated_count: null,
      pending_write_count: 12,
      library_auto_write: true,
      file_write_mode: "full",
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getPipelineStatus("My Library")).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/library/My%20Library/pipeline");
  });
});

describe("getErroredFiles", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the singular errored-file endpoint with the full backend shape", async () => {
    const response = {
      files: [
        {
          file_id: 42,
          path: "/music/album/01-broken.mp3",
          duration_seconds: 214.5,
          artist: "Some Artist",
          title: "Some Title",
        },
        {
          file_id: 7,
          path: "/music/album/02-unreadable.flac",
          duration_seconds: null,
          artist: null,
          title: null,
        },
      ],
      total: 2,
    };
    vi.mocked(get).mockResolvedValue(response);

    const result = await getErroredFiles("My Library");
    expect(result).toEqual(response);
    // Numeric file_id matches backend ErroredFileItemResponse.file_id:int.
    expect(result.files[0].file_id).toBeTypeOf("number");
    expect(result.files[1].file_id).toBeTypeOf("number");
    // Optional metadata fields stay nullable per backend model.
    expect(result.files[0].duration_seconds).toBeTypeOf("number");
    expect(result.files[1].duration_seconds).toBeNull();

    expect(get).toHaveBeenCalledWith("/api/web/library/My%20Library/errored-file");
  });
});
