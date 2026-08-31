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
    // Distinguishes the per-library pipeline state (pipeline_libraries[].state is
    // derived from the four pipeline axes via _derive_pipeline_state) from the
    // global processing status (is_processing = needs_tagging_count > 0). Here a
    // library is actively scanning (per-library state "scanning", is_scanning
    // true) while no files are pending ML tagging (is_processing false).
    const response = {
      is_scanning: true,
      scanning_libraries: [
        { library_id: "My Library", name: "My Library", progress: 120, total: 500 },
      ],
      pipeline_libraries: [
        {
          library_id: "My Library",
          name: "My Library",
          state: "scanning",
          library_auto_write: true,
        },
      ],
      is_processing: false,
      pending_files: 0,
      processed_files: 500,
      total_files: 500,
      files_per_minute: 3.5,
      estimated_minutes_remaining: null,
      is_busy: true,
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getWorkStatus()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/machine-learning/work-status");
  });
});
