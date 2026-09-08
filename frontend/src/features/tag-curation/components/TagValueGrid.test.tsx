import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders, screen, waitFor, userEvent } from "../../../test/render";

// Opaque complete-TagRef wire handles. The component must treat them as opaque
// string row/action keys and never derive them from the separate name/value fields.
const HANDLE_ELECTRONIC =
  "t1.eyJuYW1lIjoiZ2VucmUiLCJuYW1lc3BhY2UiOiJkZWZhdWx0IiwidmFsdWUiOiJFbGVjdHJvbmljIn0=";
const HANDLE_UNICODE =
  "t1.eyJuYW1lIjoiZ2VucmUiLCJuYW1lc3BhY2UiOiJkZWZhdWx0IiwidmFsdWUiOiJcdTAwYzlsZWN0cm9uaXF1ZSBcdWQ4M2RcdWRlMDAifQ==";
const HANDLE_NUMERIC =
  "t1.eyJuYW1lIjoiZ2VucmUiLCJuYW1lc3BhY2UiOiJkZWZhdWx0IiwidmFsdWUiOiIxMjAifQ==";

const { mockFetchTagValues, mockRenameTag, mockFetchTagSongs } = vi.hoisted(() => ({
  mockFetchTagValues: vi.fn(),
  mockRenameTag: vi.fn(),
  mockFetchTagSongs: vi.fn(),
}));

vi.mock("../../../shared/api/tagCuration", () => ({
  fetchTagValues: (...args: unknown[]) => mockFetchTagValues(...args),
  renameTag: (...args: unknown[]) => mockRenameTag(...args),
  mergeTags: vi.fn(),
  splitTag: vi.fn(),
  updateFileTags: vi.fn(),
  fetchTagSongs: (...args: unknown[]) => mockFetchTagSongs(...args),
  commitPendingTags: vi.fn(),
  fetchPendingCount: vi.fn(),
}));

import { TagValueGrid } from "./TagValueGrid";

const rowsFixture = [
  { id: HANDLE_ELECTRONIC, name: "genre", value: "Electronic", song_count: 4 },
  { id: HANDLE_UNICODE, name: "genre", value: "Électronique 😀", song_count: 2 },
  { id: HANDLE_NUMERIC, name: "genre", value: "120", song_count: 9 },
];

describe("TagValueGrid opaque handle propagation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetchTagValues.mockResolvedValue({ tags: rowsFixture, total: rowsFixture.length });
    mockRenameTag.mockResolvedValue({ moved: 1, merged_into_existing: false });
    mockFetchTagSongs.mockResolvedValue({ songs: [], total: 0 });
  });

  it("renders the separate name/value fields as display text (never the opaque id)", async () => {
    renderWithProviders(<TagValueGrid />);

    expect(await screen.findByText("Electronic")).toBeInTheDocument();
    expect(screen.getByText("Électronique 😀")).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
    // The opaque handles are row keys, not display text — none should be visible.
    expect(screen.queryByText(HANDLE_ELECTRONIC)).not.toBeInTheDocument();
    expect(screen.queryByText(HANDLE_NUMERIC)).not.toBeInTheDocument();
  });

  it("rolls back an inline rename when the action fails, restoring the row keyed by its opaque id", async () => {
    mockRenameTag.mockRejectedValue(new Error("Network error"));
    const user = userEvent.setup();

    renderWithProviders(<TagValueGrid />);

    // Open the "Electronic" value cell for inline editing.
    const cell = await screen.findByText("Electronic");
    await user.dblClick(cell);

    const input = await screen.findByRole("textbox");
    await user.clear(input);
    await user.type(input, "Electronica");
    await user.keyboard("{Enter}");

    // The rename must be addressed by the OPAQUE handle, never by the natural value.
    await waitFor(() => {
      expect(mockRenameTag).toHaveBeenCalledWith(HANDLE_ELECTRONIC, "Electronica");
    });

    // The failed edit rolls back to the original value (row restored by opaque key).
    await waitFor(() => {
      expect(screen.getByText("Electronic")).toBeInTheDocument();
    });
    expect(screen.queryByDisplayValue("Electronica")).not.toBeInTheDocument();
    expect(screen.getByText("Network error")).toBeInTheDocument();
  });

  it("expands a row by fetching songs with the row's opaque handle", async () => {
    mockFetchTagSongs.mockResolvedValue({
      songs: [
        {
          file_id: "101",
          title: "Électronique Anthem",
          artist: "A",
          album: "B",
          path: "/music/e.mp3",
        },
      ],
      total: 1,
    });
    const user = userEvent.setup();

    renderWithProviders(<TagValueGrid />);

    // Expand the row whose natural value is the numeric-looking string "120".
    await screen.findByText("120");
    const expandButtons = screen.getAllByRole("button", {
      name: /expand songs/i,
    });
    // The "120" row is last in the fixture; expand its button.
    await user.click(expandButtons[expandButtons.length - 1]);

    await waitFor(() => {
      expect(mockFetchTagSongs).toHaveBeenCalledWith(HANDLE_NUMERIC, 50, 0);
    });
    expect(await screen.findByText("Électronique Anthem")).toBeInTheDocument();
  });
});
