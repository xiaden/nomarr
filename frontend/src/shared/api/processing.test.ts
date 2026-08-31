import { beforeEach, describe, expect, it, vi } from "vitest";

import { get } from "./client";
import { getWorkStatus } from "./processing";

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    get: vi.fn(),
  };
});

describe("getWorkStatus", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls the canonical work-status endpoint", async () => {
    const response = {
      is_scanning: false,
      scanning_libraries: [],
      pipeline_libraries: [
        {
          library_id: "My Library",
          name: "My Library",
          state: "idle",
          library_auto_write: true,
        },
      ],
      is_processing: false,
      pending_files: 0,
      processed_files: 0,
      total_files: 0,
      files_per_minute: 0,
      estimated_minutes_remaining: null,
      is_busy: false,
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getWorkStatus()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/machine-learning/work-status");
  });
});
