import { beforeEach, describe, expect, it, vi } from "vitest";

import { del, get, post } from "./client";
import {
  clearCalibration,
  getAllHistograms,
  getApplyCombinedStatus,
  getHistogramCombinedStatus,
  getStatus,
  startApplyCalibration,
  startHistogramCalibration,
} from "./calibration";

// Mock at the wire layer: the client's `get`/`post`/`del` helpers are the
// request boundary, so asserting the exact path/body passed to them (and the
// verbatim-shaped response they resolve to) proves the client sends and
// consumes the exact backend contract from calibration_types.py.
vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    get: vi.fn(),
    post: vi.fn(),
    del: vi.fn(),
  };
});

describe("startApplyCalibration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts to the apply/start endpoint", async () => {
    const response = { status: "started", message: "Calibration apply started in background" };
    vi.mocked(post).mockResolvedValue(response);

    await expect(startApplyCalibration()).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/calibration/apply/start");
  });
});

describe("getApplyCombinedStatus", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets apply/status with nullable result/error/current_file", async () => {
    // ApplyCalibrationStatusResponse: result|None, error|None, current_file|None
    const response = {
      status: "running",
      result: null,
      error: null,
      total_files: 100,
      completed_files: 40,
      current_file: null,
      is_running: true,
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getApplyCombinedStatus()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/calibration/apply/status");
  });

  it("consumes a completed apply status with a populated result and current_file", async () => {
    const response = {
      status: "completed",
      result: { processed: 100, failed: 0, total: 100, message: "done" },
      error: null,
      total_files: 100,
      completed_files: 100,
      current_file: "/music/album/song.mp3",
      is_running: false,
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getApplyCombinedStatus()).resolves.toEqual(response);
  });
});

describe("getStatus", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets calibration status with nullable global_version and last_run", async () => {
    // CalibrationStatusResponse: global_version:str|None, last_run:int|None
    const response = { global_version: null, last_run: null, libraries: [] };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getStatus()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/calibration/status");
  });

  it("consumes a populated status with per-library breakdown", async () => {
    const response = {
      global_version: "v3",
      last_run: 1700000000000,
      libraries: [
        {
          library_id: "Main",
          library_name: "Main",
          total_files: 10,
          current_count: 8,
          outdated_count: 2,
          percentage: 80.0,
        },
      ],
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getStatus()).resolves.toEqual(response);
  });
});

describe("startHistogramCalibration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts to the histogram/start endpoint", async () => {
    const response = { status: "started", message: "Calibration generation started in background" };
    vi.mocked(post).mockResolvedValue(response);

    await expect(startHistogramCalibration()).resolves.toEqual(response);

    expect(post).toHaveBeenCalledWith("/api/web/calibration/histogram/start");
  });
});

describe("getHistogramCombinedStatus", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets histogram/status with nullable error/result/last_updated/current_head/current_head_index", async () => {
    // HistogramGenerationStatusResponse: error|None, result|None, last_updated|None,
    // current_head|None, current_head_index|None
    const response = {
      running: true,
      completed: false,
      error: null,
      result: null,
      current_head: null,
      current_head_index: null,
      total_heads: 12,
      completed_heads: 3,
      remaining_heads: 9,
      last_updated: null,
      is_running: true,
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getHistogramCombinedStatus()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/calibration/histogram/status");
  });

  it("consumes a running histogram status with populated nullable fields", async () => {
    const response = {
      running: true,
      completed: false,
      error: null,
      result: {
        version: 2,
        heads_processed: 3,
        heads_success: 3,
        heads_failed: 0,
        results: {
          mood_happy: { p5: 0.1, p95: 0.9, n: 100, underflow_count: 0, overflow_count: 0 },
        },
      },
      current_head: "mood_happy",
      current_head_index: 2,
      total_heads: 12,
      completed_heads: 3,
      remaining_heads: 9,
      last_updated: 1700000000000,
      is_running: true,
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getHistogramCombinedStatus()).resolves.toEqual(response);
  });
});

describe("getAllHistograms", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gets the flat histogram projection with nullable p5/p95 and optional metadata", async () => {
    // GetAllCalibrationHistogramsResponse{calibrations:[CalibrationHistogramItem]}
    // CalibrationHistogramItem: model_key, head_name, label, histogram_bins, p5|None,
    // p95|None, n, histogram_spec, calibration_def_hash|None, underflow_count|None,
    // overflow_count|None — all flat, no storage envelope/nested CalibrationState.
    const response = {
      calibrations: [
        {
          model_key: "0123456789abcdef",
          head_name: "mood_happy",
          label: "happy",
          histogram_bins: [{ val: 0.1, count: 5 }],
          p5: null,
          p95: null,
          n: 100,
          histogram_spec: { lo: 0, hi: 1, bins: 10, bin_width: 0.1 },
          calibration_def_hash: "def123",
          underflow_count: 0,
          overflow_count: 1,
        },
        {
          model_key: "fedcba9876543210",
          head_name: "genre",
          label: "rock",
          histogram_bins: [],
          p5: 0.2,
          p95: 0.8,
          n: 50,
          histogram_spec: { lo: 0, hi: 1, bins: 5, bin_width: 0.2 },
        },
      ],
    };
    vi.mocked(get).mockResolvedValue(response);

    await expect(getAllHistograms()).resolves.toEqual(response);

    expect(get).toHaveBeenCalledWith("/api/web/calibration/histogram");
  });
});

describe("clearCalibration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("DELETEs the calibration endpoint and surfaces the renamed bookkeeping_values_cleared field", async () => {
    // ClearCalibrationResponse{files_updated, bookkeeping_values_cleared}
    const response = { files_updated: 10, bookkeeping_values_cleared: 1 };
    vi.mocked(del).mockResolvedValue(response);

    await expect(clearCalibration()).resolves.toEqual(response);

    expect(del).toHaveBeenCalledWith("/api/web/calibration");
  });
});
