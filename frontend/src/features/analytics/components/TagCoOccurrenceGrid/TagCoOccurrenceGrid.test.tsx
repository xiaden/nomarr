import { describe, expect, it, vi, beforeEach } from "vitest";

import { renderWithProviders, screen } from "../../../../test/render";
import { TagCoOccurrenceGrid } from "../TagCoOccurrenceGrid";

// Mock the API calls
vi.mock("../../../../shared/api/files", () => ({
  getUniqueTagKeys: vi.fn().mockResolvedValue({ tag_keys: ["genre", "year", "artist"], count: 3 }),
  getUniqueTagValues: vi.fn().mockImplementation((key: string) => {
    if (key === "genre") {
      return Promise.resolve({ tag_keys: ["Rock", "Pop", "Jazz"], count: 3 });
    }
    if (key === "year") {
      return Promise.resolve({ tag_keys: ["2020", "2021", "2022"], count: 3 });
    }
    return Promise.resolve({ tag_keys: [], count: 0 });
  }),
}));

vi.mock("../../../../shared/api/analytics", () => ({
  getTagCoOccurrence: vi.fn().mockResolvedValue({
    x: [
      { key: "genre", value: "Rock" },
      { key: "genre", value: "Pop" },
    ],
    y: [
      { key: "year", value: "2020" },
      { key: "year", value: "2021" },
    ],
    matrix: [
      [10, 5],
      [8, 12],
    ],
  }),
}));

describe("TagCoOccurrenceGrid", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("rendering", () => {
    it("renders section header", () => {
      renderWithProviders(<TagCoOccurrenceGrid />);
      expect(screen.getByText("Tag Co-Occurrence Grid")).toBeInTheDocument();
    });

    it("renders preset selectors for both axes", () => {
      renderWithProviders(<TagCoOccurrenceGrid />);
      expect(screen.getByText("X Axis:")).toBeInTheDocument();
      expect(screen.getByText("Y Axis:")).toBeInTheDocument();
    });

    it("renders all preset options", () => {
      renderWithProviders(<TagCoOccurrenceGrid />);
      // Each preset appears twice (X and Y axis selectors)
      const genreButtons = screen.getAllByText("Genre");
      const moodButtons = screen.getAllByText("Mood");
      const yearButtons = screen.getAllByText("Year");
      const manualButtons = screen.getAllByText("Manual");

      expect(genreButtons).toHaveLength(2);
      expect(moodButtons).toHaveLength(2);
      expect(yearButtons).toHaveLength(2);
      expect(manualButtons).toHaveLength(2);
    });

    it("renders swap button on Y axis row", () => {
      renderWithProviders(<TagCoOccurrenceGrid />);
      const swapButton = screen.getByRole("button", { name: /swap/i });
      expect(swapButton).toBeInTheDocument();
    });
  });

  describe("manual mode", () => {
    it("does not show manual selector when no axis is in manual mode", () => {
      renderWithProviders(<TagCoOccurrenceGrid />);

      // The accordion should not be visible initially
      expect(
        screen.queryByText("Advanced (Manual Tag Selection)")
      ).not.toBeInTheDocument();
    });
  });
});
