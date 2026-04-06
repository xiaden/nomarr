import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { list, writeTags } from "../../../shared/api/library";
import type { Library } from "../../../shared/types";
import { renderWithProviders, screen, userEvent, waitFor } from "../../../test/render";

import { LibraryManagement } from "./LibraryManagement";

const {
  mockShowSuccess,
  mockShowError,
  mockConfirm,
  mockHandleConfirm,
  mockHandleCancel,
} = vi.hoisted(() => ({
  mockShowSuccess: vi.fn(),
  mockShowError: vi.fn(),
  mockConfirm: vi.fn().mockResolvedValue(false),
  mockHandleConfirm: vi.fn(),
  mockHandleCancel: vi.fn(),
}));

vi.mock("../../../shared/api/library", () => ({
  list: vi.fn().mockResolvedValue([]),
  writeTags: vi.fn().mockResolvedValue({ status: "started", task_id: "task123" }),
  scanQuick: vi.fn(),
  scanFull: vi.fn(),
  deleteLibrary: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  updateWriteMode: vi.fn(),
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

vi.mock("../../../hooks/useConfirmDialog", () => ({
  useConfirmDialog: vi.fn().mockReturnValue({
    confirm: mockConfirm,
    isOpen: false,
    options: {},
    handleConfirm: mockHandleConfirm,
    handleCancel: mockHandleCancel,
  }),
}));

vi.mock("../../../shared/components/ServerFilePicker", () => ({
  ServerFilePicker: () => null,
}));

const libraryFixture: Library = {
  library_id: "libraries:123",
  name: "library name",
  rootPath: "/music/library-name",
  isEnabled: true,
  watchMode: "off",
  fileWriteMode: "full",
  scannedAt: "2026-04-05T00:00:00Z",
  fileCount: 42,
  folderCount: 3,
};

describe("LibraryManagement", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();

    vi.mocked(list).mockResolvedValue([libraryFixture]);
    vi.mocked(writeTags).mockResolvedValue({ status: "started", task_id: "task123" });
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
});
