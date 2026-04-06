import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  create,
  getRecentActivity,
  getStats,
  list,
  update,
  writeTags,
} from "../../../shared/api/library";
import { getWorkStatus } from "../../../shared/api/processing";
import type { Library } from "../../../shared/types";
import { renderWithProviders, screen, userEvent, waitFor } from "../../../test/render";
import { DashboardPage } from "../../dashboard/DashboardPage";

import { LibraryManagement } from "./LibraryManagement";

const {
  mockShowSuccess,
  mockShowError,
} = vi.hoisted(() => ({
  mockShowSuccess: vi.fn(),
  mockShowError: vi.fn(),
}));

vi.mock("../../../shared/api/library", () => ({
  list: vi.fn().mockResolvedValue([]),
  create: vi.fn(),
  update: vi.fn(),
  writeTags: vi.fn().mockResolvedValue({ status: "started", task_id: "task123" }),
  scanQuick: vi.fn(),
  scanFull: vi.fn(),
  deleteLibrary: vi.fn(),
  updateWriteMode: vi.fn(),
  getStats: vi.fn(),
  getRecentActivity: vi.fn(),
}));

vi.mock("../../../shared/api/config", () => ({
  getConfig: vi.fn().mockResolvedValue({ library_root: "/music" }),
}));

vi.mock("../../../shared/api/processing", () => ({
  getWorkStatus: vi.fn().mockResolvedValue({ is_busy: false }),
}));

vi.mock("../hooks/useLibraryVectorConfig", () => ({
  useLibraryVectorConfig: vi.fn().mockReturnValue({
    config: null,
    loading: false,
    saving: false,
    updateConfig: vi.fn(),
  }),
}));

vi.mock("../hooks/useLibraryVectorStats", () => ({
  useLibraryVectorStats: vi.fn().mockReturnValue({ stats: null }),
}));

vi.mock("../../../hooks/useNotification", () => ({
  useNotification: vi.fn().mockReturnValue({
    showSuccess: mockShowSuccess,
    showError: mockShowError,
  }),
}));

vi.mock("../../../shared/components/ServerFilePicker", () => ({
  ServerFilePicker: () => null,
}));

vi.mock("./VectorConfigSection", () => ({
  VectorConfigSection: () => null,
}));

vi.mock("./VectorStatsCard", () => ({
  VectorStatsCard: () => null,
}));

vi.mock("@mui/x-charts/PieChart", () => ({
  PieChart: () => null,
}));

const libraryFixture: Library = {
  library_id: "libraries:123",
  name: "library name",
  rootPath: "/music/library-name",
  isEnabled: true,
  watchMode: "off",
  fileWriteMode: "full",
  libraryAutoWrite: false,
  scannedAt: "2026-04-05T00:00:00Z",
  fileCount: 42,
  folderCount: 3,
};

const workStatusFixture = {
  is_scanning: false,
  scanning_libraries: [],
  pipeline_libraries: [
    {
      library_id: "libraries:123",
      name: "library name",
      state: "write_ready",
      library_auto_write: false,
    },
    {
      library_id: "libraries:456",
      name: "tiny library",
      state: "too_small",
      library_auto_write: true,
    },
  ],
  is_processing: false,
  pending_files: 0,
  processed_files: 42,
  total_files: 42,
  files_per_minute: 0,
  estimated_minutes_remaining: null,
  is_busy: false,
};

describe("LibraryManagement", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();

    vi.mocked(list).mockResolvedValue([libraryFixture]);
    vi.mocked(create).mockResolvedValue({ ...libraryFixture, libraryAutoWrite: true });
    vi.mocked(update).mockResolvedValue({ ...libraryFixture, libraryAutoWrite: true });
    vi.mocked(writeTags).mockResolvedValue({ status: "started", task_id: "task123" });
    vi.mocked(getWorkStatus).mockResolvedValue(workStatusFixture);
    vi.mocked(getStats).mockResolvedValue({
      total_files: 42,
      unique_artists: 6,
      unique_albums: 4,
      total_duration_seconds: 3600,
    });
    vi.mocked(getRecentActivity).mockResolvedValue({ files: [] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts tag reconciliation and shows a success message when polling completes immediately", async () => {
    const user = userEvent.setup();

    renderWithProviders(<LibraryManagement />);

    await waitFor(() => {
      expect(screen.getByText("library name")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Write Tags" }));

    await waitFor(() => {
      expect(writeTags).toHaveBeenCalledWith("libraries:123");
    });
    expect(mockShowSuccess).toHaveBeenCalledWith("Tag write started");
  });

  it("shows an error message when starting tag reconciliation fails", async () => {
    vi.mocked(writeTags).mockRejectedValue(new Error("Network error"));
    const user = userEvent.setup();

    renderWithProviders(<LibraryManagement />);

    await waitFor(() => {
      expect(screen.getByText("library name")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Write Tags" }));

    await waitFor(() => {
      expect(screen.getByText("Network error")).toBeInTheDocument();
    });
    expect(mockShowSuccess).not.toHaveBeenCalled();
  });

  it("shows the auto-write confirmation dialog and keeps the toggle off when cancelled", async () => {
    const user = userEvent.setup();

    renderWithProviders(<LibraryManagement />);

    await user.click(await screen.findByRole("button", { name: "+ Add Library" }));

    const autoWriteToggle = screen.getByRole("switch", {
      name: /automatically write tags to audio files when processing completes/i,
    });

    expect(autoWriteToggle).not.toBeChecked();

    await user.click(autoWriteToggle);

    expect(
      await screen.findByText(
        "This will write tags to audio files automatically when processing completes. Are you sure?",
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => {
      expect(
        screen.queryByText(
          "This will write tags to audio files automatically when processing completes. Are you sure?",
        ),
      ).not.toBeInTheDocument();
    });
    expect(autoWriteToggle).not.toBeChecked();
  });

  it("persists confirmed auto-write state in the create payload", async () => {
    const user = userEvent.setup();

    renderWithProviders(<LibraryManagement />);

    await user.click(await screen.findByRole("button", { name: "+ Add Library" }));

    await user.type(screen.getByPlaceholderText("/music"), "/music/new-library");

    const autoWriteToggle = screen.getByRole("switch", {
      name: /automatically write tags to audio files when processing completes/i,
    });

    await user.click(autoWriteToggle);
    await user.click(await screen.findByRole("button", { name: "Confirm" }));

    await waitFor(() => {
      expect(autoWriteToggle).toBeChecked();
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Enable Auto-Write?" })).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => {
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({
          rootPath: "/music/new-library",
          libraryAutoWrite: true,
        }),
      );
    });
  });

  it("persists confirmed auto-write state in the update payload", async () => {
    const user = userEvent.setup();

    renderWithProviders(<LibraryManagement />);

    await waitFor(() => {
      expect(screen.getByText("library name")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Edit" }));

    const autoWriteToggle = screen.getByRole("switch", {
      name: /automatically write tags to audio files when processing completes/i,
    });

    await user.click(autoWriteToggle);
    await user.click(await screen.findByRole("button", { name: "Confirm" }));

    await waitFor(() => {
      expect(autoWriteToggle).toBeChecked();
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Enable Auto-Write?" })).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Update" }));

    await waitFor(() => {
      expect(update).toHaveBeenCalledWith(
        "libraries:123",
        expect.objectContaining({
          libraryAutoWrite: true,
        }),
      );
    });
  });

  it("renders the dashboard pipeline section with library badges", async () => {
    renderWithProviders(<DashboardPage />);

    expect(await screen.findByText("Library Pipeline Progress")).toBeInTheDocument();
    expect(screen.getByText("library name")).toBeInTheDocument();
    expect(screen.getByText("tiny library")).toBeInTheDocument();
    expect(screen.getByText("Write ready")).toBeInTheDocument();
    expect(screen.getByText("Too small")).toBeInTheDocument();
    expect(screen.getByText("Ready for file writeback review.")).toBeInTheDocument();
    expect(screen.getByText("Needs more tagged files before calibration can continue.")).toBeInTheDocument();
  });
});
