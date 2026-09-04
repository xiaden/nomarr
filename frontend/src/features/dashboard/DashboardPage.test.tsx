import { beforeEach, describe, expect, it, vi } from "vitest";

import { getRecentActivity, getStats } from "../../shared/api/library";
import { getWorkStatus } from "../../shared/api/processing";
import { renderWithProviders, screen, waitFor } from "../../test/render";

import { DashboardPage } from "./DashboardPage";

vi.mock("../../shared/api/library", () => ({
  getRecentActivity: vi.fn(),
  getStats: vi.fn(),
}));

vi.mock("../../shared/api/processing", () => ({
  getWorkStatus: vi.fn(),
}));

vi.mock("@mui/x-charts/PieChart", () => ({
  PieChart: () => null,
}));

const workStatus = {
  is_scanning: false,
  scanning_libraries: [],
  pipeline_libraries: [
    {
      library_id: "library-1",
      name: "Library 1",
      state: "awaiting_calibration",
      library_auto_write: false,
    },
  ],
  is_processing: false,
  pending_files: 0,
  processed_files: 10,
  total_files: 10,
  files_per_minute: 0,
  estimated_minutes_remaining: null,
  is_busy: false,
};

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.mocked(getWorkStatus).mockResolvedValue(workStatus);
    vi.mocked(getStats).mockResolvedValue({
      total_files: 10,
      unique_artists: 2,
      unique_albums: 3,
      total_duration_seconds: 600,
    });
    vi.mocked(getRecentActivity).mockResolvedValue({ files: [] });
  });

  it("highlights libraries awaiting calibration with an explanatory warning", async () => {
    renderWithProviders(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("Library 1")).toBeInTheDocument();
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Calibration is required before tag writing can continue.",
    );
    expect(screen.getByTestId("pipeline-state-badge")).toHaveTextContent("Awaiting calibration");
  });
});
