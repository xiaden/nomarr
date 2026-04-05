import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, get, post } from "./client";
import { getReconcileStatus, reconcileTags } from "./library";

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    get: vi.fn(),
    post: vi.fn(),
  };
});

describe("reconcileTags", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts to the reconcile endpoint and returns the start result", async () => {
    const response = { status: "started", task_id: "task123" };
    vi.mocked(post).mockResolvedValue(response);

    await expect(reconcileTags("library-123")).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/libraries/library-123/reconcile-tags");
  });

  it("lets ApiError from post bubble up", async () => {
    const error = new ApiError(500, "Tag write failed");
    vi.mocked(post).mockRejectedValue(error);

    await expect(reconcileTags("library-123")).rejects.toBe(error);
  });
});

describe("getReconcileStatus", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the reconcile status and returns the API response", async () => {
    const response = { pending_count: 3, in_progress: true };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getReconcileStatus("library-123")).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/libraries/library-123/reconcile-status");
  });

  it("lets ApiError from get bubble up", async () => {
    const error = new ApiError(503, "Service unavailable");
    vi.mocked(get).mockRejectedValue(error);

    await expect(getReconcileStatus("library-123")).rejects.toBe(error);
  });
});
